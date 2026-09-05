"""Domain rules for market observations and alert eligibility."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class PriceMovement:
    """The latest BTC price and its changes over configured windows."""

    price: float
    changes: Mapping[str, float]


@dataclass(frozen=True)
class PriceAlert:
    """A Price Alert that is eligible for delivery to the Telegram Audience."""

    window: str
    change_pct: float
    threshold_pct: float
    price: float

    @property
    def direction(self) -> str:
        return "up" if self.change_pct > 0 else "down"


class AlertPolicy:
    """Decides which price changes deserve alerts without knowing any adapter."""

    def __init__(self, thresholds: Mapping[str, float], cooldown_seconds: float) -> None:
        self._thresholds = dict(thresholds)
        self._cooldown_seconds = cooldown_seconds

    def evaluate(
        self,
        movement: PriceMovement,
        last_sent: Mapping[str, float],
        now: float,
    ) -> list[PriceAlert]:
        alerts: list[PriceAlert] = []
        for window, threshold in self._thresholds.items():
            change = movement.changes.get(window)
            if change is None or abs(change) < threshold:
                continue
            previous = last_sent.get(window)
            if previous and now - previous < self._cooldown_seconds:
                continue
            alerts.append(
                PriceAlert(
                    window=window,
                    change_pct=change,
                    threshold_pct=threshold,
                    price=movement.price,
                )
            )
        return alerts

