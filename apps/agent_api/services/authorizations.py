"""In-memory user authorizations kept outside the LLM tool-call boundary."""

from __future__ import annotations

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
        now: datetime,
    ) -> PaymentAuthorization:
        if not session_id:
            raise ValueError("session_id is required")
        if now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        authorization = PaymentAuthorization(
            authorization_id=secrets.token_urlsafe(24),
            session_id=session_id,
            policy=policy,
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
