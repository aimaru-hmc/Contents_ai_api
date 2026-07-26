# Contents AI API

PDF 파일을 업로드하거나 서버 경로로 지정해 목차 추출용 layout JSON과 최종 full TOC JSON을 생성하는 FastAPI 서버입니다.

처리는 비동기 job 방식으로 동작합니다. 요청을 보내면 즉시 `job_id`를 반환하고, 클라이언트는 상태 조회 API로 진행 상태와 결과를 확인합니다.

## 구성

```text
Contents_ai_api/
├── app.py              # FastAPI 앱 생성
├── routes.py           # API 엔드포인트
├── jobs.py             # job 생성 및 백그라운드 실행
├── storage.py          # 업로드 파일과 job 상태 저장
├── full_toc_core.py    # PDF 파싱, OpenAI layout, Gemma 실행
├── full_toc_v4.py      # 서버 실행 래퍼
├── requirements.txt
└── PROCESS.md          # 상세 실행 프로세스 문서
```

## 설치

```bash
cd /home/hmc2/work/development/eunsoo/Contents_ai_api
pip install -r requirements.txt
```

OpenAI layout 생성을 위해 API 키가 필요합니다.

```bash
export OPENAI_API_KEY="..."
```

## Gemma/vLLM 서버

Gemma 단계 또는 전체 TOC 생성을 실행하려면 vLLM OpenAI-compatible 서버가 먼저 떠 있어야 합니다.

```bash
CUDA_VISIBLE_DEVICES=4,5,6,7 VLLM_USE_FLASHINFER_SAMPLER=0 \
python -m vllm.entrypoints.openai.api_server \
  --model google/gemma-4-31B-it \
  --served-model-name google/gemma-4-31B-it \
  --host 127.0.0.1 \
  --port 8000 \
  --tensor-parallel-size 4 \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.9 \
  --trust-remote-code
```

## API 서버 실행

```bash
python full_toc_v4.py --host 0.0.0.0 --port 8080
```

또는:

```bash
uvicorn app:app --host 0.0.0.0 --port 8080
```

상태 확인:

```bash
curl http://127.0.0.1:8080/health
```

브라우저 문서:

```text
http://127.0.0.1:8080/docs
```

## 주요 API

```text
POST /jobs/layout/upload   # PDF 업로드 후 layout JSON만 생성
POST /jobs/gemma/upload    # PDF 업로드 후 기존 layout JSON으로 Gemma만 실행
POST /jobs/toc/upload      # PDF 업로드 후 layout + Gemma 전체 실행

POST /jobs/layout          # 서버 경로 또는 base64 입력으로 layout만 생성
POST /jobs/gemma           # 서버 경로 또는 base64 입력으로 Gemma만 실행
POST /jobs/toc             # 서버 경로 또는 base64 입력으로 전체 실행

GET  /jobs/{job_id}        # job 상태 조회
GET  /jobs/{job_id}/result # job 결과 조회
GET  /jobs/{job_id}/files/result # 결과 파일 다운로드
GET  /jobs/{job_id}/files/log    # 로그 파일 다운로드
```

## 전체 실행 예시

```bash
curl -X POST http://127.0.0.1:8080/jobs/toc/upload \
  -F 'file=@/path/to/file.pdf' \
  -F 'config={"parse_mode":"headings"}'
```

응답 예:

```json
{
  "job_id": "20260724_120000_ab12cd34",
  "status": "queued",
  "stage": "all",
  "status_url": "/jobs/20260724_120000_ab12cd34",
  "result_url": "/jobs/20260724_120000_ab12cd34/result"
}
```

상태 조회:

```bash
curl http://127.0.0.1:8080/jobs/JOB_ID
```

결과 조회:

```bash
curl http://127.0.0.1:8080/jobs/JOB_ID/result
```

결과 파일 다운로드:

```bash
curl -O http://127.0.0.1:8080/jobs/JOB_ID/files/result
```

## Layout만 생성

```bash
curl -X POST http://127.0.0.1:8080/jobs/layout/upload \
  -F 'file=@/path/to/file.pdf' \
  -F 'config={"parse_mode":"headings"}'
```

생성된 layout JSON 경로는 job 결과의 `created_files`에 들어갑니다.

## Gemma만 실행

```bash
curl -X POST http://127.0.0.1:8080/jobs/gemma/upload \
  -F 'file=@/path/to/file.pdf' \
  -F 'config={
    "parse_mode":"headings",
    "layout_file":"data/layout/파일명_시간_layout.json",
    "max_output_tokens":32768
  }'
```

## 저장 위치

기본 산출물은 `data/` 아래에 저장됩니다.

```text
data/uploads/       업로드 PDF
data/parsed/        PDF 파싱 txt
data/layout/        OpenAI layout JSON
data/full_json/     Gemma 최종 TOC JSON
data/log/           실행 로그
data/jobs/          job 상태 파일
```

## 상세 문서

자세한 처리 흐름과 서비스 연동 프로세스는 [PROCESS.md](PROCESS.md)를 참고하세요.
