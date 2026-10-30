FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" OMP_THREAD_LIMIT=2
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng ca-certificates fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
WORKDIR /service
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app/ocr_models.py /tmp/ocr_models.py
RUN python /tmp/ocr_models.py /opt/ocr-models && rm /tmp/ocr_models.py
COPY licenses /opt/ocr-models/licenses
RUN apt-get update && apt-get install -y --no-install-recommends fonts-liberation2 && rm -rf /var/lib/apt/lists/*
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
# Git does not track read permissions; protected host files may arrive as 0600.
# Keep image code owned by root and readable by the unprivileged service user.
RUN find app alembic -type d -exec chmod 0755 {} + \
    && find app alembic -type f -exec chmod 0644 {} + \
    && chmod 0644 alembic.ini
RUN useradd --uid 10001 --create-home service && mkdir /data && chown service:service /data
USER service
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
