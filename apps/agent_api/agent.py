"""Google ADK definition for the read-only payment analysis agent."""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.apps import App

from apps.agent_api.adk_tools import inspect_payment_request, preview_payment_policy

APP_NAME = "agent_api"
AGENT_NAME = "agentic_checkout"
DEFAULT_MODEL = "gemini-2.5-flash"

PAYMENT_AGENT_INSTRUCTION = """
You are the read-only analysis stage of a policy-guarded Solana payment system.

For every payment payload:
1. Call inspect_payment_request before stating its protocol, network, asset, amount,
   recipient, reference, or executability.
2. If a policy is provided, call preview_payment_policy only for an advisory preview.
3. Clearly distinguish authoritative, incomplete, unsupported, and invalid intents.
4. Never infer a missing amount, token mint, network, recipient, or reference.
5. Never treat a QR label or message as verified merchant identity.
6. Never claim that a payment was authorized, signed, submitted, confirmed, or completed.

You have no signing or payment execution tool. Explain that final authorization requires
the guarded executor to reload trusted policy, usage, merchant identity, fee, and balance.
Respond in the user's language and keep transaction identifiers exact.
""".strip()

root_agent = Agent(
    name=AGENT_NAME,
    description="Inspects payment QR payloads and previews Solana spending policies.",
    model=os.getenv("GEMINI_MODEL") or DEFAULT_MODEL,
    instruction=PAYMENT_AGENT_INSTRUCTION,
    tools=[inspect_payment_request, preview_payment_policy],
)

app = App(name=APP_NAME, root_agent=root_agent)
adk_app = app
