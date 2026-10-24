FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data

WORKDIR /app

COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY app ./app
COPY templates ./templates
COPY static ./static

# Train the model at build time so every replica starts with the same model file.
RUN python app/train.py

# Run as a non-root user; /app/data is the (volume-mounted) upload + database folder.
RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health', timeout=3)" || exit 1

CMD ["gunicorn", "--chdir", "app", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "2", "app:app"]
