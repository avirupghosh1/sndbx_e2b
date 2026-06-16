#!/usr/bin/env python3
"""
Minimal example: register a template from a Dockerfile (parsed mode) with COPY context,
then create a sandbox from that template.

Prerequisites
-------------
- API server running with Docker (``SANDBOX_ISOLATION=docker`` or ``gvisor``).
- Default ``TEMPLATE_DOCKERFILE_BUILD_MODE=parsed`` on the server (or unset = parsed).
- ``pip install -e ./my_sandbox_sdk`` from repo root (or adjust PYTHONPATH).

Environment
-----------
  export SANDBOX_API_URL=http://127.0.0.1:8000
  export API_KEY=your-key
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from my_sdk import Sandbox
from my_sdk.template import Template


def main() -> None:
    api_url = os.environ.get("SANDBOX_API_URL", "http://127.0.0.1:8000").rstrip("/")
    api_key = (os.environ.get("API_KEY") or os.environ.get("X_API_KEY") or "").strip() or None

    work = Path(tempfile.mkdtemp(prefix="sdk-tpl-"))
    try:
        # One file that will be COPY'd into the image (SDK builds context_tar_gzip_base64).
        note = work / "hello.txt"
        note.write_text("hello from build context\n", encoding="utf-8")

        tpl = (
            Template()
            .from_dockerfile(
                """
                FROM python:3.11-slim
                COPY hello.txt /opt/hello.txt
                """,
                context_dir=str(work)) 
        )

        template_id = "SdkDemoTpl"
        print("POST /templates/from-dockerfile (parsed) …")
        info = Template.build(
            tpl,
            template_id,
            api_url=api_url,
            api_key=api_key,
        )
        print("registered:", info.template_id, "warm_snapshot:", (info.definition or {}).get("warm_snapshot_image"))

        print("POST /sandboxes …")
        sb = Sandbox.create(api_url=api_url, api_key=api_key, template_id=template_id)
        try:
            r = sb.commands.run("cat /opt/hello.txt", timeout=60.0)
            print("command:", r.exit_code, repr(r.stdout.strip()))
        finally:
            sb.kill()
            print("sandbox killed.")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
