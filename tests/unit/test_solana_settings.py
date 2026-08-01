from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.agent_api.settings import SOLANA_DEVNET_USDC_MINT, SolanaSettings


def test_settings_default_to_devnet_and_official_usdc(tmp_path: Path) -> None:
    settings = SolanaSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.solana_network == "devnet"
    assert str(settings.solana_rpc_url) == "https://api.devnet.solana.com/"
    assert settings.solana_usdc_mint == SOLANA_DEVNET_USDC_MINT
    assert settings.parsed_cors_allowed_origins() == [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]
    assert settings.resolved_keypair_path(workspace=tmp_path) == (
        tmp_path / ".secrets/devnet-agent-keypair.json"
    ).resolve()


def test_mainnet_network_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SolanaSettings(solana_network="mainnet", _env_file=None)  # type: ignore[arg-type,call-arg]


def test_non_official_mint_is_rejected() -> None:
    with pytest.raises(ValidationError, match="official Circle"):
        SolanaSettings(solana_usdc_mint="FakeMint111111111111111111111111111111", _env_file=None)  # type: ignore[call-arg]
