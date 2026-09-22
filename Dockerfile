FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY . .

RUN pip install --upgrade pip && pip install -e .

EXPOSE 8080 8501

CMD ["python", "src/run_service.py"]
