"""Resolve the requested private company seal in local and cloud deployments."""
import base64
import hashlib
from pathlib import Path
import re
from .seal_storage import download_company_seal


COMPANY_SEAL_SHA256 = "9367225d53b33fbef008623f07f45c4eed38e17b2a001800b8cb96965c695357"


def resolve_company_seal(root, env, *, expected_sha256=COMPANY_SEAL_SHA256, storage_loader=None):
    """Use the local image, private storage, or a matching legacy cloud secret."""
    path = Path(root) / "assets" / "image.png"
    if path.is_file():
        return path, None, None
    storage_error = None
    if env.get("SUPABASE_URL") and env.get("SUPABASE_SECRET_KEY"):
        try:
            loader = storage_loader or download_company_seal
            data = loader(env, expected_sha256)
            if not data.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(data).hexdigest() != expected_sha256:
                raise RuntimeError("The Supabase seal does not match the requested image")
            return path, data, None
        except (ValueError, RuntimeError, OSError) as exc:
            storage_error = str(exc)
    encoded = str(env.get("KEKOREA_COMPANY_SEAL_BASE64", "")).strip()
    if not encoded:
        return path, None, storage_error or "Upload assets/image.png to the private Supabase seal bucket"
    encoded = re.sub(r"\s+", "", encoded)
    encoded = re.sub(r"^data:image/png;base64,", "", encoded, flags=re.IGNORECASE)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return path, None, "KEKOREA_COMPANY_SEAL_BASE64 is not valid Base64"
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return path, None, "KEKOREA_COMPANY_SEAL_BASE64 does not contain a PNG image"
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        return path, None, storage_error or "KEKOREA_COMPANY_SEAL_BASE64 does not match assets/image.png; upload the new image to private Supabase storage"
    return path, data, None
