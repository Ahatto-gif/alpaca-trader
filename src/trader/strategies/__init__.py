"""Strategy registry. Add your strategy class here to make it available in the config/CLI."""
from .base import Strategy
from .rsi_mean_reversion import RsiMeanReversion
from .sma_crossover import SmaCrossover

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (SmaCrossover, RsiMeanReversion)
}


def build_strategy(name: str, params: dict | None = None) -> Strategy:
    if name not in REGISTRY:
        raise SystemExit(f"Unknown strategy '{name}'. Available: {', '.join(REGISTRY)}")
    return REGISTRY[name](**(params or {}))


__all__ = ["Strategy", "REGISTRY", "build_strategy"]
