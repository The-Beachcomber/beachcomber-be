FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY docs/ ./docs/
COPY openapi.yaml .

# Cloud Run 以 $PORT 注入監聽埠；單一 worker，狀態一律走 GCS 不放記憶體。
ENV PORT=8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
