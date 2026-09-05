"""Configuração via variáveis de ambiente (todas com padrão)."""
import os
from datetime import timedelta, timezone


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    def __init__(self) -> None:
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.report_time = os.getenv("REPORT_TIME", "08:00")
        try:
            _hh, _mm = (int(x) for x in self.report_time.split(":"))
            if not (0 <= _hh <= 23 and 0 <= _mm <= 59):
                raise ValueError
        except ValueError as e:
            raise ValueError(
                f"REPORT_TIME inválido: '{self.report_time}' (use HH:MM, ex.: 08:00)"
            ) from e
        self.report_on_start = _bool("REPORT_ON_START", True)

        # Variação brusca
        self.alert_enabled = _bool("ALERT_ENABLED", True)
        self.alert_interval_seconds = _int("ALERT_INTERVAL_SECONDS", 600)
        self.alert_1h_pct = _float("ALERT_1H_PCT", 3.0)
        self.alert_4h_pct = _float("ALERT_4H_PCT", 5.0)
        self.alert_24h_pct = _float("ALERT_24H_PCT", 8.0)
        self.alert_cooldown_hours = _float("ALERT_COOLDOWN_HOURS", 6.0)

        self.state_file = os.getenv("STATE_FILE", "/data/state.json")
        self.http_timeout = _int("HTTP_TIMEOUT_SECONDS", 15)
        self.log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        self.tz_name = os.getenv("TZ", "America/Sao_Paulo")

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def local_tz(self):
        """Fuso local. Em Linux (Docker com tzdata) usa zoneinfo; em Windows
        sem tzdata cai para UTC-3 fixo (Brasília, sem DST desde 2019)."""
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(self.tz_name)
        except Exception:
            return timezone(timedelta(hours=-3), name="UTC-3")

