from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from full_toc_core import DEFAULT_DATA_DIR, clean_text, safe_filename_part, timestamp_for_filename


TERMINAL_STATUSES = {"completed", "failed"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_job_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def default_jobs_dir() -> Path:
    return DEFAULT_DATA_DIR / "jobs"


def safe_job_id(job_id: str) -> str:
    value = str(job_id or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    if not value or any(ch not in allowed for ch in value):
        raise ValueError(f"Invalid job_id: {job_id}")
    return value


def job_dir(job_id: str) -> Path:
    return default_jobs_dir() / safe_job_id(job_id)


def status_path(job_id: str) -> Path:
    return job_dir(job_id) / "status.json"


def write_status(job_id: str, data: dict[str, Any]) -> None:
    path = status_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["updated_at"] = now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_status(job_id: str) -> dict[str, Any]:
    path = status_path(job_id)
    if not path.is_file():
        raise FileNotFoundError(f"Job not found: {job_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    hidden = {"openai_api_key", "api_key", "file_base64", "files"}
    result: dict[str, Any] = {}
    for key, value in payload.items():
        normalized = key.replace("-", "_")
        result[key] = "<hidden>" if normalized in hidden else value
    return result


def save_uploaded_pdf_bytes(upload_dir: Path, filename: str, content: bytes) -> Path:
    name = Path(clean_text(filename) or "uploaded.pdf").name
    if not name.lower().endswith(".pdf"):
        raise ValueError(f"Uploaded file is not a PDF: {name}")
    if not content:
        raise ValueError(f"Uploaded file is empty: {name}")
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{timestamp_for_filename()}_{safe_filename_part(Path(name).stem)}.pdf"
    path.write_bytes(content)
    return path
