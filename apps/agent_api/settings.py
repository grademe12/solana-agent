"""Validated runtime settings with a hard safety boundary around Solana Devnet."""

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SOLANA_DEVNET_USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"


class SolanaSettings(BaseSettings):
    """P0 settings; mainnet values are intentionally rejected."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    solana_network: Literal["devnet"] = "devnet"
    solana_rpc_url: AnyHttpUrl = AnyHttpUrl("https://api.devnet.solana.com")
    solana_keypair_path: Path = Path(".secrets/devnet-agent-keypair.json")
    solana_usdc_mint: str = Field(default=SOLANA_DEVNET_USDC_MINT, min_length=32)
    payment_execution_mode: Literal["mock", "devnet"] = "mock"
    demo_merchant_id: str = Field(default="demo-merchant", min_length=1, max_length=128)
    demo_merchant_recipient: str = Field(
        default="FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB",
        min_length=32,
        max_length=44,
    )

    @field_validator("solana_usdc_mint")
    @classmethod
    def require_official_devnet_usdc(cls, value: str) -> str:
        if value != SOLANA_DEVNET_USDC_MINT:
            raise ValueError("P0 only accepts the official Circle Solana Devnet USDC mint")
        return value

    def resolved_keypair_path(self, *, workspace: Path | None = None) -> Path:
        if self.solana_keypair_path.is_absolute():
            return self.solana_keypair_path.resolve()
        return ((workspace or Path.cwd()) / self.solana_keypair_path).resolve()
