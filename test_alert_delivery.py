from types import SimpleNamespace
import unittest
from unittest.mock import patch

from btcsauron.alerts import check_alerts


def config(**overrides):
    values = {
        "alert_enabled": True,
        "http_timeout": 15,
        "alert_1h_pct": 3.0,
        "alert_4h_pct": 5.0,
        "alert_24h_pct": 8.0,
        "alert_cooldown_hours": 6.0,
        "telegram_configured": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class AlertDeliveryTests(unittest.TestCase):
    @patch("btcsauron.alerts.time.time", return_value=1_000)
    @patch("btcsauron.alerts.compute_moves")
    def test_records_cooldown_only_for_alerts_that_are_delivered(self, moves, _clock) -> None:
        moves.return_value = {
            "price": 100_000,
            "move_1h": 4.0,
            "move_4h": 1.0,
            "move_24h": -9.0,
        }
        state = {}

        sent = check_alerts(config(), state)

        self.assertEqual(len(sent), 2)
        self.assertEqual(state["last_alerts"], {"1h": 1_000, "24h": 1_000})

    @patch("btcsauron.alerts.compute_moves")
    def test_does_not_query_market_when_alerts_are_disabled(self, moves) -> None:
        self.assertEqual(check_alerts(config(alert_enabled=False), {}), [])
        moves.assert_not_called()
