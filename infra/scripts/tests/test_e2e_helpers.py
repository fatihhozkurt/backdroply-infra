from __future__ import annotations

import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "e2e_full_probe.py"
SPEC = importlib.util.spec_from_file_location("e2e_full_probe", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class E2EHelpersTest(unittest.TestCase):
    def test_read_env_map_parses_pairs_and_ignores_comments(self):
        content = "\n# comment\nA=1\nB = two\nINVALID_LINE\n"
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text(content, encoding="utf-8")
            result = MODULE.read_env_map(env_file)

        self.assertEqual({"A": "1", "B": "two"}, result)

    def test_issue_jwt_contains_expected_claims(self):
        token = MODULE.issue_jwt(
            secret="x" * 48,
            user_id=42,
            email="user@example.com",
            name="User Name",
            expires_min=10,
        )

        header_b64, payload_b64, signature_b64 = token.split(".")
        self.assertTrue(signature_b64)

        payload_raw = base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4))
        payload = json.loads(payload_raw.decode("utf-8"))
        self.assertEqual("42", payload["sub"])
        self.assertEqual("user@example.com", payload["email"])
        self.assertEqual("User Name", payload["name"])
        self.assertGreater(payload["exp"], payload["iat"])


if __name__ == "__main__":
    unittest.main()

