"""Verify that the P0 local toolchain and Python dependencies are available."""

from __future__ import annotations

import importlib
import importlib.metadata
import platform
import sys

REQUIRED_IMPORTS = {
    "fastapi": "fastapi",
    "google-adk": "google.adk",
    "httpx": "httpx",
    "pillow": "PIL",
    "pydantic-settings": "pydantic_settings",
    "solana": "solana",
    "solders": "solders",
    "zxing-cpp": "zxingcpp",
}


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        print(f"ERROR: Python 3.12 is required; found {platform.python_version()}")
        return 1

    failures: list[str] = []
    print(f"Python {platform.python_version()}")

    for distribution, module in REQUIRED_IMPORTS.items():
        try:
            importlib.import_module(module)
            version = importlib.metadata.version(distribution)
            print(f"OK {distribution}=={version}")
        except Exception as exc:  # pragma: no cover - diagnostic script
            failures.append(f"{distribution}: {exc}")

    if failures:
        for failure in failures:
            print(f"ERROR {failure}")
        return 1

    print("Environment verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
