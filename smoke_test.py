from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

import full_toc_core
from app import app


def pdf_bytes(lines: list[tuple[int, int, int, str]]) -> bytes:
    content = ["BT", "/F1 12 Tf"]
    for x, y, size, text in lines:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content.extend([f"/F1 {size} Tf", f"1 0 0 1 {x} {y} Tm", f"({escaped}) Tj"])
    content.append("ET")
    stream = "\n".join(content).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def fake_openai_layout(**kwargs):
    layout = {
        "source_reference": "smoke",
        "source_chunk": "full_pdf",
        "matching_priority": ["examples"],
        "rules": [
            {
                "level": 1,
                "s": 16.0,
                "r": 1.0,
                "b": 0,
                "i": 0,
                "f": "f1",
                "x_min": 60,
                "x_max": 100,
                "y_min": 0,
                "y_max": 800,
                "start_shapes": ["Chapter"],
                "reference_count": 2,
                "examples": ["Chapter 1 Overview", "Chapter 2 Details"],
            }
        ],
        "unmatched_reference_titles": [],
    }
    return {
        "text": json.dumps(layout),
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def fake_gemma(**kwargs):
    toc = {
        "title": "Smoke Test PDF",
        "chapters": [
            {"level": 1, "chapter": "Smoke Test PDF", "page": 1},
            {"level": 1, "chapter": "Chapter 1 Overview", "page": 1},
            {"level": 2, "chapter": "1.1 Goals", "page": 1},
            {"level": 1, "chapter": "Chapter 2 Details", "page": 1},
        ],
    }
    return {
        "text": json.dumps(toc),
        "usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33},
    }


def wait_for_job(client: TestClient, job_id: str) -> dict:
    for _ in range(100):
        response = client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        status = response.json()
        if status["status"] in {"completed", "failed"}:
            return status
        time.sleep(0.05)
    raise AssertionError(f"job did not finish: {job_id}")


def main() -> None:
    full_toc_core.call_openai_layout = fake_openai_layout
    full_toc_core.call_gemma_openai_compatible = fake_gemma

    root = Path(tempfile.mkdtemp(prefix="contents_ai_api_smoke_"))
    data_dir = root / "data"
    pdf_path = root / "smoke.pdf"
    pdf_path.write_bytes(
        pdf_bytes(
            [
                (72, 720, 22, "Smoke Test PDF"),
                (72, 670, 16, "Chapter 1 Overview"),
                (96, 630, 13, "1.1 Goals"),
                (72, 570, 16, "Chapter 2 Details"),
            ]
        )
    )

    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200, health.text
    assert health.json()["ok"] is True
    print("PASS /health")

    missing = client.get("/jobs/does_not_exist")
    assert missing.status_code == 404, missing.text
    print("PASS missing job returns 404")

    invalid = client.post("/jobs/layout/upload", data={"config": "{}"})
    assert invalid.status_code == 400, invalid.text
    print("PASS upload validation returns 400")

    config = {
        "data_dir": str(data_dir),
        "title": "Smoke Test PDF",
        "include_result": True,
        "openai_api_key": "smoke-test-key",
        "openai_model": "smoke-openai",
        "model": "smoke-gemma",
        "ai_retries": 1,
        "openai_retries": 1,
    }
    with pdf_path.open("rb") as file_obj:
        response = client.post(
            "/jobs/toc/upload",
            data={"config": json.dumps(config)},
            files={"file": ("smoke.pdf", file_obj, "application/pdf")},
        )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    print(f"PASS create toc job {job_id}")

    status = wait_for_job(client, job_id)
    assert status["status"] == "completed", json.dumps(status, ensure_ascii=False, indent=2)
    result = status["result"]
    assert result["ok"] is True, result
    assert len(result["created_files"]) == 1, result
    print("PASS job completed")

    result_response = client.get(f"/jobs/{job_id}/result")
    assert result_response.status_code == 200, result_response.text
    result_body = result_response.json()
    assert result_body["ok"] is True
    embedded = result_body.get("result") or json.loads(Path(result_body["created_files"][0]).read_text())
    chapters = embedded.get("chapters", [])
    assert len(chapters) >= 3, embedded
    assert any(item["chapter"] == "Chapter 1 Overview" for item in chapters), embedded
    print("PASS result contains generated TOC")

    file_response = client.get(f"/jobs/{job_id}/files/result")
    assert file_response.status_code == 200, file_response.text
    print("PASS result file download")

    log_response = client.get(f"/jobs/{job_id}/files/log")
    assert log_response.status_code == 200, log_response.text
    print("PASS log file download")

    print(f"SMOKE_TEST_DATA_DIR={data_dir}")


if __name__ == "__main__":
    main()
