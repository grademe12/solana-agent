"""HTTP surface for health checks and user-created payment authorizations."""

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.agent_api.adk_tools import (
    authorization_store,
    execute_authorized_checkout,
)
from apps.agent_api.tools.decode_qr import MAX_IMAGE_BYTES, QrDecodeError, decode_payment_qr
from apps.agent_api.tools.resolve_intent import resolve_payment_intent
from packages.schemas import SpendingPolicy

app = FastAPI(title="Agentic Checkout API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


class CreateAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: str = Field(min_length=1, max_length=128)
    policy: dict[str, object]


class AuthorizationResponse(BaseModel):
    authorization_id: str
    session_id: str
    policy_id: str
    created_at: datetime


class PaymentPayloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    payload: str = Field(min_length=1, max_length=4096)


class ExecuteCheckoutRequest(PaymentPayloadRequest):
    authorization_id: str = Field(min_length=1, max_length=256)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Report whether the local API process is running."""

    return {"status": "ok"}


@app.post("/api/qr/decode")
async def decode_qr(file: Annotated[UploadFile, File()]) -> dict[str, object]:
    """Decode one uploaded QR image without following or executing its payload."""

    image_bytes = await file.read(MAX_IMAGE_BYTES + 1)
    try:
        decoded = decode_payment_qr(image_bytes)
    except QrDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return decoded.model_dump(mode="json")


@app.post("/api/intents/resolve")
async def resolve_intent(request: PaymentPayloadRequest) -> dict[str, object]:
    """Normalize untrusted QR text into an inspectable payment intent."""

    intent = resolve_payment_intent(request.payload)
    response = intent.model_dump(mode="json")
    response["amount_display"] = intent.amount_display
    return response


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


@app.post("/api/checkout/execute")
async def execute_checkout(request: ExecuteCheckoutRequest) -> dict[str, object]:
    """Invoke the same guarded execution capability exposed to the ADK agent."""

    return await execute_authorized_checkout(request.payload, request.authorization_id)
