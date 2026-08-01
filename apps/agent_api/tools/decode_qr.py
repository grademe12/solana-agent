"""Decode a QR image without following links or performing payment actions."""

from __future__ import annotations

import hashlib
import warnings
from io import BytesIO

import zxingcpp
from PIL import Image, UnidentifiedImageError

from packages.schemas import DecodedPaymentQr

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = MAX_IMAGE_DIMENSION * MAX_IMAGE_DIMENSION
ALLOWED_IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})


class QrDecodeError(ValueError):
    """A safe, structured QR decoding failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _load_image(image_bytes: bytes) -> Image.Image:
    if not image_bytes:
        raise QrDecodeError("empty_image", "QR image is empty")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise QrDecodeError("image_too_large", "QR image exceeds the 10 MiB limit")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(image_bytes))
            if image.format not in ALLOWED_IMAGE_FORMATS:
                raise QrDecodeError(
                    "unsupported_image_format", "QR image must be PNG, JPEG, or WEBP"
                )
            width, height = image.size
            if (
                width <= 0
                or height <= 0
                or width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise QrDecodeError(
                    "image_dimensions_exceeded", "QR image dimensions exceed safety limits"
                )
            image.load()
            return image.convert("RGB")
    except QrDecodeError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise QrDecodeError(
            "image_dimensions_exceeded", "QR image dimensions exceed safety limits"
        ) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise QrDecodeError("invalid_image", "Input is not a valid supported image") from exc


def decode_payment_qr(image_bytes: bytes) -> DecodedPaymentQr:
    """Extract one QR payload; never fetch or otherwise act on the decoded value."""

    if not isinstance(image_bytes, bytes):
        raise TypeError("image_bytes must be bytes")

    image = _load_image(image_bytes)
    qr_formats = zxingcpp.BarcodeFormats(zxingcpp.BarcodeFormat.QRCode)
    barcodes = zxingcpp.read_barcodes(image, formats=qr_formats)
    if not barcodes:
        raise QrDecodeError("decode_failed", "No readable QR code was found")
    if len(barcodes) != 1:
        raise QrDecodeError("ambiguous_qr", "Image must contain exactly one QR code")

    raw_payload = barcodes[0].text
    if not raw_payload:
        raise QrDecodeError("empty_payload", "QR code contains no text")
    if len(raw_payload) > 4096:
        raise QrDecodeError("payload_too_large", "QR payload exceeds 4096 characters")

    payload_hash = "sha256:" + hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
    return DecodedPaymentQr(
        raw_payload=raw_payload,
        payload_hash=payload_hash,
        image_width=image.width,
        image_height=image.height,
    )
