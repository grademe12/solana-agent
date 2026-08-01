"""Local keypair persistence that never logs or returns secret material as text."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from solders.keypair import Keypair


@dataclass(frozen=True, slots=True)
class KeypairFileResult:
    keypair: Keypair
    path: Path
    created: bool


def _validate_secret_bytes(value: object) -> bytes:
    if not isinstance(value, list) or len(value) != Keypair.LENGTH:
        raise ValueError("keypair file must contain exactly 64 byte values")
    invalid_byte = any(
        not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 255
        for item in value
    )
    if invalid_byte:
        raise ValueError("keypair file contains an invalid byte value")
    return bytes(value)


def load_keypair_file(path: Path) -> Keypair:
    """Load a Solana keypair without emitting its secret bytes."""

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("keypair file is missing, unreadable, or invalid JSON") from exc
    secret_bytes = _validate_secret_bytes(parsed)
    try:
        return Keypair.from_bytes(secret_bytes)
    except ValueError as exc:
        raise ValueError("keypair file does not contain a valid Solana keypair") from exc


def create_or_load_keypair_file(path: Path) -> KeypairFileResult:
    """Create a new file atomically, or load the existing key without overwriting it."""

    resolved = path.resolve()
    resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            resolved,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        return KeypairFileResult(
            keypair=load_keypair_file(resolved),
            path=resolved,
            created=False,
        )

    keypair = Keypair()
    serialized = json.dumps(list(bytes(keypair)), separators=(",", ":"))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(serialized)
            file.write("\n")
        os.chmod(resolved, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        try:
            resolved.unlink(missing_ok=True)
        finally:
            raise
    return KeypairFileResult(keypair=keypair, path=resolved, created=True)
