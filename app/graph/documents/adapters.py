"""PI/PO/CI/PL의 기존 operations/repository를 연결하는 조립 경계."""

from app.graph.schemas import ExecutionResult, WorkflowError
from app.services.openai_keys import user_openai
from app.trade.common import operations as common
from app.trade.common.models import DocumentError
from app.trade.common.rendering import render_approved_files
from app.trade.review import operations as review
from app.trade.review.models import Decision, ReviewRequest
from app.trade.review.repository import SQLReviews
from app.trade.pi import agent as pi_agent, operations as pi
from app.trade.pi.models import PIInput
from app.trade.pi.repository import pi_repository
from app.trade.pi.rendering import render_pi_files
from app.trade.po import agent as po_agent, operations as po
from app.trade.po.models import POInput
from app.trade.po.repository import po_repository
from app.trade.ci import agent as ci_agent, operations as ci
from app.trade.ci.models import CIInput
from app.trade.ci.repository import ci_repository
from app.trade.ci.rendering import render_ci_files
from app.trade.pl import agent as pl_agent, operations as pl
from app.trade.pl.models import PLInput, PackingDecision
from app.trade.pl.repository import pl_repository

IMPLEMENTATIONS = {
    "PI": (pi, PIInput, pi_repository, pi_agent.extract_pi, render_pi_files),
    "PO": (po, POInput, po_repository, po_agent.extract_po, render_approved_files),
    "CI": (ci, CIInput, ci_repository, ci_agent.extract_ci, render_ci_files),
    "PL": (pl, PLInput, pl_repository, pl_agent.extract_pl, render_approved_files),
}


