from dataclasses import replace

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from spl.token.instructions import decode_transfer_checked, get_associated_token_address

from apps.agent_api.services.solana_transfer import (
    build_usdc_transfer_plan,
    compile_and_sign_transfer,
    transfer_plan_matches_intent,
)
from apps.agent_api.settings import SOLANA_DEVNET_USDC_MINT
from apps.agent_api.tools.resolve_intent import resolve_payment_intent
from packages.schemas import PaymentIntent

RECIPIENT = "FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB"
REFERENCE = "SysvarC1ock11111111111111111111111111111111"


def make_intent() -> PaymentIntent:
    return resolve_payment_intent(
        f"solana:{RECIPIENT}?amount=1.25&spl-token={SOLANA_DEVNET_USDC_MINT}"
        f"&reference={REFERENCE}"
    )


def test_builds_direct_usdc_transfer_with_reference_account() -> None:
    signer = Keypair()
    mint = Pubkey.from_string(SOLANA_DEVNET_USDC_MINT)
    intent = make_intent()

    plan = build_usdc_transfer_plan(intent, payer=signer.pubkey())

    assert plan.source_token_account == get_associated_token_address(signer.pubkey(), mint)
    assert plan.destination_token_account == get_associated_token_address(
        Pubkey.from_string(RECIPIENT), mint
    )
    assert plan.amount_atomic == 1_250_000
    assert plan.decimals == 6
    assert len(plan.instructions) == 2

    transfer = plan.instructions[-1]
    decoded = decode_transfer_checked(transfer)
    assert decoded.amount == 1_250_000
    assert decoded.decimals == 6
    assert transfer.accounts[-1].pubkey == Pubkey.from_string(REFERENCE)
    assert transfer.accounts[-1].is_signer is False
    assert transfer.accounts[-1].is_writable is False
    assert transfer_plan_matches_intent(plan, intent)


def test_compiles_and_signs_only_matching_plan() -> None:
    signer = Keypair()
    intent = make_intent()
    plan = build_usdc_transfer_plan(intent, payer=signer.pubkey())

    transaction = compile_and_sign_transfer(
        plan,
        intent,
        signer=signer,
        recent_blockhash=Hash.new_unique(),
    )

    assert transaction.verify_with_results() == [True]
    assert transaction.message.account_keys[0] == signer.pubkey()


def test_recipient_tampering_is_rejected_before_signing() -> None:
    signer = Keypair()
    intent = make_intent()
    plan = build_usdc_transfer_plan(intent, payer=signer.pubkey())
    tampered = replace(plan, recipient=Pubkey.new_unique())

    assert not transfer_plan_matches_intent(tampered, intent)
    with pytest.raises(ValueError, match="does not match"):
        compile_and_sign_transfer(
            tampered,
            intent,
            signer=signer,
            recent_blockhash=Hash.new_unique(),
        )


def test_wrong_signer_is_rejected() -> None:
    payer = Keypair()
    intent = make_intent()
    plan = build_usdc_transfer_plan(intent, payer=payer.pubkey())

    with pytest.raises(ValueError, match="does not control"):
        compile_and_sign_transfer(
            plan,
            intent,
            signer=Keypair(),
            recent_blockhash=Hash.new_unique(),
        )

