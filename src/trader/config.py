"""Load settings.yaml plus API credentials from the environment / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "settings.yaml"


@dataclass(frozen=True)
class Credentials:
    api_key: str
    secret_key: str
    paper: bool


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path) as f:
        settings = yaml.safe_load(f)
    # Resolve relative paths against the project root so commands work from any directory.
    for section, key in [("data", "cache_dir"), ("backtest", "results_dir"),
                         ("live", "log_dir"), ("risk", "kill_switch_file")]:
        value = settings.get(section, {}).get(key)
        if value and not Path(value).is_absolute():
            settings[section][key] = str(PROJECT_ROOT / value)
    return settings


def load_credentials() -> Credentials:
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret or key == "your_key_here":
        raise SystemExit(
            "Missing Alpaca credentials. Copy .env.example to .env and add your API keys."
        )
    paper = os.getenv("ALPACA_PAPER", "true").strip().lower() not in ("false", "0", "no")
    return Credentials(key, secret, paper)
