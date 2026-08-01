"""Schemas for deterministic payment authorization policies."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SpendingPolicy(BaseModel):
    """Immutable policy data consumed by the future policy engine."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    allowed_networks: frozenset[str]
    allowed_asset_mints: frozenset[str]
    allowed_merchants: frozenset[str]
    budget_asset_mint: str = Field(min_length=1)
    budget_decimals: int = Field(ge=0, le=18)
    max_per_transaction_atomic: int = Field(gt=0)
    max_daily_atomic: int = Field(gt=0)
    max_transactions_per_day: int = Field(gt=0)
    max_network_fee_lamports: int = Field(ge=0)
    max_slippage_bps: int = Field(ge=0, le=10_000)
    expires_at: datetime

    @field_validator("allowed_networks", "allowed_asset_mints", "allowed_merchants", mode="before")
    @classmethod
    def freeze_allowlist(cls, value: Any) -> frozenset[str]:
        if isinstance(value, str):
            raise ValueError("allowlists must be collections, not strings")
        if not isinstance(value, (set, frozenset, list, tuple)):
            raise ValueError("allowlists must be collections")
        return frozenset(value)

    @model_validator(mode="after")
    def validate_limits(self) -> SpendingPolicy:
        if self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        if self.max_daily_atomic < self.max_per_transaction_atomic:
            raise ValueError("daily limit cannot be lower than per-transaction limit")

        if self.enabled:
            empty_allowlists = [
                name
                for name, value in (
                    ("allowed_networks", self.allowed_networks),
                    ("allowed_asset_mints", self.allowed_asset_mints),
                    ("allowed_merchants", self.allowed_merchants),
                )
                if not value
            ]
            if empty_allowlists:
                raise ValueError(
                    "enabled policy has empty allowlists: " + ", ".join(empty_allowlists)
                )

        if self.budget_asset_mint not in self.allowed_asset_mints:
            raise ValueError("budget asset mint must be explicitly allowed")

        return self
