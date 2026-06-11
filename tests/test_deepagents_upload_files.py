"""Unit tests for Deep Agents ``SandboxDeepAgentBackend.upload_files``."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "my_sandbox_sdk"))

from my_sdk.integrations import deepagents_backend as deepagents_backend_mod  # noqa: E402
from my_sdk.integrations.deepagents_backend import SandboxDeepAgentBackend  # noqa: E402


def _cmd_result(exit_code: int, stdout: str = "", stderr: str = "") -> MagicMock:
    r = MagicMock()
    r.exit_code = exit_code
    r.stdout = stdout
    r.stderr = stderr
    return r


class TestPythonScriptPathExtraction(unittest.TestCase):
    def test_extracts_absolute_py_paths(self):
        self.assertEqual(
            deepagents_backend_mod._python_script_paths("python3 /tmp/coinflip.py"),
            ["/tmp/coinflip.py"],
        )
        self.assertEqual(
            deepagents_backend_mod._python_script_paths("cd / && python3 /tmp/a.py && python /tmp/b.py"),
            ["/tmp/a.py", "/tmp/b.py"],
        )


class TestDeepAgentsUploadFiles(unittest.TestCase):
    def test_upload_files_calls_write_then_verify(self):
        sb = MagicMock()
        sb.sandbox_id = "sb-test"
        sb.files.write.return_value = MagicMock()
        sb.commands.run.return_value = _cmd_result(0, stdout="-rw-r--r-- 1 root root 3 Jan 1 00:00 /workspace/x.py")

        backend = SandboxDeepAgentBackend(sandbox=sb)
        out = backend.upload_files([("/workspace/x.py", b"abc")])

        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0].error)
        self.assertEqual(out[0].path, "/workspace/x.py")
        sb.files.write.assert_called_once_with("/workspace/x.py", "abc")
        sb.commands.run.assert_called_once()
        call_kw = sb.commands.run.call_args[1]
        self.assertEqual(call_kw.get("cwd"), "/")

    def test_upload_files_surfaces_error_when_verify_fails(self):
        sb = MagicMock()
        sb.sandbox_id = "sb-test"
        sb.files.write.return_value = MagicMock()
        sb.commands.run.return_value = _cmd_result(1, stdout="", stderr="missing")

        backend = SandboxDeepAgentBackend(sandbox=sb)
        out = backend.upload_files([("/workspace/missing.py", b"x")])

        self.assertEqual(len(out), 1)
        self.assertIsNotNone(out[0].error)
        self.assertIn("write_verify_failed", out[0].error)

    def test_upload_files_non_utf8(self):
        sb = MagicMock()
        backend = SandboxDeepAgentBackend(sandbox=sb)
        out = backend.upload_files([("/b.bin", b"\xff\xfe")])

        self.assertEqual(out[0].error, "invalid_path")
        sb.files.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
