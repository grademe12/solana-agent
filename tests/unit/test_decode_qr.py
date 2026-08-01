from io import BytesIO

import pytest
import zxingcpp  # type: ignore[import-untyped]
from PIL import Image

from apps.agent_api.tools.decode_qr import QrDecodeError, decode_payment_qr


def _qr_png(payload: str) -> bytes:
    barcode = zxingcpp.create_barcode(payload, zxingcpp.BarcodeFormat.QRCode)
    qr_image = zxingcpp.write_barcode_to_image(barcode, scale=4)
    height, width = qr_image.shape
    image = Image.frombytes("L", (width, height), bytes(qr_image))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_decodes_qr_payload_without_acting_on_url() -> None:
    payload = "https://example.invalid/payment?order=123"

    decoded = decode_payment_qr(_qr_png(payload))

    assert decoded.raw_payload == payload
    assert decoded.payload_hash.startswith("sha256:")
    assert decoded.image_width > 0
    assert decoded.image_height > 0


def test_rejects_non_image_input() -> None:
    with pytest.raises(QrDecodeError) as exc_info:
        decode_payment_qr(b"not an image")

    assert exc_info.value.code == "invalid_image"


def test_rejects_image_without_qr() -> None:
    image = Image.new("RGB", (100, 100), "white")
    output = BytesIO()
    image.save(output, format="PNG")

    with pytest.raises(QrDecodeError) as exc_info:
        decode_payment_qr(output.getvalue())

    assert exc_info.value.code == "decode_failed"

