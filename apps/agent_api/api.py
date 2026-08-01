"""Minimal API surface used to verify the local development environment."""

from fastapi import FastAPI

app = FastAPI(title="Agentic Checkout API", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Report whether the local API process is running."""

    return {"status": "ok"}
