"""Comandos do bot via Telegram (long polling em thread separada).

O daemon consome /getUpdates e responde a comandos do usuário:
  /start        → boas-vindas
  /help         → ajuda
  /indicadores  → explicação de cada indicador do relatório
"""
import json
import logging
import threading
import urllib.request

from . import telegram

log = logging.getLogger("btcsauron.commands")

API = "https://api.telegram.org/bot{token}/getUpdates"

WELCOME = (
    "👁️ <b>BTC Sauron</b> — o olho que tudo vê no mercado.\n"
    "Envio o relatório diário de indicadores on-chain às 08:00 e alertas de "
    "variação brusca de preço.\n\n"
    "Comandos:\n"
    "• /indicadores — explicação de cada indicador do relatório\n"
    "• /help — esta ajuda"
)

EXPLANATION = (
    "📖 <b>Indicadores do BTC Sauron</b>\n\n"
    "🔗 <b>On-chain</b>\n"
    "• <b>MVRV</b>: preço de mercado ÷ custo médio de aquisição de todas as "
    "moedas. &gt;3.5 = topo histórico; &lt;1 = abaixo do custo médio (fundo).\n"
    "• <b>MVRV Z-Score</b>: MVRV normalizado (janela de 730 dias). "
    "&gt;7 = topo histórico; &lt;0 = capitulação.\n"
    "• <b>NUPL</b>: lucro não realizado ÷ market cap. Zonas: &lt;0 capitulação · "
    "0–0.25 esperança · 0.25–0.5 otimismo · 0.5–0.75 crença · &gt;0.75 euforia.\n"
    "• <b>Realized Price (est.)</b>: preço médio de aquisição do mercado "
    "(≈ preço ÷ MVRV). Preço abaixo dele = raridade histórica.\n"
    "• <b>Puell Multiple</b>: receita dos mineradores ÷ média de 365 dias. "
    "&lt;0.5 = estresse (fundo); &gt;4 = mineradores superfaturando (topo).\n"
    "• <b>Hash Ribbons</b>: SMA30 ÷ SMA60 do hashrate. &lt;1 = capitulação de "
    "mineradores; &gt;1 = alta.\n\n"
    "📐 <b>Preço vs Médias</b>\n"
    "• <b>Mayer Multiple (200d)</b>: preço ÷ média móvel de 200 dias. "
    "~2.4 = topo histórico; &lt;1 = barato.\n"
    "• <b>MM200 (200 semanas)</b>: média de 200 semanas — suporte macro de "
    "longo prazo.\n"
    "• <b>Pi Cycle Top</b>: cruzamento de 2×MA111 com MA350 — historicamente "
    "marca topos de ciclo.\n\n"
    "💥 <b>Liquidações (24h)</b>: posições long/short liquidadas à força (US$) "
    "na OKX. Picos = excesso de alavancagem e possíveis reversões.\n\n"
    "💵 <b>ETFs spot</b>: fluxo líquido diário (entrada/saída) dos ETFs de BTC "
    "nos EUA. Entradas sustentadas = demanda institucional.\n\n"
    "🔎 <b>Google Trends</b>: interesse de busca por \"bitcoin\" (0–100). "
    "Extremos = euforia ou pânico popular.\n\n"
    "😱 <b>Fear &amp; Greed</b>: sentimento 0–100. 0–25 medo extremo "
    "(oportunidade); 75–100 ganância extrema (cautela).\n\n"
    "Fontes: Coin Metrics · Binance · OKX · ETF Flow · Google Trends · "
    "Alternative.me (gratuitas)"
)


def handle_command(text: str) -> str | None:
    """Retorna a resposta para um comando do Telegram (None se não for comando)."""
    text = (text or "").strip()
    if not text:
        return None
    cmd = text.split()[0].lower().split("@")[0]
    if cmd == "/start":
        return WELCOME
    if cmd in ("/help", "/indicadores", "/indicators", "/indicador"):
        return EXPLANATION
    if cmd.startswith("/"):
        return "Comando desconhecido. Use /indicadores ou /help."
    return None


def _fetch_updates(cfg, offset: int) -> dict:
    url = f"{API.format(token=cfg.telegram_bot_token)}?offset={offset}&timeout=25"
    req = urllib.request.Request(url, headers={"User-Agent": "btc-sauron/1.1"})
    with urllib.request.urlopen(req, timeout=cfg.http_timeout + 30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_telegram_commands(cfg, state: dict, save_state, stop_event: threading.Event) -> None:
    """Thread: long polling no Telegram e respostas a comandos."""
    if not cfg.telegram_configured:
        log.info("Comandos do bot desativados (TELEGRAM_BOT_TOKEN/CHAT_ID ausentes)")
        return
    offset = int(state.get("telegram_offset") or 0)
    log.info("Comandos do bot ativos (offset inicial %d)", offset)
    while not stop_event.is_set():
        try:
            data = _fetch_updates(cfg, offset)
            if not data.get("ok"):
                log.warning("getUpdates respondeu erro: %s", data)
                stop_event.wait(10)
                continue
            for u in data.get("result", []):
                offset = max(offset, int(u.get("update_id", 0)) + 1)
                msg = u.get("message") or {}
                text = (msg.get("text") or "").strip()
                cid = msg.get("chat", {}).get("id")
                if not text or cid is None:
                    continue
                reply = handle_command(text)
                if reply:
                    telegram.send_message(cfg.telegram_bot_token, str(cid),
                                          reply, cfg.http_timeout)
            if offset != state.get("telegram_offset"):
                state["telegram_offset"] = offset
                save_state()
        except Exception as e:
            log.warning("getUpdates falhou: %s", e)
            stop_event.wait(10)

