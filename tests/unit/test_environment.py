from fastapi.testclient import TestClient

from apps.agent_api.api import app


def _policy() -> dict[str, object]:
    from datetime import UTC, datetime, timedelta

    from apps.agent_api.settings import SOLANA_DEVNET_USDC_MINT

    return {
        "policy_id": "api-policy",
        "user_id": "api-user",
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
        "max_slippage_bps": 50,
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }


def test_healthz() -> None:
    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_revoke_payment_authorization() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/authorizations",
        json={"session_id": "api-session", "policy": _policy()},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == "api-session"
    assert body["policy_id"] == "api-policy"
    assert body["authorization_id"]

    revoked = client.delete(f"/api/authorizations/{body['authorization_id']}")
    assert revoked.status_code == 204
