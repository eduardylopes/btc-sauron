"""Envio de mensagens via Telegram Bot API (stdlib apenas)."""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("btcsauron.telegram")

API = "https://api.telegram.org/bot{token}/sendMessage"


def send_message(token: str, chat_id: str, text: str, timeout: int = 15) -> bool:
    """Envia mensagem HTML. Retorna False em falha (não levanta)."""
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
         "disable_web_page_preview": True}
    ).encode("utf-8")
    req = urllib.request.Request(
        API.format(token=token),
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "btc-sauron/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            log.error("Telegram respondeu erro: %s", body)
            return False
        log.info("Mensagem enviada ao Telegram (chat %s)", chat_id)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as e:
        log.error("Falha ao enviar Telegram: %s", e)
        return False
