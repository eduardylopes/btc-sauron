"""Detecção de variação brusca de preço com alerta via Telegram.

Um único request de candles 1h (limit=25) cobre as janelas de 1h, 4h e 24h.
Cooldown por janela, persistido no arquivo de estado (evita spam e sobrevive
a restart do container).
"""
import logging
import time

from . import sources, telegram
from .domain import AlertPolicy, PriceMovement

log = logging.getLogger("btcsauron.alerts")


def _pct(a: float, b: float) -> float:
    return (a - b) / b * 100.0


def compute_moves(timeout: int = 15) -> dict:
    """Variação % de 1h, 4h e 24h a partir dos candles 1h."""
    k = sources.fetch_binance_klines("1h", limit=25, timeout=timeout)
    if len(k) < 25:
        raise RuntimeError(f"candles insuficientes: {len(k)}")
    last = k[-1]["close"]
    return {
        "price": last,
        "move_1h": _pct(last, k[-2]["close"]),
        "move_4h": _pct(last, k[-5]["close"]),
        "move_24h": _pct(last, k[-25]["close"]),
    }


def check_alerts(cfg, state: dict) -> list[str]:
    """Roda uma verificação de alerta. Retorna lista de mensagens enviadas."""
    if not cfg.alert_enabled:
        return []
    moves = compute_moves(cfg.http_timeout)
    now = time.time()
    last_alerts = state.setdefault("last_alerts", {})
    sent: list[str] = []
    policy = AlertPolicy(
        thresholds={
            "1h": cfg.alert_1h_pct,
            "4h": cfg.alert_4h_pct,
            "24h": cfg.alert_24h_pct,
        },
        cooldown_seconds=cfg.alert_cooldown_hours * 3600,
    )
    movement = PriceMovement(
        price=moves["price"],
        changes={
            "1h": moves["move_1h"],
            "4h": moves["move_4h"],
            "24h": moves["move_24h"],
        },
    )

    for alert in policy.evaluate(movement, last_alerts, now):
        direction = "🚀" if alert.direction == "up" else "🚨"
        from .report import colorize_pct
        msg = (
            f"{direction} <b>ALERTA BTC</b> — {alert.window} {alert.change_pct:+.2f}%\n"
            f"Preço: ${alert.price:,.2f}\n"
            f"1h {colorize_pct(moves['move_1h'])} · 4h {colorize_pct(moves['move_4h'])} · "
            f"24h {colorize_pct(moves['move_24h'])}"
        )
        if cfg.telegram_configured:
            ok = telegram.send_message(
                cfg.telegram_bot_token, cfg.telegram_chat_id, msg, cfg.http_timeout)
            if not ok:
                continue  # não marca cooldown se falhou
        else:
            log.info("ALERTA (sem Telegram configurado): %s", msg.replace("\n", " | "))
        last_alerts[alert.window] = now
        sent.append(msg)
    return sent

