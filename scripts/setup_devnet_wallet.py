"""Create/load the ignored demo wallet and verify its Solana Devnet environment."""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal, InvalidOperation

from apps.agent_api.services.devnet_rpc import (
    LAMPORTS_PER_SOL,
    DevnetFundingUnavailable,
    DevnetRpcService,
)
from apps.agent_api.services.keypairs import create_or_load_keypair_file
from apps.agent_api.settings import SolanaSettings


def _sol_to_lamports(value: str) -> int:
    try:
        sol = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("SOL amount must be a decimal number") from exc
    lamports = sol * LAMPORTS_PER_SOL
    if sol < 0 or lamports != lamports.to_integral_value():
        raise argparse.ArgumentTypeError("SOL amount must be non-negative with at most 9 decimals")
    return int(lamports)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--minimum-sol",
        default=0,
        type=_sol_to_lamports,
        help="Request Devnet SOL only when the wallet is below this minimum (default: 0)",
    )
    return parser.parse_args()


async def run(minimum_lamports: int) -> None:
    settings = SolanaSettings()
    keypair_result = create_or_load_keypair_file(settings.resolved_keypair_path())
    public_key = keypair_result.keypair.pubkey()

    print(f"Wallet public key: {public_key}")
    print(f"Keypair file: {keypair_result.path}")
    print(f"Created: {str(keypair_result.created).lower()}")

    rpc = DevnetRpcService(settings)
    snapshot = await rpc.probe(public_key)
    print(f"RPC endpoint: {snapshot.endpoint}")
    print(f"Genesis hash: {snapshot.genesis_hash}")
    print(f"Confirmed slot: {snapshot.slot}")
    print(f"SOL balance lamports: {snapshot.wallet_balance_lamports}")
    print(f"USDC mint: {snapshot.usdc_mint}")
    print(f"USDC decimals: {snapshot.usdc_decimals}")

    if minimum_lamports > 0:
        funded = await rpc.fund_to_minimum_sol(public_key, minimum_lamports)
        print(f"Airdrop requested lamports: {funded.requested_lamports}")
        print(f"Airdrop signature: {funded.signature or 'not-needed'}")
        print(f"Final SOL balance lamports: {funded.final_balance_lamports}")


def main() -> int:
    args = parse_args()
    try:
        asyncio.run(run(args.minimum_sol))
    except DevnetFundingUnavailable as exc:
        print(f"ERROR: {exc}")
        print("Solana faucet: https://faucet.solana.com")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
