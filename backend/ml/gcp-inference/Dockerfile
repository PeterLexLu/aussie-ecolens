FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    MODEL_WORK_DIR=/tmp/aussie-ecolens \
    TORCH_CPU_THREADS=2 \
    GUNICORN_THREADS=2

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --no-deps onnx==1.20.1 onnx2torch==1.5.15 ml_dtypes

COPY service.py .

CMD exec gunicorn --bind :${PORT:-8080} --workers 1 --threads ${GUNICORN_THREADS} --timeout 900 service:app
