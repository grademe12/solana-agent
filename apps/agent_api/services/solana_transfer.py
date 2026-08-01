"""Build, verify, sign, and simulate guarded Solana Devnet USDC transfers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    create_idempotent_associated_token_account,
    get_associated_token_address,
    transfer_checked,
)
from spl.token.models import TransferCheckedParams

from apps.agent_api.services.devnet_rpc import DevnetRpcService
from apps.agent_api.services.keypairs import load_keypair_file
from apps.agent_api.settings import SOLANA_DEVNET_USDC_MINT, SolanaSettings
from packages.schemas import PaymentIntent


@dataclass(frozen=True, slots=True)
class SolanaTransferPlan:
    intent_id: str
    network: str
    payer: Pubkey
    recipient: Pubkey
    mint: Pubkey
    source_token_account: Pubkey
    destination_token_account: Pubkey
    amount_atomic: int
    decimals: int
    reference: Pubkey
    instructions: tuple[Instruction, ...]


@dataclass(frozen=True, slots=True)
class PreparedSolanaTransfer:
    plan: SolanaTransferPlan
    transaction: VersionedTransaction
    recent_blockhash: Hash
    last_valid_block_height: int
    estimated_fee_lamports: int | None
    simulation_succeeded: bool
    simulation_error: str | None
    simulation_logs: tuple[str, ...]
    units_consumed: int | None
    submitted: bool = False


def _transfer_with_reference(
    *,
    source: Pubkey,
    mint: Pubkey,
    destination: Pubkey,
    owner: Pubkey,
    amount_atomic: int,
    decimals: int,
    reference: Pubkey,
) -> Instruction:
    transfer = transfer_checked(
        TransferCheckedParams(
            program_id=TOKEN_PROGRAM_ID,
            source=source,
            mint=mint,
            dest=destination,
            owner=owner,
            amount=amount_atomic,
            decimals=decimals,
        )
    )
    return Instruction(
        transfer.program_id,
        transfer.data,
        [*transfer.accounts, AccountMeta(reference, False, False)],
    )


def build_usdc_transfer_plan(intent: PaymentIntent, *, payer: Pubkey) -> SolanaTransferPlan:
    """Build the only P0 transfer shape: direct official USDC on Solana Devnet."""

    if not intent.is_executable or intent.amount is None or intent.asset is None:
        raise ValueError("payment intent is not executable")
    if intent.network != "solana:devnet":
        raise ValueError("P0 transfer builder only accepts Solana Devnet")
    if intent.asset.mint != SOLANA_DEVNET_USDC_MINT or intent.asset.decimals != 6:
        raise ValueError("P0 transfer builder only accepts official Devnet USDC")
    if intent.recipient is None or intent.reference is None:
        raise ValueError("payment intent is missing recipient or reference")

    recipient = Pubkey.from_string(intent.recipient)
    mint = Pubkey.from_string(intent.asset.mint)
    reference = Pubkey.from_string(intent.reference)
    source_token_account = get_associated_token_address(payer, mint)
    destination_token_account = get_associated_token_address(recipient, mint)

    create_destination = create_idempotent_associated_token_account(
        payer=payer,
        owner=recipient,
        mint=mint,
    )
    transfer = _transfer_with_reference(
        source=source_token_account,
        mint=mint,
        destination=destination_token_account,
        owner=payer,
        amount_atomic=intent.amount.atomic,
        decimals=intent.amount.decimals,
        reference=reference,
    )
    return SolanaTransferPlan(
        intent_id=intent.intent_id,
        network=intent.network,
        payer=payer,
        recipient=recipient,
        mint=mint,
        source_token_account=source_token_account,
        destination_token_account=destination_token_account,
        amount_atomic=intent.amount.atomic,
        decimals=intent.amount.decimals,
        reference=reference,
        instructions=(create_destination, transfer),
    )


def transfer_plan_matches_intent(plan: SolanaTransferPlan, intent: PaymentIntent) -> bool:
    """Rebuild expected instructions and reject any field or account-meta tampering."""

    try:
        expected = build_usdc_transfer_plan(intent, payer=plan.payer)
    except ValueError:
        return False
    return plan == expected


def compile_and_sign_transfer(
    plan: SolanaTransferPlan,
    intent: PaymentIntent,
    *,
    signer: Keypair,
    recent_blockhash: Hash,
) -> VersionedTransaction:
    """Sign only after the complete transfer plan has been deterministically rebuilt."""

    if signer.pubkey() != plan.payer:
        raise ValueError("signer does not control the plan payer")
    if not transfer_plan_matches_intent(plan, intent):
        raise ValueError("transfer plan does not match payment intent")
    message = MessageV0.try_compile(
        plan.payer,
        list(plan.instructions),
        [],
        recent_blockhash,
    )
    return VersionedTransaction(message, [signer])


class DevnetUsdcTransferService:
    """Prepare a real signed transaction and simulate it, without submitting it."""

    def __init__(self, settings: SolanaSettings) -> None:
        self._settings = settings
        self._endpoint = str(settings.solana_rpc_url)
        self._rpc_guard = DevnetRpcService(settings)

    async def prepare_and_simulate(self, intent: PaymentIntent) -> PreparedSolanaTransfer:
        signer = load_keypair_file(self._settings.resolved_keypair_path())
        await self._rpc_guard.probe(signer.pubkey())
        plan = build_usdc_transfer_plan(intent, payer=signer.pubkey())

        async with AsyncClient(self._endpoint, commitment=Confirmed) as client:
            genesis_hash = str((await client.get_genesis_hash()).value)
            DevnetRpcService._require_devnet(genesis_hash)
            latest = (await client.get_latest_blockhash(commitment=Confirmed)).value
            transaction = compile_and_sign_transfer(
                plan,
                intent,
                signer=signer,
                recent_blockhash=latest.blockhash,
            )
            message = cast(MessageV0, transaction.message)
            fee = (await client.get_fee_for_message(message, commitment=Confirmed)).value
            simulation = await client.simulate_transaction(
                transaction,
                sig_verify=True,
                commitment=Confirmed,
                replace_recent_blockhash=False,
                inner_instructions=True,
            )

        simulation_value = simulation.value
        error = str(simulation_value.err) if simulation_value.err is not None else None
        return PreparedSolanaTransfer(
            plan=plan,
            transaction=transaction,
            recent_blockhash=latest.blockhash,
            last_valid_block_height=latest.last_valid_block_height,
            estimated_fee_lamports=fee,
            simulation_succeeded=simulation_value.err is None,
            simulation_error=error,
            simulation_logs=tuple(simulation_value.logs or ()),
            units_consumed=simulation_value.units_consumed,
        )
