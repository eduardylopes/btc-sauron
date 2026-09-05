import unittest

from btcsauron.domain import AlertPolicy, PriceMovement


class AlertPolicyTests(unittest.TestCase):
    def test_emits_only_windows_that_cross_their_threshold(self) -> None:
        policy = AlertPolicy(
            thresholds={"1h": 3.0, "4h": 5.0, "24h": 8.0},
            cooldown_seconds=6 * 3600,
        )

        alerts = policy.evaluate(
            PriceMovement(price=100_000, changes={"1h": 3.1, "4h": -4.9, "24h": -8.2}),
            last_sent={},
            now=1_000,
        )

        self.assertEqual([alert.window for alert in alerts], ["1h", "24h"])
        self.assertEqual(alerts[1].change_pct, -8.2)

    def test_respects_cooldown_per_window(self) -> None:
        policy = AlertPolicy(
            thresholds={"1h": 3.0, "4h": 5.0, "24h": 8.0},
            cooldown_seconds=6 * 3600,
        )

        alerts = policy.evaluate(
            PriceMovement(price=100_000, changes={"1h": 4.0, "4h": 6.0, "24h": 9.0}),
            last_sent={"1h": 900, "4h": 0},
            now=1_000,
        )

        self.assertEqual([alert.window for alert in alerts], ["4h", "24h"])
