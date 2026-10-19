"""Configuration loading. Secrets come ONLY from environment variables."""
from __future__ import annotations
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_WEIGHTS = {"growth": 25, "business_quality": 20, "financial_strength": 15, "size_runway": 10,
                   "governance": 10, "valuation": 10, "technical": 5, "tailwinds": 5}

RISK_PRESETS = {  # used only when a value is missing from config.yaml
    "conservative": {"max_smallcap_pct": 10, "max_single_stock_pct": 8},
    "balanced": {"max_smallcap_pct": 20, "max_single_stock_pct": 10},
    "aggressive": {"max_smallcap_pct": 50, "max_single_stock_pct": 8},
}


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    risk = cfg.setdefault("risk", {})
    for k, v in RISK_PRESETS.get(risk.get("profile", "balanced"), {}).items():
        risk.setdefault(k, v)
    w = cfg.setdefault("scoring_weights", dict(DEFAULT_WEIGHTS))
    total = sum(w.values())
    if abs(total - 100) > 1e-9:
        raise ValueError(f"scoring_weights must sum to 100, got {total}")
    return cfg


def secret(name: str) -> str | None:
    """Read a secret from the environment (never from files in the repo)."""
    v = os.environ.get(name)
    return v if v else None


def redact(text: str) -> str:
    """Remove any known secret values from a log string."""
    for name in ("GMAIL_APP_PASSWORD",):
        v = os.environ.get(name)
        if v:
            text = text.replace(v, "***")
    return text
