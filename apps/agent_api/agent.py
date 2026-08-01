"""Google ADK definition for the read-only payment analysis agent."""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.apps import App

from apps.agent_api.adk_tools import (
    execute_authorized_checkout,
    get_agent_wallet_balances,
    inspect_authorized_payment,
    inspect_payment_request,
    preview_payment_policy,
)

APP_NAME = "agent_api"
AGENT_NAME = "agentic_checkout"
DEFAULT_MODEL = "gemini-2.5-flash"

PAYMENT_AGENT_INSTRUCTION = """
You are a policy-guarded Solana payment agent.

For every payment payload:
1. Call inspect_payment_request before stating its protocol, network, asset, amount,
   recipient, reference, or executability.
2. If a policy is provided, call preview_payment_policy only for an advisory preview.
3. Clearly distinguish authoritative, incomplete, unsupported, and invalid intents.
4. Never infer a missing amount, token mint, network, recipient, or reference.
5. Never treat a QR label or message as verified merchant identity.
6. Every checkout, including a server-configured mock checkout, requires an authorization ID.
7. For an authorized checkout, call inspect_authorized_payment with the authorization ID.
   Never reconstruct, copy, or pass a payment payload to the execution tool.
8. Call execute_authorized_checkout only when the user explicitly requests payment and
   provides an authorization ID created outside the model by the application.
9. Before execute_authorized_checkout, call get_agent_wallet_balances and do not execute
    if the tool reports insufficient SOL or USDC for the authorized payment amount.
10. Never invent or alter an authorization ID, policy, merchant identity, fee, wallet,
    network, recipient, token mint, amount, or reference.
11. Report a real payment as confirmed only when the tool returns mode=devnet,
    status=confirmed, and a non-null Explorer URL.

The guarded executor reloads server-stored policy, usage, merchant identity, fee, and
wallet configuration. A mock signature is not valid on Solana and has no Explorer URL.
Respond in the user's language and keep transaction identifiers exact.
""".strip()

root_agent = Agent(
    name=AGENT_NAME,
    description="Inspects and executes server-authorized Solana payment requests.",
    model=os.getenv("GEMINI_MODEL") or DEFAULT_MODEL,
    instruction=PAYMENT_AGENT_INSTRUCTION,
    tools=[
        inspect_payment_request,
        inspect_authorized_payment,
        preview_payment_policy,
        get_agent_wallet_balances,
        execute_authorized_checkout,
    ],
)

app = App(name=APP_NAME, root_agent=root_agent)
adk_app = app
