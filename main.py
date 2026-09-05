"""btc-sauron — entrypoint.

Modos:
  python -m btcsauron.main report   → relatório único (útil p/ teste/cron)
  python -m btcsauron.main run      → daemon: relatório diário + alertas 24/7
  python -m btcsauron.main check    → uma verificação única de alerta (teste)
"""
import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime

from . import alerts, report, sources, telegram
from .config import Config
from .schedule import DailySchedule

log = logging.getLogger("btcsauron")


def _setup_logging(cfg: Config) -> None:
    level = getattr(logging, cfg.log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _load_state(cfg: Config) -> dict:
    try:
        with open(cfg.state_file, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(cfg: Config, state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(cfg.state_file), exist_ok=True)
        tmp = cfg.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, cfg.state_file)
    except OSError as e:
        log.warning("Não foi possível salvar estado em %s: %s", cfg.state_file, e)


def _gather_market_data(cfg: Config) -> dict:
    """Preço ao vivo + movimentos + funding (Binance)."""
    market = {"price": None, "change_24h_pct": None,
              "move_1h": None, "move_4h": None, "funding": None}
    try:
        market.update(sources.fetch_binance_ticker(cfg.http_timeout))
    except Exception as e:
        log.error("Ticker Binance falhou: %s", e)
    try:
        market.update(alerts.compute_moves(cfg.http_timeout))
    except Exception as e:
        log.warning("Movimentos Binance indisponíveis: %s", e)
    market["funding"] = sources.fetch_binance_funding(cfg.http_timeout)
    return market


def generate_report_text(cfg: Config, liq_totals: dict | None = None) -> tuple[str, datetime]:
    daily = sources.fetch_coinmetrics_daily(cfg.http_timeout)
    from .indicators import compute_indicators
    ind = compute_indicators(daily)
    market = _gather_market_data(cfg)
    fng = sources.fetch_fear_greed(cfg.http_timeout)
    extra = {
        "etf": sources.fetch_etf_flows(cfg.http_timeout),
        "trends": sources.fetch_google_trends(cfg.http_timeout),
        "liquidations": liq_totals or {},
    }
    now = datetime.now(cfg.local_tz())
    return report.build_report(ind, market, fng, now, extra), now


def _liq_totals_from_file(cfg: Config) -> dict:
    """Totais persistidos (para modo report único / inspeção)."""
    from .liquidations import LiquidationTracker
    return LiquidationTracker(cfg.state_file).totals_24h()


def cmd_report(cfg: Config) -> int:
    text, now = generate_report_text(cfg, _liq_totals_from_file(cfg))
    log.info("Relatório gerado (%s):\n%s", now, text)
    if cfg.telegram_configured:
        telegram.send_message(cfg.telegram_bot_token, cfg.telegram_chat_id, text, cfg.http_timeout)
    else:
        log.warning("TELEGRAM_BOT_TOKEN/CHAT_ID ausentes — relatório apenas no log/stdout")
        print(text)
    return 0


def cmd_check(cfg: Config) -> int:
    state = _load_state(cfg)
    sent = alerts.check_alerts(cfg, state)
    _save_state(cfg, state)
    log.info("Alertas disparados nesta checagem: %d", len(sent))
    return 0


def _next_report_time(cfg: Config, now: datetime) -> datetime:
    return DailySchedule(cfg.report_time).next_after(now)


def cmd_run(cfg: Config) -> int:
    state = _load_state(cfg)
    tz = cfg.local_tz()

    # Agregador de liquidações (thread): acumula 24h via WS da OKX
    from .liquidations import LiquidationTracker
    tracker = LiquidationTracker(cfg.state_file)
    stop_event = threading.Event()
    threading.Thread(target=tracker.run_worker, args=(stop_event,), daemon=True,
                     name="liquidations-okx").start()

    # Comandos do bot (thread): responde /indicadores, /help, /start
    from .commands import run_telegram_commands
    threading.Thread(target=run_telegram_commands,
                     args=(cfg, state, lambda: _save_state(cfg, state), stop_event),
                     daemon=True, name="telegram-commands").start()

    if cfg.report_on_start:
        try:
            text, _ = generate_report_text(cfg, tracker.totals_24h())
            if cfg.telegram_configured:
                telegram.send_message(cfg.telegram_bot_token, cfg.telegram_chat_id, text, cfg.http_timeout)
            else:
                log.info("Relatório inicial (sem Telegram):\n%s", text)
            state["last_report_date"] = datetime.now(tz).date().isoformat()
            _save_state(cfg, state)
        except Exception as e:
            log.exception("Falha no relatório inicial: %s", e)

    last_alert_check = time.time()
    while True:
        now = datetime.now(tz)
        # Relatório diário
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_report = _next_report_time(cfg, midnight)
        if state.get("last_report_date") != now.date().isoformat() and now >= today_report:
            try:
                text, _ = generate_report_text(cfg, tracker.totals_24h())
                if cfg.telegram_configured:
                    telegram.send_message(cfg.telegram_bot_token, cfg.telegram_chat_id, text, cfg.http_timeout)
                else:
                    log.info("Relatório diário (sem Telegram):\n%s", text)
                state["last_report_date"] = now.date().isoformat()
                _save_state(cfg, state)
            except Exception as e:
                log.exception("Falha no relatório diário: %s", e)
        # Alertas
        if time.time() - last_alert_check >= cfg.alert_interval_seconds:
            try:
                alerts.check_alerts(cfg, state)
                _save_state(cfg, state)
            except Exception as e:
                log.exception("Falha na checagem de alertas: %s", e)
            last_alert_check = time.time()
        time.sleep(20)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="btc-sauron")
    parser.add_argument("mode", nargs="?", default="run",
                        choices=["run", "report", "check"],
                        help="run=daemon (padrão), report=uma vez, check=alertas uma vez")
    args = parser.parse_args(argv)

    cfg = Config()
    _setup_logging(cfg)
    # Console Windows usa cp1252 e quebra com emojis — força UTF-8
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    log.info("btc-sauron v1.1.0 — modo '%s' (TZ=%s)", args.mode, cfg.tz_name)

    if args.mode == "report":
        return cmd_report(cfg)
    if args.mode == "check":
        return cmd_check(cfg)
    return cmd_run(cfg)


if __name__ == "__main__":
    sys.exit(main())
