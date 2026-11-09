from copy import deepcopy

from app.config import DEFAULT_REQUIRED_FIELDS
from app.graph.state import RequiredFields

FIELD_LABELS = {field["key"]: field["label"] for field in DEFAULT_REQUIRED_FIELDS}


def get_required_fields(user_id: int) -> RequiredFields:
    return {"fields": deepcopy(DEFAULT_REQUIRED_FIELDS), "source": "config", "evidence": []}
