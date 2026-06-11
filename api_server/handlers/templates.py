"""Logical sandbox templates (Docker): base image + env + start_cmd + one-time warm snapshot."""

import re

from fastapi import APIRouter, Depends, HTTPException
from typing import List

from async_runner import run_io
from models import RegisterTemplateRequest
from models.responses import TemplateDefinitionResponse
from middleware import validate_api_key
from orchestrator import SandboxManager

router = APIRouter(prefix="/templates", tags=["templates"])

_TEMPLATE_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{0,62}$")


def _validate_template_id(template_id: str) -> str:
    tid = template_id.strip()
    if not _TEMPLATE_ID_RE.match(tid):
        raise HTTPException(
            status_code=400,
            detail=(
                "template_id must be 1–63 chars, start with a letter, "
                "and use only [a-zA-Z0-9._-] (no `/` — use base_image for the Docker ref)."
            ),
        )
    return tid


@router.post("", response_model=TemplateDefinitionResponse)
async def register_template(
    request: RegisterTemplateRequest,
    api_key: str = Depends(validate_api_key),
    sandbox_manager: SandboxManager = Depends(lambda: SandboxManager.__dict__.get("instance")),
):
    """Register or update a logical template (clears any previous warm snapshot)."""
    tid = _validate_template_id(request.template_id)
    row = await run_io(
        sandbox_manager.db.upsert_sandbox_template,
        tid,
        request.base_image.strip(),
        request.env or {},
        (request.start_cmd or "").strip(),
        int(request.settle_seconds),
    )
    return TemplateDefinitionResponse(**_row_to_response(row))


@router.get("", response_model=List[TemplateDefinitionResponse])
async def list_templates(
    api_key: str = Depends(validate_api_key),
    sandbox_manager: SandboxManager = Depends(lambda: SandboxManager.__dict__.get("instance")),
):
    rows = await run_io(sandbox_manager.db.list_sandbox_templates)
    return [TemplateDefinitionResponse(**_row_to_response(r)) for r in rows]


@router.get("/{template_id}", response_model=TemplateDefinitionResponse)
async def get_template(
    template_id: str,
    api_key: str = Depends(validate_api_key),
    sandbox_manager: SandboxManager = Depends(lambda: SandboxManager.__dict__.get("instance")),
):
    row = await run_io(sandbox_manager.db.get_sandbox_template, template_id.strip())
    if not row:
        raise HTTPException(status_code=404, detail=f"Unknown template_id: {template_id}")
    return TemplateDefinitionResponse(**_row_to_response(row))


def _row_to_response(row: dict) -> dict:
    return {
        "template_id": row["template_id"],
        "base_image": row["base_image"],
        "env": dict(row.get("env") or {}),
        "start_cmd": row.get("start_cmd") or "",
        "settle_seconds": int(row.get("settle_seconds") or 20),
        "warm_snapshot_image": row.get("warm_snapshot_image"),
        "build_error": row.get("build_error"),
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
    }
