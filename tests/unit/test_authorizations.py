import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from apps.agent_api.services.authorizations import InMemoryAuthorizationStore
from apps.agent_api.tools.resolve_intent import SOLANA_DEVNET_USDC_MINT
from packages.schemas import SpendingPolicy

RECIPIENT = "FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB"
REFERENCE = "SysvarC1ock11111111111111111111111111111111"
PAYLOAD = (
    f"solana:{RECIPIENT}?amount=0.2&spl-token={SOLANA_DEVNET_USDC_MINT}"
    f"&reference={REFERENCE}"
)
PAYLOAD_HASH = "sha256:" + hashlib.sha256(PAYLOAD.encode("utf-8")).hexdigest()


def _policy() -> SpendingPolicy:
    return SpendingPolicy.model_validate(
        {
            "policy_id": "authorization-policy",
            "user_id": "authorization-user",
            "enabled": True,
            "allowed_networks": ["solana:devnet"],
            "allowed_asset_mints": [SOLANA_DEVNET_USDC_MINT],
            "allowed_merchants": ["demo-merchant"],
            "budget_asset_mint": SOLANA_DEVNET_USDC_MINT,
            "budget_decimals": 6,
            "max_per_transaction_atomic": 1_000_000,
            "max_daily_atomic": 5_000_000,
            "max_transactions_per_day": 10,
            "max_network_fee_lamports": 100_000,
            "max_slippage_bps": 0,
            "expires_at": datetime.now(UTC) + timedelta(days=1),
        }
    )


def test_authorization_binds_exact_payment_payload_and_hash() -> None:
    authorization = InMemoryAuthorizationStore().create(
        session_id="binding-session",
        policy=_policy(),
        payment_payload=PAYLOAD,
        intent_id=PAYLOAD_HASH,
        source_payload_hash=PAYLOAD_HASH,
        now=datetime.now(UTC),
    )

    assert authorization.payment_payload == PAYLOAD
    assert authorization.intent_id == PAYLOAD_HASH
    assert authorization.source_payload_hash == PAYLOAD_HASH


def test_authorization_rejects_payload_hash_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        InMemoryAuthorizationStore().create(
            session_id="binding-session",
            policy=_policy(),
            payment_payload=PAYLOAD,
            intent_id=PAYLOAD_HASH,
            source_payload_hash="sha256:" + "0" * 64,
            now=datetime.now(UTC),
        )
