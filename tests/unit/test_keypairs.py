import json
from pathlib import Path

import pytest

from apps.agent_api.services.keypairs import (
    create_or_load_keypair_file,
    load_keypair_file,
)


def test_keypair_file_is_created_once_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / ".secrets" / "agent.json"

    created = create_or_load_keypair_file(path)
    loaded = create_or_load_keypair_file(path)

    assert created.created is True
    assert loaded.created is False
    assert created.keypair.pubkey() == loaded.keypair.pubkey()
    assert created.path == path.resolve()
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 64


def test_existing_keypair_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "agent.json"
    first = create_or_load_keypair_file(path)
    original = path.read_bytes()

    second = create_or_load_keypair_file(path)

    assert path.read_bytes() == original
    assert second.keypair.pubkey() == first.keypair.pubkey()


def test_invalid_keypair_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[1,2,3]", encoding="utf-8")

    with pytest.raises(ValueError, match="64 byte"):
        load_keypair_file(path)

