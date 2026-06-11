"""Tests for loose JSON-in-text → tool_calls coercion (examples/deepagents_my_sandbox.py)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "my_sandbox_sdk"))

_EXAMPLE = ROOT / "examples" / "deepagents_my_sandbox.py"
_spec = importlib.util.spec_from_file_location("_deepagents_example", _EXAMPLE)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class TestLooseToolJsonCoercion(unittest.TestCase):
    def _coerce(self, content: str) -> AIMessage:
        msg = AIMessage(content=content)
        return _mod._coerce_json_in_content_to_tool_calls(msg)

    def test_action_and_flat_fields(self):
        body = """{
  "action": "write_file",
  "file_path": "/tmp/calculator.py",
  "content": "print(1)\\n"
}"""
        out = self._coerce(body)
        tcs = getattr(out, "tool_calls", None) or []
        self.assertEqual(len(tcs), 1)
        self.assertEqual(tcs[0]["name"], "write_file")
        self.assertEqual(tcs[0]["args"]["file_path"], "/tmp/calculator.py")
        self.assertIn("print(1)", tcs[0]["args"]["content"])

    def test_hybrid_name_arguments_and_top_level(self):
        body = """{
  "name": "write_file",
  "arguments": {"file_path": "/tmp/x.py", "content": "from_args"},
  "file_path": "/tmp/x.py",
  "content": "from_top"
}"""
        out = self._coerce(body)
        tcs = getattr(out, "tool_calls", None) or []
        self.assertEqual(len(tcs), 1)
        self.assertEqual(tcs[0]["name"], "write_file")
        self.assertEqual(tcs[0]["args"]["content"], "from_top")

    def test_tool_calls_array_loose_items(self):
        body = """{"tool_calls": [
          {"action": "execute", "command": "ls /tmp"}
        ]}"""
        out = self._coerce(body)
        tcs = getattr(out, "tool_calls", None) or []
        self.assertEqual(len(tcs), 1)
        self.assertEqual(tcs[0]["name"], "execute")
        self.assertEqual(tcs[0]["args"]["command"], "ls /tmp")

    def test_openai_function_blob(self):
        body = r"""{
  "function": {"name": "write_file", "arguments": "{\"file_path\": \"/a.py\", \"content\": \"x\"}"}
}"""
        out = self._coerce(body)
        tcs = getattr(out, "tool_calls", None) or []
        self.assertEqual(len(tcs), 1)
        self.assertEqual(tcs[0]["name"], "write_file")
        self.assertEqual(tcs[0]["args"]["file_path"], "/a.py")

    def test_type_field_as_tool_name(self):
        body = '{"type": "write_file", "file_path": "/tmp/calculator.py", "content": "print(2)\\n"}'
        out = self._coerce(body)
        tcs = getattr(out, "tool_calls", None) or []
        self.assertEqual(len(tcs), 1)
        self.assertEqual(tcs[0]["name"], "write_file")
        self.assertEqual(tcs[0]["args"]["file_path"], "/tmp/calculator.py")

    def test_type_object_not_treated_as_tool(self):
        body = '{"type": "object", "file_path": "/tmp/x.py"}'
        out = self._coerce(body)
        tcs = getattr(out, "tool_calls", None) or []
        self.assertEqual(len(tcs), 0)

    def test_invalid_json_unquoted_content_not_coerced(self):
        body = '{\n  "type": "write_file",\n  "file_path": "/tmp/calculator.py",\n  "content": NOT_A_STRING\n}'
        out = self._coerce(body)
        tcs = getattr(out, "tool_calls", None) or []
        self.assertEqual(len(tcs), 0)

    def test_skips_when_native_tool_calls_present(self):
        msg2 = AIMessage(
            content='{"action":"execute","command":"should_not_apply"}',
            tool_calls=[
                {"name": "execute", "args": {"command": "true"}, "id": "1", "type": "tool_call"}
            ],
        )
        out = _mod._coerce_json_in_content_to_tool_calls(msg2)
        self.assertEqual(len(out.tool_calls), 1)
        self.assertEqual(out.tool_calls[0]["name"], "execute")
        self.assertEqual(out.tool_calls[0]["args"]["command"], "true")


if __name__ == "__main__":
    unittest.main()
