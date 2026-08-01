"""Prepare and simulate an official Devnet USDC payment without submitting it."""

from __future__ import annotations

import argparse
import asyncio
from urllib.parse import urlencode

from apps.agent_api.services.solana_transfer import DevnetUsdcTransferService
from apps.agent_api.settings import SOLANA_DEVNET_USDC_MINT, SolanaSettings
from apps.agent_api.tools.resolve_intent import resolve_payment_intent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--amount", required=True, help="USDC decimal amount, for example 0.10")
    return parser.parse_args()


async def run(recipient: str, reference: str, amount: str) -> int:
    query = urlencode(
        {
            "amount": amount,
            "spl-token": SOLANA_DEVNET_USDC_MINT,
            "reference": reference,
            "label": "Agentic Checkout Devnet Diagnostic",
        }
    )
    intent = resolve_payment_intent(f"solana:{recipient}?{query}")
    if not intent.is_executable:
        print(f"ERROR: {intent.rejection_code}: {intent.rejection_reason}")
        return 2

    prepared = await DevnetUsdcTransferService(SolanaSettings()).prepare_and_simulate(intent)
    print(f"Intent ID: {prepared.plan.intent_id}")
    print(f"Payer: {prepared.plan.payer}")
    print(f"Recipient: {prepared.plan.recipient}")
    print(f"Mint: {prepared.plan.mint}")
    print(f"Amount atomic: {prepared.plan.amount_atomic}")
    print(f"Reference: {prepared.plan.reference}")
    print(f"Estimated fee lamports: {prepared.estimated_fee_lamports}")
    print(f"Signed transaction signature: {prepared.transaction.signatures[0]}")
    print(f"Simulation succeeded: {str(prepared.simulation_succeeded).lower()}")
    print(f"Simulation error: {prepared.simulation_error or 'none'}")
    print("Submitted: false")
    return 0 if prepared.simulation_succeeded else 3


def main() -> int:
    args = parse_args()
    return asyncio.run(run(args.recipient, args.reference, args.amount))


if __name__ == "__main__":
    raise SystemExit(main())

