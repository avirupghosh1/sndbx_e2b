"""Tests for Option 2 (LLM outside, sandbox as tool) helpers — stdlib only."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
sys.path.insert(0, str(EXAMPLES))

import llm_sandbox_tools_demo as demo  # noqa: E402


class TestOption2Helpers(unittest.TestCase):
    def test_extract_json_object_plain(self):
        s = '{"action": "done", "thought": "x"}'
        self.assertEqual(demo.extract_json_object(s), s)

    def test_extract_json_object_fenced(self):
        s = '```json\n{"action": "done"}\n```'
        out = demo.extract_json_object(s)
        self.assertEqual(json.loads(out)["action"], "done")

    def test_safe_workspace_path(self):
        self.assertTrue(demo.safe_workspace_path("/workspace/calc.py"))
        self.assertFalse(demo.safe_workspace_path("/etc/passwd"))
        self.assertFalse(demo.safe_workspace_path("/workspace/../etc/passwd"))

    def test_execute_tool_done(self):
        class _Sb:
            pass

        self.assertEqual(demo.execute_tool(_Sb(), {"action": "done"}), "DONE")

    def test_execute_tool_unknown(self):
        class _Sb:
            pass

        self.assertIn("unknown", demo.execute_tool(_Sb(), {"action": "fly"}).lower())

    def test_execute_tool_write_mock(self):
        calls = []

        class FakeFiles:
            def write(self, path, content):
                calls.append((path, content))

        class FakeSb:
            files = FakeFiles()

        obs = demo.execute_tool(
            FakeSb(),
            {"action": "write_file", "path": "/workspace/a.py", "content": "print(1)"},
        )
        self.assertIn("OK", obs)
        self.assertEqual(calls, [("/workspace/a.py", "print(1)")])


if __name__ == "__main__":
    unittest.main()
