import json
from datetime import UTC, datetime, timedelta

import pytest
from google.adk.agents import Agent
from google.adk.apps import App

from apps.agent_api.adk_tools import (
    authorization_store,
    execute_authorized_checkout,
    execute_mock_guarded_checkout,
    get_agent_wallet_balances,
    inspect_payment_request,
    preview_payment_policy,
)
from apps.agent_api.agent import (
    AGENT_NAME,
    APP_NAME,
    PAYMENT_AGENT_INSTRUCTION,
    adk_app,
    root_agent,
)
from apps.agent_api.tools.resolve_intent import SOLANA_DEVNET_USDC_MINT
from packages.schemas import SpendingPolicy

RECIPIENT = "FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB"
REFERENCE = "11111111111111111111111111111111"
PAYLOAD = (
    f"solana:{RECIPIENT}?amount=0.5&spl-token={SOLANA_DEVNET_USDC_MINT}"
    f"&reference={REFERENCE}"
)


def make_policy_json() -> str:
    return json.dumps(
        {
            "policy_id": "demo-policy",
            "user_id": "demo-user",
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
    )


def test_adk_app_exposes_guarded_payment_agent() -> None:
    assert isinstance(root_agent, Agent)
    assert isinstance(adk_app, App)
    assert root_agent.name == AGENT_NAME
    assert adk_app.name == APP_NAME
    assert adk_app.root_agent is root_agent

    tool_names = {tool.__name__ for tool in root_agent.tools}
    assert tool_names == {
        "inspect_payment_request",
        "preview_payment_policy",
        "execute_mock_guarded_checkout",
        "execute_authorized_checkout",
        "get_agent_wallet_balances",
    }


def test_agent_instruction_restricts_payment_completion_claims() -> None:
    assert "Never infer a missing amount" in PAYMENT_AGENT_INSTRUCTION
    assert "provides an authorization ID" in PAYMENT_AGENT_INSTRUCTION
    assert "Never invent or alter an authorization ID" in PAYMENT_AGENT_INSTRUCTION
    assert "status=confirmed" in PAYMENT_AGENT_INSTRUCTION
    assert "mock signature is not valid on Solana" in PAYMENT_AGENT_INSTRUCTION


def test_inspection_tool_returns_serializable_authoritative_intent() -> None:
    result = inspect_payment_request(PAYLOAD)

    assert result["read_only"] is True
    assert result["intent"]["confidence"] == "authoritative"
    assert result["intent"]["amount"]["atomic"] == "500000"
    json.dumps(result)


def test_policy_preview_is_explicitly_advisory() -> None:
    result = preview_payment_policy(
        PAYLOAD,
        make_policy_json(),
        verified_merchant_id="demo-merchant",
        network_fee_lamports=5_000,
    )

    assert result["status"] == "allowed"
    assert result["read_only"] is True
    assert result["advisory_only"] is True
    assert result["assumptions"]["daily_spent_atomic"] == 0


def test_policy_preview_returns_structured_validation_error() -> None:
    result = preview_payment_policy(PAYLOAD, "{}")

    assert result["status"] == "invalid_policy"
    assert result["advisory_only"] is True
    assert result["errors"]


def test_adk_mock_checkout_tool_never_claims_real_payment() -> None:
    result = execute_mock_guarded_checkout(
        PAYLOAD,
        make_policy_json(),
        session_id="adk-mock-test-session",
        demo_merchant_id="demo-merchant",
    )

    assert result["status"] == "confirmed"
    assert result["mode"] == "mock"
    assert result["real_funds_moved"] is False
    assert result["receipt"]["mock"] is True
    assert result["receipt"]["explorer_url"] is None
    assert result["receipt"]["signature"].startswith("mock:")


@pytest.mark.asyncio
async def test_authorized_tool_uses_server_stored_policy_in_mock_mode() -> None:
    policy = SpendingPolicy.model_validate_json(make_policy_json())
    authorization = authorization_store().create(
        session_id="authorized-tool-session",
        policy=policy,
        now=datetime.now(UTC),
    )

    result = await execute_authorized_checkout(PAYLOAD, authorization.authorization_id)

    assert result["status"] == "confirmed"
    assert result["mode"] == "mock"
    assert result["real_funds_moved"] is False
    assert result["receipt"]["mock"] is True


@pytest.mark.asyncio
async def test_authorized_tool_rejects_unknown_authorization() -> None:
    result = await execute_authorized_checkout(PAYLOAD, "unknown")

    assert result == {"status": "authorization_not_found", "submitted": False}


@pytest.mark.asyncio
async def test_wallet_balance_tool_is_read_only_and_mock_by_default() -> None:
    result = await get_agent_wallet_balances()

    assert result["status"] == "ok"
    assert result["mode"] == "mock"
    assert result["read_only"] is True
    assert result["usdc_atomic"]
    assert result["sol_lamports"] > 0
