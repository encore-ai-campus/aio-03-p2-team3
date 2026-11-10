"""Seal selection must not silently use an older cloud image."""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlparse

from Quotation_KEKOREA.agent.branding import resolve_company_seal
from Quotation_KEKOREA.agent.seal_storage import BUCKET, download_company_seal, upload_company_seal


class FakeResponse:
    def __init__(self, content):
        self.content = content
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size=-1):
        return self.content[:size] if size >= 0 else self.content


class CompanySealTests(TestCase):
    def test_local_requested_image_takes_priority_over_old_secret(self):
        with patch.object(Path, "is_file", return_value=True):
            path, data, error = resolve_company_seal("root", {"KEKOREA_COMPANY_SEAL_BASE64": "old"})
        self.assertEqual(path.name, "image.png")
        self.assertIsNone(data)
        self.assertIsNone(error)

    def test_cloud_secret_must_match_requested_image(self):
        data = b"\x89PNG\r\n\x1a\nexample"
        encoded = base64.b64encode(data).decode("ascii")
        expected = hashlib.sha256(data).hexdigest()
        with patch.object(Path, "is_file", return_value=False):
            _, actual, error = resolve_company_seal("root", {"KEKOREA_COMPANY_SEAL_BASE64": encoded}, expected_sha256=expected)
            self.assertEqual(actual, data)
            self.assertIsNone(error)
            _, actual, error = resolve_company_seal("root", {"KEKOREA_COMPANY_SEAL_BASE64": encoded}, expected_sha256="0" * 64)
            self.assertIsNone(actual)
            self.assertIn("does not match", error)

    def test_missing_or_invalid_cloud_secret_reports_setup_error(self):
        with patch.object(Path, "is_file", return_value=False):
            self.assertIn("Upload", resolve_company_seal("root", {})[2])
            self.assertIn("Base64", resolve_company_seal("root", {"KEKOREA_COMPANY_SEAL_BASE64": "!"})[2])

    def test_private_storage_takes_priority_over_old_secret(self):
        data = b"\x89PNG\r\n\x1a\nexample"
        expected = hashlib.sha256(data).hexdigest()
        env = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SECRET_KEY": "sb_secret_test",
               "KEKOREA_COMPANY_SEAL_BASE64": "outdated"}
        with patch.object(Path, "is_file", return_value=False):
            _, actual, error = resolve_company_seal("root", env, expected_sha256=expected,
                                                    storage_loader=lambda config, sha: data)
        self.assertEqual(actual, data)
        self.assertIsNone(error)

    def test_upload_creates_private_bucket_and_verifies_download(self):
        data = b"\x89PNG\r\n\x1a\nexample"
        expected = hashlib.sha256(data).hexdigest()
        env = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SECRET_KEY": "sb_secret_test"}
        state = {"bucket": False, "object": None, "requests": []}
        def opener(request, timeout):
            path = urlparse(request.full_url).path
            state["requests"].append((request.get_method(), path, request.get_header("Apikey")))
            if path == f"/storage/v1/bucket/{BUCKET}":
                if not state["bucket"]:
                    raise HTTPError(request.full_url, 400, "not found", {}, BytesIO(b'{"statusCode":"404","error":"Bucket not found"}'))
                return FakeResponse(json.dumps({"public": False}).encode())
            if path == "/storage/v1/bucket" and request.get_method() == "POST":
                self.assertFalse(json.loads(request.data)["public"])
                state["bucket"] = True
                return FakeResponse(b"{}")
            if path == f"/storage/v1/object/authenticated/{BUCKET}/{expected}.png":
                if state["object"] is None:
                    raise HTTPError(request.full_url, 400, "not found", {}, BytesIO(b'{"statusCode":"404","error":"Object not found"}'))
                return FakeResponse(state["object"])
            if path == f"/storage/v1/object/{BUCKET}/{expected}.png" and request.get_method() == "POST":
                state["object"] = request.data
                return FakeResponse(b"{}")
            raise AssertionError(path)
        self.assertEqual(upload_company_seal(env, data, expected, opener=opener), "uploaded")
        self.assertEqual(download_company_seal(env, expected, opener=opener), data)
        self.assertTrue(all(key == "sb_secret_test" for _, _, key in state["requests"]))
        self.assertEqual(upload_company_seal(env, data, expected, opener=opener), "already present")

    def test_public_bucket_is_rejected_before_upload(self):
        env = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SECRET_KEY": "sb_secret_test"}
        data = b"\x89PNG\r\n\x1a\nexample"
        with self.assertRaisesRegex(RuntimeError, "must be private"):
            upload_company_seal(env, data, hashlib.sha256(data).hexdigest(),
                                opener=lambda request, timeout: FakeResponse(b'{"public":true}'))
