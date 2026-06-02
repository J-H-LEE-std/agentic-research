FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 (curl: 헬스체크용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . .

# 출력 디렉토리 생성
RUN mkdir -p /data/outputs/logs /data/outputs/graphs /data/outputs/papers

ENV PYTHONPATH=/app
ENV EXECUTOR_OUTPUT_PATH=/data/outputs
ENV PROGRESS_PATH=/data/progress.md
ENV TOKEN_LOG_PATH=/data/outputs/logs/token_usage.jsonl

# ENTRYPOINT 제거 → docker-compose CMD로 override 가능
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
