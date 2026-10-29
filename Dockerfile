# Single container: FastAPI API + static dashboard. Works on Hugging Face Spaces (port 7860),
# Render/Railway/Fly (they inject $PORT) and plain `docker run -p 7860:7860`.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=7860 SPIKELENS_DB=/data/spikelens.db
RUN useradd -m -u 1000 app && mkdir -p /data && chown app /data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY spikelens ./spikelens
USER app
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health')"
CMD ["sh", "-c", "uvicorn spikelens.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
