"""CONTRACT 6.4의 설치된 프롬프트/스키마만 교환한다. 임의 실행 명세를 받지 않는다."""
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_JSON_BYTES = 256 * 1024
MAX_VARIABLE_BYTES = 128 * 1024


class WorkerError(Exception):
    def __init__(self, code="invalid_input", status=400):
        self.code, self.status = code, status
        super().__init__(code)  # 입력/인증값/예외 원문을 보존하지 않는다.


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    @field_validator("protocol_version", mode="before", check_fields=False)
    @classmethod
    def integer_protocol(cls, value):
        if type(value) is not int:
            raise ValueError("protocol_version")
        return value

    @field_validator("ok", mode="before", check_fields=False)
    @classmethod
    def boolean_ok(cls, value):
        if type(value) is not bool:
            raise ValueError("ok")
        return value


class Capability(StrictModel):
    prompt_id: str
    prompt_version: str
    schema_id: str
    schema_version: Literal["v1"]
    prompt_sha256: str
    schema_sha256: str


class Capabilities(StrictModel):
    protocol_version: Literal[1]
    definitions: list[Capability] = Field(min_length=1, max_length=12)
    models: list[str] = Field(min_length=1, max_length=10)


class PairRequest(StrictModel):
    device_name: str = Field(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$")
    capabilities: Capabilities

    @field_validator("device_name")
    @classmethod
    def visible_name(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("device_name")
        return value


class PairPoll(StrictModel):
    device_secret: str = Field(min_length=40, max_length=100)


class ApprovePair(StrictModel):
    pairing_code: str = Field(min_length=16, max_length=100)
    device_name: str = Field(min_length=1, max_length=80)


class ExecutionMode(StrictModel):
    ai_execution_mode: Literal["stored_key", "local_worker"]


class JobRequest(StrictModel):
    protocol_version: Literal[1]
    kind: Literal["structured_ai_call"]
    job_id: str
    attempt_id: str
    device_id: str
    run_id: str
    prompt_id: str
    prompt_version: str
    schema_id: str
    schema_version: Literal["v1"]
    variables: dict[str, str | int]
    requested_model: str
    created_at: str
    expires_at: str


ErrorKind = Literal["rate_limit", "network", "invalid_output", "invalid_input", "internal",
                    "key_required", "owner_mismatch", "unsupported_version", "worker_unavailable", "expired"]


class Success(StrictModel):
    protocol_version: Literal[1]
    job_id: str
    attempt_id: str
    device_id: str
    schema_id: str
    schema_version: Literal["v1"]
    ok: Literal[True]
    value: dict
    duration_ms: int = Field(ge=0, le=30000)


class Failure(StrictModel):
    protocol_version: Literal[1]
    job_id: str
    attempt_id: str
    device_id: str
    schema_id: str
    schema_version: Literal["v1"]
    ok: Literal[False]
    error_kind: ErrorKind


@dataclass(frozen=True)
class Definition:
    prompt: object
    schema: type[BaseModel]
    variables: tuple[str, ...]

    def capability(self):
        return dict(prompt_id=self.prompt.NAME, prompt_version=self.prompt.VERSION,
                    schema_id=self.schema.__name__, schema_version="v1",
                    prompt_sha256=hashlib.sha256(self.prompt.TEMPLATE.encode()).hexdigest(),
                    schema_sha256=digest(self.schema.model_json_schema()))


@lru_cache(maxsize=1)
def definitions():
    from app.graph.nodes.analyze_email import EmailAnalysis
    from app.graph.nodes.reflect import ReflectAnalysis
    from app.services.memory import ThreadSummary
    from app.tools.draft_replies import DraftOutput
    from app.tools.draft_followup_replies import FollowupDraft
    from app.tools.extract_deal_terms import ExtractedDealTerms, ExtractedTradeDoc, ExtractedTradeCIDoc
    from app.prompts import analyze_email, draft_replies, draft_followup_replies, extract_deal_terms
    from app.prompts import extract_trade_terms, summarize_thread, reflect_fix
    from app.trade.pi import agent as pi
    from app.trade.po import agent as po
    from app.trade.ci import agent as ci
    from app.trade.pl import agent as pl
    from app.trade.common.extraction import wire_schema
    rows = [
        (analyze_email.PROMPT, EmailAnalysis, "thread_context email"),
        (draft_replies.PROMPT, DraftOutput, "candidate_min candidate_max reply_mode_guide trade_doc preferences feedback thread_context email"),
        (extract_deal_terms.PROMPT, ExtractedDealTerms, "email thread received_date feedback"),
        (extract_trade_terms.PROMPT, ExtractedTradeDoc, "document_type ci_rules thread email feedback"),
        (extract_trade_terms.PROMPT, ExtractedTradeCIDoc, "document_type ci_rules thread email feedback"),
        (draft_followup_replies.PROMPT, FollowupDraft, "missing_labels known_terms preferences thread email feedback"),
        (summarize_thread.PROMPT, ThreadSummary, "previous_summary confirmed_terms last_result messages"),
        (reflect_fix.PROMPT, ReflectAnalysis, "reply_mode strategy retry_target issues deal_summary"),
        (pi.PROMPT, wire_schema(pi.PIExtraction), "text"),
        (po.PROMPT, wire_schema(po.POExtraction), "text"),
        (ci.PROMPT, wire_schema(ci.CIExtraction), "text"),
        (pl.PROMPT, wire_schema(pl.PLExtraction), "text"),
    ]
    return [Definition(prompt, schema, tuple(keys.split())) for prompt, schema, keys in rows]


def manifest(model):
    return dict(protocol_version=1, definitions=[d.capability() for d in definitions()], models=[model])


def validate_capabilities(value, model):
    allowed = manifest(model)
    if value.protocol_version != 1 or value.models != [model]:
        raise WorkerError("unsupported_version", 409)
    entries = [d.model_dump() for d in value.definitions]
    if len({digest(d) for d in entries}) != len(entries) or any(d not in allowed["definitions"] for d in entries):
        raise WorkerError("unsupported_version", 409)
    return value.model_dump()


def find_definition(prompt_id, prompt_version, schema_id, schema_version):
    for d in definitions():
        if (d.prompt.NAME, d.prompt.VERSION, d.schema.__name__, "v1") == (prompt_id, prompt_version, schema_id, schema_version):
            return d
    raise WorkerError("unsupported_version", 409)


def validate_request(value, capabilities, model):
    try:
        if len(json_bytes(value)) > MAX_JSON_BYTES:
            raise WorkerError("payload_too_large", 413)
        job = JobRequest.model_validate(value)
        for key in ("job_id", "attempt_id", "device_id", "run_id"):
            UUID(getattr(job, key))
        definition = find_definition(job.prompt_id, job.prompt_version, job.schema_id, job.schema_version)
        if definition.capability() not in capabilities["definitions"] or job.requested_model != model or model not in capabilities["models"]:
            raise WorkerError("unsupported_version", 409)
        variables = job.variables
        if set(variables) != set(definition.variables):
            raise WorkerError()
        for key, val in variables.items():
            if key in ("candidate_min", "candidate_max"):
                if type(val) is not int or val != {"candidate_min": 2, "candidate_max": 3}[key]:
                    raise WorkerError()
            elif type(val) is not str or len(val.encode()) > MAX_VARIABLE_BYTES:
                raise WorkerError()
        if "text" in variables and len(variables["text"]) > 20000:
            raise WorkerError()
        if job.prompt_id == "extract_trade_terms":
            from app.tools.extract_deal_terms import CI_RULES
            kind = variables["document_type"]
            if kind not in {"PI", "PO", "CI", "PL"} or variables["ci_rules"] != (CI_RULES if kind == "CI" else ""):
                raise WorkerError()
            if (kind == "CI") != (job.schema_id == "ExtractedTradeCIDoc"):
                raise WorkerError()
        times = [datetime.fromisoformat(getattr(job, key).replace("Z", "+00:00")) for key in ("created_at", "expires_at")]
        if any(t.utcoffset() is None or t.utcoffset().total_seconds() != 0 for t in times) or not 0 < (times[1] - times[0]).total_seconds() <= 120:
            raise WorkerError()
        return job
    except (ValidationError, ValueError, TypeError, OverflowError):
        raise WorkerError() from None


def validate_result(value, schema_id, schema_version):
    try:
        if len(json_bytes(value)) > MAX_JSON_BYTES:
            raise WorkerError("payload_too_large", 413)
        result = (Success if value.get("ok") is True else Failure).model_validate(value)
        if (result.schema_id, result.schema_version) != (schema_id, schema_version):
            raise WorkerError("unsupported_version", 409)
        if result.ok:
            schema = next(d.schema for d in definitions() if d.schema.__name__ == schema_id)
            schema.model_validate(result.value, strict=True, extra="forbid")
        return result
    except (ValidationError, ValueError, TypeError, StopIteration):
        raise WorkerError("invalid_output", 422) from None
