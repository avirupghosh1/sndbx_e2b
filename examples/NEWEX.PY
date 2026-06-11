import sys
import os
import time
from pathlib import Path

import subprocess



_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO, "my_sandbox_sdk"))

from my_sdk.sync.sandbox import Sandbox
from my_sdk.integrations.deepagents_backend import SandboxDeepAgentBackend 
sandbox = Sandbox.create(
    api_url="http://localhost:8000",
    api_key="test-key-12345",
    template_id="python:3.11",
    request_timeout=900.0,
)
SandboxDeepAgentBackend(sandbox).upload_files([("/tmp/coinflip.py", b"print(1)\n")])
r=sandbox.commands.run("python3 /tmp/coinflip.py", cwd="/")
print(r.stdout)
sandbox.kill()
