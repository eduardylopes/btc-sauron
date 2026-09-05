from datetime import datetime
import unittest

from btcsauron.schedule import DailySchedule


class DailyScheduleTests(unittest.TestCase):
    def test_selects_todays_future_report_time(self) -> None:
        schedule = DailySchedule("08:00")

        self.assertEqual(
            schedule.next_after(datetime(2026, 9, 5, 7, 59)),
            datetime(2026, 9, 5, 8, 0),
        )

    def test_selects_tomorrow_when_todays_time_has_arrived(self) -> None:
        schedule = DailySchedule("08:00")

        self.assertEqual(
            schedule.next_after(datetime(2026, 9, 5, 8, 0)),
            datetime(2026, 9, 6, 8, 0),
        )

