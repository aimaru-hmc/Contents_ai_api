from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from full_toc_core import args_from_payload
from jobs import job_response, payload_with_stage, save_base64_uploads_for_payload, start_background_job
from storage import TERMINAL_STATUSES, read_status, save_uploaded_pdf_bytes, status_path


FORM_UPLOAD_FIELDS = ("file", "files", "pdf", "pdfs")


router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "full_toc_v4", "framework": "fastapi"}


def parse_config(value: Any) -> dict[str, Any]:
    raw = value or "{}"
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    payload = json.loads(str(raw) or "{}")
    if not isinstance(payload, dict):
        raise ValueError("config must be a JSON object.")
    return payload


def http_error(status_code: int, error: Exception) -> HTTPException:
    return HTTPException(status_code=status_code, detail={
        "ok": False,
        "error": str(error),
        "type": type(error).__name__,
    })


async def uploaded_paths_from_form(form: Any, payload: dict[str, Any]) -> list[Path]:
    args = args_from_payload(payload)
    upload_dir = Path(args.data_dir) / "uploads"
    uploaded_paths: list[Path] = []
    for key in FORM_UPLOAD_FIELDS:
        for item in form.getlist(key):
            filename = getattr(item, "filename", None)
            read = getattr(item, "read", None)
            if not filename or read is None:
                continue
            content = await read()
            uploaded_paths.append(save_uploaded_pdf_bytes(upload_dir, filename, content))
    if not uploaded_paths and not args.input_file:
        raise ValueError("No PDF upload found. Use multipart field 'file' or 'files'.")
    return uploaded_paths


def create_job(payload: dict[str, Any], uploaded_paths: list[Path]) -> JSONResponse:
    job = start_background_job(payload, uploaded_paths)
    return JSONResponse(job_response(job), status_code=202)


def stage_json_endpoint(stage: str):
    async def endpoint(payload: dict[str, Any]) -> JSONResponse:
        try:
            payload_with_forced_stage = payload_with_stage(payload, stage)
            uploaded_paths = save_base64_uploads_for_payload(payload_with_forced_stage)
            return create_job(payload_with_forced_stage, uploaded_paths)
        except Exception as error:
            raise http_error(400, error) from error
    return endpoint


def stage_upload_endpoint(stage: str):
    async def endpoint(request: Request) -> JSONResponse:
        try:
            form = await request.form()
            payload = parse_config(form.get("config"))
            payload_with_forced_stage = payload_with_stage(payload, stage)
            uploaded_paths = await uploaded_paths_from_form(form, payload_with_forced_stage)
            return create_job(payload_with_forced_stage, uploaded_paths)
        except Exception as error:
            raise http_error(400, error) from error
    return endpoint


router.add_api_route("/jobs/layout", stage_json_endpoint("layout"), methods=["POST"])
router.add_api_route("/jobs/gemma", stage_json_endpoint("gemma"), methods=["POST"])
router.add_api_route("/jobs/toc", stage_json_endpoint("all"), methods=["POST"])
router.add_api_route("/jobs/layout/upload", stage_upload_endpoint("layout"), methods=["POST"])
router.add_api_route("/jobs/gemma/upload", stage_upload_endpoint("gemma"), methods=["POST"])
router.add_api_route("/jobs/toc/upload", stage_upload_endpoint("all"), methods=["POST"])


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    try:
        return read_status(job_id)
    except Exception as error:
        raise http_error(404, error) from error


@router.get("/jobs/{job_id}/result")
async def get_job_result(job_id: str) -> JSONResponse:
    try:
        status = read_status(job_id)
        if status.get("status") not in TERMINAL_STATUSES:
            return JSONResponse({
                "job_id": job_id,
                "status": status.get("status"),
                "ready": False,
            }, status_code=202)
        result = status.get("result")
        if not isinstance(result, dict):
            return JSONResponse(status, status_code=500)
        return JSONResponse(result, status_code=200 if result.get("ok") else 500)
    except Exception as error:
        raise http_error(404, error) from error


def job_file_path(job_id: str, status: dict[str, Any], file_type: str) -> Path:
    result = status.get("result") if isinstance(status.get("result"), dict) else {}
    if file_type == "log":
        return Path(result.get("log_file") or "")
    if file_type == "result":
        created = result.get("created_files") if isinstance(result.get("created_files"), list) else []
        return Path(created[-1]) if created else Path("")
    if file_type == "status":
        return status_path(job_id)
    raise ValueError("file_type must be one of: log, result, status")


@router.get("/jobs/{job_id}/files/{file_type}")
async def get_job_file(job_id: str, file_type: str):
    try:
        path = job_file_path(job_id, read_status(job_id), file_type)
        if not path.is_file():
            raise FileNotFoundError(f"File not found for job {job_id}: {file_type}")
        return FileResponse(path)
    except Exception as error:
        raise http_error(404, error) from error


@router.post("/jobs")
async def compatibility_json_job(payload: dict[str, Any]) -> JSONResponse:
    payload = payload_with_stage(payload, str(payload.get("stage") or "all"))
    uploaded_paths = save_base64_uploads_for_payload(payload)
    return create_job(payload, uploaded_paths)


@router.post("/jobs/upload")
async def compatibility_upload_job(request: Request) -> JSONResponse:
    form = await request.form()
    payload = parse_config(form.get("config"))
    payload = payload_with_stage(payload, str(payload.get("stage") or "all"))
    uploaded_paths = await uploaded_paths_from_form(form, payload)
    return create_job(payload, uploaded_paths)


@router.post("/run")
async def compatibility_run(payload: dict[str, Any]) -> JSONResponse:
    return await compatibility_json_job(payload)


@router.post("/toc")
async def compatibility_toc(payload: dict[str, Any]) -> JSONResponse:
    return await compatibility_json_job(payload)


@router.post("/upload")
async def compatibility_upload(request: Request) -> JSONResponse:
    return await compatibility_upload_job(request)