class ExistingDocuments:
    def __init__(self, *, database, storage=None, key_cipher=None):
        self.database, self.storage, self.key_cipher = database, storage, key_cipher

    def get(self, actor_id, command):
        ops, _, repository, _, _ = IMPLEMENTATIONS[command.kind]
        try:
            result = common.get_document(command.document_id, repository=repository(self.database, actor_id), result=ops.result)
            if command.revision is not None and command.revision != result.revision:
                raise WorkflowError("document_changed")
            return result.model_dump(mode="json")
        except DocumentError as error:
            raise WorkflowError(error.code) from None

    def draft(self, actor_id, command):
        ops, model, factory, extractor, _ = IMPLEMENTATIONS[command.kind]
        repository = factory(self.database, actor_id)
        try:
            if command.values is not None:
                values = model.model_validate(command.values)
                if command.document_id is not None:
                    result = ops.revise(command.document_id, command.revision, values, repository=repository)
                else:
                    result = ops.create(values, repository=repository)
            elif command.document_id is not None:
                raise WorkflowError("revision_requires_values")
            else:
                if command.kind == "CI":
                    raise WorkflowError("ci_requires_source_pi_values")
                with user_openai(self.database, actor_id, cipher=self.key_cipher) as ai:
                    result = ops.extract(command.text, repository=repository, extractor=extractor)
                if ai.issue is not None:
                    raise WorkflowError(ai.issue.code)
            return result.model_dump(mode="json")
        except DocumentError as error:
            raise WorkflowError(error.code) from None

    def propose(self, actor_id, command, *, packing=False):
        ops, _, _, _, _ = IMPLEMENTATIONS[command.kind]
        repository = SQLReviews(self.database, actor_id, command.kind, self.storage)
        try:
            if packing:
                proposal = pl.packing_review(command.document_id, repository=pl_repository(self.database, actor_id))
                if command.revision is not None and command.revision != proposal["revision"]:
                    raise WorkflowError("document_changed")
                return {"kind": "PL", "document_id": command.document_id, "revision": proposal["revision"],
                        "proposal_hash": proposal["content_hash"], "preview": proposal["payload"]}
            document = repository.document(command.document_id)
            revision = command.revision if command.revision is not None else document["revision"]
            proposal = review.propose(command.document_id, ReviewRequest(revision=revision, formats=command.formats),
                                      repository=repository, check_document=ops.check)
            return {"kind": command.kind, "proposal_id": proposal["id"], "document_id": command.document_id,
                    "revision": proposal["revision"], "proposal_hash": proposal["content_hash"], "preview": proposal["payload"]}
        except DocumentError as error:
            raise WorkflowError(error.code) from None

    def _proposal(self, actor_id, action):
        payload = action.payload
        repository = SQLReviews(self.database, actor_id, payload["kind"], self.storage)
        decision = Decision(action="approve", revision=payload["revision"], content_hash=payload["proposal_hash"])
        proposal = review.check_decision(payload["proposal_id"], payload["document_id"], decision, repository=repository)
        if proposal["payload"] != payload["preview"]:
            raise WorkflowError("proposal_changed")
        return repository, decision, proposal

    def recheck(self, actor_id, action):
        try:
            if action.operation == "approve_packing":
                proposal = pl.packing_review(action.payload["document_id"], repository=pl_repository(self.database, actor_id))
                if proposal["content_hash"] != action.payload["proposal_hash"]:
                    raise WorkflowError("document_changed")
                return
            repository, _, proposal = self._proposal(actor_id, action)
            document = repository.document(action.payload["document_id"])
            if proposal["status"] != "pending" or document["revision"] != action.payload["revision"] or document["status"] != "ready":
                raise WorkflowError("document_changed")
            IMPLEMENTATIONS[action.payload["kind"]][0].check(document)
        except DocumentError as error:
            raise WorkflowError(error.code) from None

    def issue(self, actor_id, action):
        try:
            if action.operation == "approve_packing":
                pl.decide_packing(action.payload["document_id"], PackingDecision(action="approve",
                    revision=action.payload["revision"], content_hash=action.payload["proposal_hash"]),
                    repository=pl_repository(self.database, actor_id))
                return self.lookup(actor_id, action)
            repository, decision, _ = self._proposal(actor_id, action)
            renderer = IMPLEMENTATIONS[action.payload["kind"]][4]
            review.decide(action.payload["proposal_id"], action.payload["document_id"], decision,
                          repository=repository, renderer=renderer)
            return self.lookup(actor_id, action)
        except DocumentError as error:
            return ExecutionResult(status="failed", action_id=action.id, content_hash=action.content_hash, code=error.code)

    def lookup(self, actor_id, action):
        if action.operation == "approve_packing":
            repository = pl_repository(self.database, actor_id)
            document = repository.get(action.payload["document_id"])
            previous = repository.version(action.payload["document_id"], action.payload["revision"])
            original = previous.get("document", previous.get("payload", previous))
            matched = review.content_hash({"document_id": action.payload["document_id"],
                "revision": action.payload["revision"], "document": original}) == action.payload["proposal_hash"]
            if (matched and document["revision"] == action.payload["revision"] + 1
                    and (document.get("packing_totals") or {}).get("approved") is True):
                return ExecutionResult(status="succeeded", action_id=action.id, content_hash=action.content_hash,
                    receipt={"document_id": action.payload["document_id"], "revision": document["revision"], "packing_approved": True})
            return ExecutionResult(status="unknown", action_id=action.id, content_hash=action.content_hash, code="packing_unconfirmed")
        _, _, proposal = self._proposal(actor_id, action)
        if proposal["status"] == "approved" and proposal["files"]:
            return ExecutionResult(status="succeeded", action_id=action.id, content_hash=action.content_hash,
                receipt={"document_id": proposal["document_id"], "proposal_id": proposal["id"],
                         "file_ids": [file["id"] for file in proposal["files"]], "files": proposal["files"]})
        return ExecutionResult(status="unknown", action_id=action.id, content_hash=action.content_hash, code="issue_unconfirmed")

    def cancel(self, actor_id, action):
        if action.operation == "approve_packing":
            return None
        repository, decision, _ = self._proposal(actor_id, action)
        review.decide(action.payload["proposal_id"], action.payload["document_id"],
                      decision.model_copy(update={"action": "cancel"}), repository=repository,
                      renderer=IMPLEMENTATIONS[action.payload["kind"]][4])
