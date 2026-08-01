import base64
import json
from datetime import UTC, datetime

import pytest
from solders.hash import Hash
from solders.keypair import Keypair

from apps.agent_api.services.receipts import (
    ReceiptVerificationError,
    verify_confirmed_transaction,
)
from apps.agent_api.services.solana_transfer import (
    build_usdc_transfer_plan,
    compile_and_sign_transfer,
)
from apps.agent_api.settings import SOLANA_DEVNET_USDC_MINT
from apps.agent_api.tools.resolve_intent import resolve_payment_intent
from packages.schemas import PaymentIntent

RECIPIENT = "FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB"
REFERENCE = "SysvarC1ock11111111111111111111111111111111"
OTHER_REFERENCE = "SysvarRent111111111111111111111111111111111"
NOW = datetime(2026, 8, 1, 15, tzinfo=UTC)


def make_intent(*, amount: str = "1.25", reference: str = REFERENCE) -> PaymentIntent:
    return resolve_payment_intent(
        f"solana:{RECIPIENT}?amount={amount}&spl-token={SOLANA_DEVNET_USDC_MINT}"
        f"&reference={reference}"
    )


def make_response(
    intent: PaymentIntent,
    signer: Keypair,
    *,
    error: object = None,
) -> tuple[str, str]:
    plan = build_usdc_transfer_plan(intent, payer=signer.pubkey())
    transaction = compile_and_sign_transfer(
        plan,
        intent,
        signer=signer,
        recent_blockhash=Hash.new_unique(),
    )
    signature = str(transaction.signatures[0])
    response = {
        "jsonrpc": "2.0",
        "result": {
            "meta": {"err": error},
            "transaction": [
                base64.b64encode(bytes(transaction)).decode("ascii"),
                "base64",
            ],
        },
        "id": 1,
    }
    return json.dumps(response), signature


def test_verifies_exact_wire_transaction_and_returns_receipt() -> None:
    signer = Keypair()
    intent = make_intent()
    response, signature = make_response(intent, signer)

    receipt = verify_confirmed_transaction(
        response,
        intent,
        expected_payer=signer.pubkey(),
        expected_signature=signature,
        confirmed_at=NOW,
    )

    assert receipt.signature == signature
    assert receipt.payer == str(signer.pubkey())
    assert receipt.recipient == RECIPIENT
    assert receipt.mint == SOLANA_DEVNET_USDC_MINT
    assert receipt.amount_atomic == 1_250_000
    assert receipt.decimals == 6
    assert receipt.reference == REFERENCE
    assert receipt.explorer_url.endswith(f"/{signature}?cluster=devnet")


@pytest.mark.parametrize(
    "different_intent",
    [make_intent(amount="1.26"), make_intent(reference=OTHER_REFERENCE)],
)
def test_rejects_amount_or_reference_mismatch(different_intent: PaymentIntent) -> None:
    signer = Keypair()
    response, signature = make_response(make_intent(), signer)

    with pytest.raises(ReceiptVerificationError, match="does not match"):
        verify_confirmed_transaction(
            response,
            different_intent,
            expected_payer=signer.pubkey(),
            expected_signature=signature,
            confirmed_at=NOW,
        )


def test_rejects_failed_onchain_transaction() -> None:
    signer = Keypair()
    intent = make_intent()
    response, signature = make_response(intent, signer, error={"InstructionError": [1, 1]})

    with pytest.raises(ReceiptVerificationError, match="failed on chain"):
        verify_confirmed_transaction(
            response,
            intent,
            expected_payer=signer.pubkey(),
            expected_signature=signature,
            confirmed_at=NOW,
        )


def test_rejects_different_submission_signature() -> None:
    signer = Keypair()
    intent = make_intent()
    response, _ = make_response(intent, signer)

    with pytest.raises(ReceiptVerificationError, match="signature does not match"):
        verify_confirmed_transaction(
            response,
            intent,
            expected_payer=signer.pubkey(),
            expected_signature=str(Keypair().sign_message(b"other")),
            confirmed_at=NOW,
        )
