# Contents AI API Process

## 기본 구조

```text
/home/hmc2/work/development/eunsoo/Contents_ai_api
├── app.py              # FastAPI 앱 생성
├── routes.py           # API 엔드포인트
├── jobs.py             # job 생성/백그라운드 실행
├── storage.py          # 업로드 파일, job 상태 저장
├── full_toc_core.py    # PDF 파싱, OpenAI layout, Gemma 실행
├── full_toc_v4.py      # 서버 실행 래퍼
├── requirements.txt
└── data/
    ├── input/
    ├── uploads/
    ├── parsed/
    ├── layout/
    ├── full_json/
    ├── log/
    └── jobs/
```

## 1. 서버 실행

```bash
cd /home/hmc2/work/development/eunsoo/Contents_ai_api
pip install -r requirements.txt
```

OpenAI API 키 준비:

```bash
export OPENAI_API_KEY="..."
```

Gemma까지 실행하려면 vLLM 서버를 먼저 실행한다.

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

FastAPI 서버 실행:

```bash
python full_toc_v4.py --host 0.0.0.0 --port 8080
```

서버 확인:

```bash
curl http://127.0.0.1:8080/health
```

## 2. 전체 TOC 생성

PDF 업로드 후 전체 실행:

```bash
curl -X POST http://127.0.0.1:8080/jobs/toc/upload \
  -F 'file=@/path/to/file.pdf' \
  -F 'config={"parse_mode":"headings"}'
```

내부 흐름:

```text
routes.py
→ /jobs/toc/upload 요청 수신
→ stage="all" 설정
→ PDF 업로드 저장: data/uploads/
→ jobs.py에서 job_id 생성
→ data/jobs/JOB_ID/status.json 생성
→ 백그라운드 thread 시작
→ 클라이언트에는 job_id 즉시 반환

백그라운드:
→ full_toc_core.py 실행
→ PDF 파싱
→ data/parsed/에 parsed txt 저장
→ OpenAI API로 layout JSON 생성
→ data/layout/에 layout JSON 저장
→ Gemma/vLLM으로 full TOC JSON 생성
→ data/full_json/에 최종 JSON 저장
→ data/log/에 로그 저장
→ status.json을 completed 또는 failed로 갱신
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

## 3. 상태 조회

```bash
curl http://127.0.0.1:8080/jobs/JOB_ID
```

처리 중:

```json
{
  "job_id": "JOB_ID",
  "status": "running",
  "progress": {
    "stage": "all"
  }
}
```

완료:

```json
{
  "job_id": "JOB_ID",
  "status": "completed",
  "result": {
    "ok": true,
    "stage": "all",
    "log_file": ".../data/log/full_toc_....log",
    "created_files": [
      ".../data/full_json/file_0724_120000_full_foc.json"
    ],
    "failed_files": []
  }
}
```

## 4. 결과 조회

```bash
curl http://127.0.0.1:8080/jobs/JOB_ID/result
```

처리 중이면:

```json
{
  "job_id": "JOB_ID",
  "status": "running",
  "ready": false
}
```

완료되면:

```json
{
  "ok": true,
  "stage": "all",
  "log_file": ".../data/log/full_toc_....log",
  "created_files": [
    ".../data/full_json/file_0724_120000_full_foc.json"
  ],
  "failed_files": []
}
```

## 5. 파일 다운로드

최종 결과 JSON:

```bash
curl -O http://127.0.0.1:8080/jobs/JOB_ID/files/result
```

로그:

```bash
curl -O http://127.0.0.1:8080/jobs/JOB_ID/files/log
```

job 상태 파일:

```bash
curl -O http://127.0.0.1:8080/jobs/JOB_ID/files/status
```

## 6. Layout만 생성

```bash
curl -X POST http://127.0.0.1:8080/jobs/layout/upload \
  -F 'file=@/path/to/file.pdf' \
  -F 'config={"parse_mode":"headings"}'
```

내부 흐름:

```text
PDF 업로드
→ data/uploads/ 저장
→ stage="layout"
→ PDF 파싱
→ data/parsed/ 저장
→ OpenAI API 호출
→ data/layout/파일명_시간_layout.json 저장
→ job completed
```

결과의 `created_files`에 layout JSON 경로가 들어간다.

## 7. Gemma만 실행

먼저 layout JSON이 있어야 한다.

```bash
curl -X POST http://127.0.0.1:8080/jobs/gemma/upload \
  -F 'file=@/path/to/file.pdf' \
  -F 'config={
    "parse_mode":"headings",
    "layout_file":"data/layout/파일명_시간_layout.json",
    "max_output_tokens":32768
  }'
```

내부 흐름:

```text
PDF 업로드
→ data/uploads/ 저장
→ stage="gemma"
→ parsed txt 확인
→ 없으면 PDF 파싱
→ layout_file 로드
→ Gemma/vLLM API 호출
→ data/full_json/파일명_시간_full_foc.json 저장
→ job completed
```

## 8. 서버에 이미 있는 PDF 경로로 실행

PDF를 업로드하지 않고 서버 경로로 실행할 수도 있다.

전체:

```bash
curl -X POST http://127.0.0.1:8080/jobs/toc \
  -H 'Content-Type: application/json' \
  -d '{"input_file":"data/input/file.pdf","parse_mode":"headings"}'
```

layout만:

```bash
curl -X POST http://127.0.0.1:8080/jobs/layout \
  -H 'Content-Type: application/json' \
  -d '{"input_file":"data/input/file.pdf","parse_mode":"headings"}'
```

Gemma만:

```bash
curl -X POST http://127.0.0.1:8080/jobs/gemma \
  -H 'Content-Type: application/json' \
  -d '{
    "input_file":"data/input/file.pdf",
    "parse_mode":"headings",
    "layout_file":"data/layout/파일명_시간_layout.json"
  }'
```

## 9. 저장 위치 요약

```text
data/uploads/       외부 업로드 PDF
data/parsed/        PDF 파싱 txt
data/layout/        OpenAI layout JSON
data/full_json/     Gemma 최종 TOC JSON
data/log/           실행 로그
data/jobs/JOB_ID/   job 상태 파일
```

## 10. 서비스 연동 권장 흐름

전체 자동 생성:

```text
1. 서비스 백엔드가 PDF를 받음
2. /jobs/toc/upload 호출
3. 응답의 job_id를 DB에 저장
4. 프론트가 /jobs/{job_id} polling
5. completed면 /jobs/{job_id}/result 조회
6. created_files 또는 /jobs/{job_id}/files/result로 결과 사용
```

레이아웃 검토 후 생성:

```text
1. /jobs/layout/upload 호출
2. layout JSON 생성
3. 사용자가 layout 검토/수정
4. /jobs/gemma/upload 호출
5. 최종 full TOC JSON 생성
```
