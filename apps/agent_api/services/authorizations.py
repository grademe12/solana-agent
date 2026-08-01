"""In-memory user authorizations kept outside the LLM tool-call boundary."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from packages.schemas import SpendingPolicy


@dataclass(frozen=True, slots=True)
class PaymentAuthorization:
    authorization_id: str
    session_id: str
    policy: SpendingPolicy
    payment_payload: str
    intent_id: str
    source_payload_hash: str
    created_at: datetime


class InMemoryAuthorizationStore:
    """Local P0 adapter; a deployed version must use authenticated durable storage."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._authorizations: dict[str, PaymentAuthorization] = {}

    def create(
        self,
        *,
        session_id: str,
        policy: SpendingPolicy,
        payment_payload: str,
        intent_id: str,
        source_payload_hash: str,
        now: datetime,
    ) -> PaymentAuthorization:
        if not session_id:
            raise ValueError("session_id is required")
        if not payment_payload:
            raise ValueError("payment_payload is required")
        expected_payload_hash = "sha256:" + hashlib.sha256(
            payment_payload.encode("utf-8")
        ).hexdigest()
        if source_payload_hash != expected_payload_hash:
            raise ValueError("source_payload_hash does not match payment_payload")
        if not intent_id.startswith("sha256:"):
            raise ValueError("intent_id must be a sha256 identifier")
        if now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        authorization = PaymentAuthorization(
            authorization_id=secrets.token_urlsafe(24),
            session_id=session_id,
            policy=policy,
            payment_payload=payment_payload,
            intent_id=intent_id,
            source_payload_hash=source_payload_hash,
            created_at=now,
        )
        with self._lock:
            self._authorizations[authorization.authorization_id] = authorization
        return authorization

    def get(self, authorization_id: str) -> PaymentAuthorization | None:
        with self._lock:
            return self._authorizations.get(authorization_id)

    def revoke(self, authorization_id: str) -> bool:
        with self._lock:
            return self._authorizations.pop(authorization_id, None) is not None
