FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

COPY requirements.runtime.lock pyproject.toml README.md ./
COPY apps ./apps
COPY packages ./packages

RUN python -m pip install --no-cache-dir -r requirements.runtime.lock \
    && python -m pip install --no-cache-dir --no-deps .

EXPOSE 8080

CMD ["sh", "-c", "exec python -m uvicorn apps.agent_api.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
