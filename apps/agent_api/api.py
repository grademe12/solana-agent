"""HTTP surface for health checks and user-created payment authorizations."""

import json
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.agent_api.adk_tools import authorization_store
from packages.schemas import SpendingPolicy

app = FastAPI(title="Agentic Checkout API", version="0.1.0")


class CreateAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: str = Field(min_length=1, max_length=128)
    policy: dict[str, object]


class AuthorizationResponse(BaseModel):
    authorization_id: str
    session_id: str
    policy_id: str
    created_at: datetime


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Report whether the local API process is running."""

    return {"status": "ok"}


@app.post("/api/authorizations", response_model=AuthorizationResponse, status_code=201)
async def create_authorization(request: CreateAuthorizationRequest) -> AuthorizationResponse:
    """Store an explicit user policy outside the model context for later tool use."""

    try:
        policy = SpendingPolicy.model_validate_json(json.dumps(request.policy))
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False),
        ) from exc
    authorization = authorization_store().create(
        session_id=request.session_id,
        policy=policy,
        now=datetime.now(UTC),
    )
    return AuthorizationResponse(
        authorization_id=authorization.authorization_id,
        session_id=authorization.session_id,
        policy_id=authorization.policy.policy_id,
        created_at=authorization.created_at,
    )


@app.delete("/api/authorizations/{authorization_id}", status_code=204)
async def revoke_authorization(authorization_id: str) -> None:
    """Revoke a local authorization so future agent calls cannot use it."""

    authorization_store().revoke(authorization_id)
