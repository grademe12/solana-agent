import pytest

from apps.agent_api.services.devnet_rpc import (
    DEVNET_GENESIS_HASH,
    DevnetRpcService,
    WrongSolanaCluster,
)


def test_accepts_full_devnet_genesis_hash() -> None:
    DevnetRpcService._require_devnet(DEVNET_GENESIS_HASH)


def test_rejects_mainnet_or_truncated_genesis_hash() -> None:
    with pytest.raises(WrongSolanaCluster):
        DevnetRpcService._require_devnet("5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d")
    with pytest.raises(WrongSolanaCluster):
        DevnetRpcService._require_devnet("EtWTRABZaYq6iMfeYKouRu166VU2xqa1")

