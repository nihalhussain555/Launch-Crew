# Official Playwright image: ships Chromium + all system libs.
# Tag MUST match the playwright version pinned in requirements.txt.
# (The image's system Python is 3.12; the code is compatible with 3.10-3.12.)
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages --ignore-installed -r requirements.txt

COPY app ./app
RUN mkdir -p /data/artifacts

# Render injects $PORT; default 8000 for local docker.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
