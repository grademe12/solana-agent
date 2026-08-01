from io import BytesIO

import zxingcpp  # type: ignore[import-untyped]
from fastapi.testclient import TestClient
from PIL import Image

import apps.agent_api.api as api_module
from apps.agent_api.agent_runtime import AgentRunResult, AgentToolTrace
from apps.agent_api.api import app
from apps.agent_api.settings import SOLANA_DEVNET_USDC_MINT

RECIPIENT = "FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB"
REFERENCE = "SysvarC1ock11111111111111111111111111111111"
PAYLOAD = (
    f"solana:{RECIPIENT}?amount=0.2&spl-token={SOLANA_DEVNET_USDC_MINT}"
    f"&reference={REFERENCE}"
)


def _qr_png(payload: str) -> bytes:
    barcode = zxingcpp.create_barcode(payload, zxingcpp.BarcodeFormat.QRCode)
    qr_image = zxingcpp.write_barcode_to_image(barcode, scale=4)
    height, width = qr_image.shape
    image = Image.frombytes("L", (width, height), bytes(qr_image))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _policy() -> dict[str, object]:
    from datetime import UTC, datetime, timedelta

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


def test_resolve_and_execute_authorized_checkout_api() -> None:
    client = TestClient(app)
    resolved = client.post("/api/intents/resolve", json={"payload": PAYLOAD})

    assert resolved.status_code == 200
    assert resolved.json()["confidence"] == "authoritative"
    assert resolved.json()["amount_display"] == "0.2"

    created = client.post(
        "/api/authorizations",
        json={"session_id": "api-execution-session", "policy": _policy()},
    )
    authorization_id = created.json()["authorization_id"]
    executed = client.post(
        "/api/checkout/execute",
        json={"payload": PAYLOAD, "authorization_id": authorization_id},
    )

    assert executed.status_code == 200
    assert executed.json()["status"] == "confirmed"
    assert executed.json()["mode"] == "mock"
    assert executed.json()["real_funds_moved"] is False


def test_decode_qr_upload_api() -> None:
    response = TestClient(app).post(
        "/api/qr/decode",
        files={"file": ("payment.png", _qr_png(PAYLOAD), "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["raw_payload"] == PAYLOAD
    assert response.json()["payload_hash"].startswith("sha256:")


def test_agent_run_api_returns_tool_trajectory(monkeypatch) -> None:
    class FakeAgentRuntime:
        async def run(self, *, user_id: str, session_id: str, prompt: str) -> AgentRunResult:
            assert user_id == "demo-user"
            assert session_id == "agent-session"
            assert prompt == "결제를 실행해줘"
            return AgentRunResult(
                final_text="완료",
                trajectory=(
                    AgentToolTrace("inspect_payment_request", "requested"),
                    AgentToolTrace("inspect_payment_request", "completed"),
                ),
                checkout_result={"status": "confirmed", "mode": "mock"},
            )

    monkeypatch.setattr(api_module, "agent_runtime", FakeAgentRuntime())
    response = TestClient(app).post(
        "/api/agent/run",
        json={
            "user_id": "demo-user",
            "session_id": "agent-session",
            "prompt": "결제를 실행해줘",
        },
    )

    assert response.status_code == 200
    assert response.json()["final_text"] == "완료"
    assert response.json()["trajectory"][0] == {
        "tool_name": "inspect_payment_request",
        "phase": "requested",
    }
