from __future__ import annotations

import json
import threading
import traceback
from pathlib import Path
from typing import Any

from full_toc_core import args_from_payload, attach_uploaded_paths, run_pipeline_locked, save_json_base64_uploads
from storage import make_job_id, now_iso, read_status, summarize_payload, write_status


def include_result_if_requested(result: dict[str, Any], include_result: bool) -> dict[str, Any]:
    if include_result and result.get("created_files"):
        result_path = Path(result["created_files"][-1])
        if result_path.is_file():
            result["result"] = json.loads(result_path.read_text(encoding="utf-8"))
    return result


def payload_with_stage(payload: dict[str, Any], stage: str) -> dict[str, Any]:
    result = dict(payload)
    result["stage"] = stage
    return result


def save_base64_uploads_for_payload(payload: dict[str, Any]) -> list[Path]:
    args = args_from_payload(payload)
    upload_dir = Path(args.data_dir) / "uploads"
    return save_json_base64_uploads(payload, upload_dir)


def run_job(job_id: str, payload: dict[str, Any], uploaded_paths: list[Path]) -> None:
    status = read_status(job_id)
    try:
        write_status(job_id, {
            **status,
            "status": "running",
            "started_at": now_iso(),
            "progress": {"stage": payload.get("stage", "all")},
        })
        include_result = bool(payload.get("include_result", False))
        args = args_from_payload(payload)
        args = attach_uploaded_paths(args, uploaded_paths)
        result = include_result_if_requested(run_pipeline_locked(args), include_result)
        final_status = "completed" if result.get("ok") else "failed"
        write_status(job_id, {
            **read_status(job_id),
            "status": final_status,
            "finished_at": now_iso(),
            "progress": {"stage": final_status},
            "result": result,
        })
    except Exception as error:
        write_status(job_id, {
            **read_status(job_id),
            "status": "failed",
            "finished_at": now_iso(),
            "progress": {"stage": "failed"},
            "error": str(error),
            "error_type": type(error).__name__,
            "traceback": traceback.format_exc(),
        })


def start_background_job(payload: dict[str, Any], uploaded_paths: list[Path]) -> dict[str, Any]:
    job_id = make_job_id()
    write_status(job_id, {
        "job_id": job_id,
        "status": "queued",
        "created_at": now_iso(),
        "request": summarize_payload(payload),
        "uploaded_files": [str(path) for path in uploaded_paths],
        "progress": {"stage": payload.get("stage", "all")},
    })
    thread = threading.Thread(target=run_job, args=(job_id, dict(payload), list(uploaded_paths)), daemon=True)
    thread.start()
    return read_status(job_id)


def job_response(job: dict[str, Any]) -> dict[str, Any]:
    job_id = job["job_id"]
    return {
        "job_id": job_id,
        "status": job["status"],
        "stage": job.get("request", {}).get("stage"),
        "status_url": f"/jobs/{job_id}",
        "result_url": f"/jobs/{job_id}/result",
    }
