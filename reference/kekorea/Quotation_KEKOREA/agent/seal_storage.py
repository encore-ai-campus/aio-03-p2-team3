"""Keep the company seal in a private Supabase Storage bucket."""
import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


BUCKET = "kekorea-private-seal"
MAX_SEAL_BYTES = 5 * 1024 * 1024


def _request(env, endpoint, *, method="GET", data=None, content_type=None, opener=urlopen):
    url = str(env.get("SUPABASE_URL") or "").rstrip("/")
    key = str(env.get("SUPABASE_SECRET_KEY") or "").strip()
    parsed = urlparse(url)
    if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co")
            or parsed.query or parsed.fragment or parsed.path not in ("", "/") or not key):
        raise ValueError("SUPABASE_URL and SUPABASE_SECRET_KEY must be configured for private seal storage")
    headers = {"apikey": key, "Accept": "application/json", "User-Agent": "KEKOREA-Document-App/1.0"}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url + "/storage/v1/" + endpoint, data=data, headers=headers, method=method)
    try:
        with opener(request, timeout=30) as response:
            content = response.read(MAX_SEAL_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 400:
            try:
                detail = json.loads(exc.read(4096).decode("utf-8"))
                if isinstance(detail, dict) and str(detail.get("statusCode")) == "404":
                    return None
            except (ValueError, UnicodeError, OSError):
                pass
        raise RuntimeError(f"Supabase seal storage request failed (HTTP {exc.code})") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Supabase seal storage could not be reached") from None
    if len(content) > MAX_SEAL_BYTES:
        raise RuntimeError("Supabase seal exceeds the permitted size")
    return content


def _private_bucket(env, *, opener=urlopen):
    data = _request(env, "bucket/" + BUCKET, opener=opener)
    if data is None:
        return False
    try:
        bucket = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise RuntimeError("Supabase returned invalid seal bucket details") from None
    if not isinstance(bucket, dict) or bucket.get("public") is not False:
        raise RuntimeError("The Supabase seal bucket must be private")
    return True


def download_company_seal(env, expected_sha256, *, opener=urlopen):
    """Download and verify the expected PNG, without exposing a public URL."""
    if not _private_bucket(env, opener=opener):
        raise RuntimeError("The private Supabase seal bucket has not been created")
    data = _request(env, f"object/authenticated/{BUCKET}/{expected_sha256}.png", opener=opener)
    if data is None:
        raise RuntimeError("The requested company seal has not been uploaded to Supabase")
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise RuntimeError("The Supabase seal does not match the requested image")
    return data


def upload_company_seal(env, data, expected_sha256, *, opener=urlopen):
    """Create a private bucket if needed; never overwrite a different object."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > MAX_SEAL_BYTES or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("assets/image.png does not match the configured company seal")
    if not _private_bucket(env, opener=opener):
        payload = json.dumps({"id": BUCKET, "name": BUCKET, "public": False}).encode("utf-8")
        _request(env, "bucket", method="POST", data=payload, content_type="application/json", opener=opener)
        if not _private_bucket(env, opener=opener):
            raise RuntimeError("The private seal bucket could not be verified")
    path = f"object/authenticated/{BUCKET}/{expected_sha256}.png"
    existing = _request(env, path, opener=opener)
    if existing is not None:
        if hashlib.sha256(existing).hexdigest() != expected_sha256:
            raise RuntimeError("An unexpected file already exists at the seal path; it was not overwritten")
        return "already present"
    _request(env, f"object/{BUCKET}/{expected_sha256}.png", method="POST", data=data,
             content_type="image/png", opener=opener)
    if download_company_seal(env, expected_sha256, opener=opener) != data:
        raise RuntimeError("Uploaded company seal could not be verified")
    return "uploaded"
