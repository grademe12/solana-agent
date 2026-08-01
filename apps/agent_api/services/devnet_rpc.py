"""Solana Devnet RPC probing and test-SOL funding helpers."""

from __future__ import annotations

from dataclasses import dataclass

from solana.exceptions import SolanaRpcException
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solders.pubkey import Pubkey

from apps.agent_api.settings import SolanaSettings

DEVNET_GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
LAMPORTS_PER_SOL = 1_000_000_000


class WrongSolanaCluster(RuntimeError):
    """Raised before mutation when an RPC endpoint is not Solana Devnet."""


class DevnetFundingUnavailable(RuntimeError):
    """Raised when a public Devnet RPC refuses or rate-limits an airdrop."""


@dataclass(frozen=True, slots=True)
class DevnetRpcSnapshot:
    endpoint: str
    genesis_hash: str
    slot: int
    wallet_balance_lamports: int
    usdc_mint: str
    usdc_decimals: int


@dataclass(frozen=True, slots=True)
class AirdropResult:
    requested_lamports: int
    signature: str | None
    final_balance_lamports: int


class DevnetRpcService:
    def __init__(self, settings: SolanaSettings) -> None:
        self._settings = settings
        self._endpoint = str(settings.solana_rpc_url)
        self._usdc_mint = Pubkey.from_string(settings.solana_usdc_mint)

    async def probe(self, wallet: Pubkey) -> DevnetRpcSnapshot:
        """Verify cluster identity, wallet balance, and the official USDC mint."""

        async with AsyncClient(self._endpoint, commitment=Confirmed) as client:
            genesis_hash = str((await client.get_genesis_hash()).value)
            self._require_devnet(genesis_hash)
            balance = (await client.get_balance(wallet, commitment=Confirmed)).value
            slot = (await client.get_slot(commitment=Confirmed)).value
            token_supply = (
                await client.get_token_supply(self._usdc_mint, commitment=Confirmed)
            ).value
        if token_supply.decimals != 6:
            raise WrongSolanaCluster("configured USDC mint does not have 6 decimals")
        return DevnetRpcSnapshot(
            endpoint=self._endpoint,
            genesis_hash=genesis_hash,
            slot=slot,
            wallet_balance_lamports=balance,
            usdc_mint=str(self._usdc_mint),
            usdc_decimals=token_supply.decimals,
        )

    async def fund_to_minimum_sol(self, wallet: Pubkey, minimum_lamports: int) -> AirdropResult:
        """Request only enough valueless Devnet SOL to reach the configured minimum."""

        if minimum_lamports <= 0:
            raise ValueError("minimum_lamports must be greater than zero")
        async with AsyncClient(self._endpoint, commitment=Confirmed) as client:
            genesis_hash = str((await client.get_genesis_hash()).value)
            self._require_devnet(genesis_hash)
            current = (await client.get_balance(wallet, commitment=Confirmed)).value
            if current >= minimum_lamports:
                return AirdropResult(
                    requested_lamports=0,
                    signature=None,
                    final_balance_lamports=current,
                )
            requested = minimum_lamports - current
            try:
                signature = (
                    await client.request_airdrop(wallet, requested, commitment=Confirmed)
                ).value
            except (RPCException, SolanaRpcException) as exc:
                raise DevnetFundingUnavailable(
                    "Devnet SOL airdrop was refused or rate-limited; use an official "
                    "faucet and rerun the probe"
                ) from exc
            await client.confirm_transaction(signature, commitment=Confirmed)
            final_balance = (
                await client.get_balance(wallet, commitment=Confirmed)
            ).value
        return AirdropResult(
            requested_lamports=requested,
            signature=str(signature),
            final_balance_lamports=final_balance,
        )

    @staticmethod
    def _require_devnet(genesis_hash: str) -> None:
        if genesis_hash != DEVNET_GENESIS_HASH:
            raise WrongSolanaCluster(
                "RPC genesis hash is not Solana Devnet; refusing wallet operation"
            )
