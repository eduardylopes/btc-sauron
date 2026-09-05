"""Agregador de liquidações long/short do perpétuo BTC via stream público da OKX.

O daemon mantém uma conexão WebSocket (wss://ws.okx.com:443) no canal
`liquidation-orders` (SWAP, BTC-USDT) e acumula os eventos das últimas 24h.
Notional estimado = sz (contratos) × ctVal × bkPx (preço de falência).
Persistência em arquivo separado (sobrevive a restart do container).
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time

from .wsclient import OP_CLOSE, OP_PING, OP_PONG, OP_TEXT, WsConnection

log = logging.getLogger("btcsauron.liquidations")

OKX_HOST = "ws.okx.com"
OKX_PORT = 443
OKX_PATH = "/ws/v5/public"
INST_ID = "BTC-USDT-SWAP"
CTVAL_BTC_SWAP = 0.01  # OKX BTC-USDT-SWAP: 1 contrato = 0.01 BTC
WINDOW_MS = 24 * 3600 * 1000
MAX_EVENTS = 50000
RECONNECT_BASE = 5
RECONNECT_MAX = 300
FRAME_IDLE_LIMIT = 90  # reconecta se nenhum frame em 90s


class LiquidationTracker:
    def __init__(self, state_file: str):
        self.liq_file = os.path.join(os.path.dirname(state_file) or ".", "liquidations.json")
        self.events: list[list] = []  # [ts_ms, pos_side, notional_usd]
        self.lock = threading.Lock()
        self.updated_at: float | None = None
        self.received_count = 0  # total de detalhes de liquidação recebidos (qualquer par)
        self._load()

    # ------------------------------------------------------------------ dados
    def _load(self) -> None:
        try:
            with open(self.liq_file, encoding="utf-8") as f:
                rows = json.load(f)
            now = time.time() * 1000
            self.events = [
                r for r in rows
                if isinstance(r, list) and len(r) == 3
                and now - float(r[0]) <= WINDOW_MS
            ]
            if self.events:
                self.updated_at = time.time()
            log.info("Liquidações carregadas do estado: %d eventos", len(self.events))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            self.events = []

    def persist(self) -> None:
        with self.lock:
            rows = list(self.events)
        try:
            os.makedirs(os.path.dirname(self.liq_file), exist_ok=True)
            tmp = self.liq_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rows, f)
            try:
                os.replace(tmp, self.liq_file)
            except OSError:
                # Windows: o destino pode estar temporariamente travado
                if os.path.exists(self.liq_file):
                    os.remove(self.liq_file)
                os.replace(tmp, self.liq_file)
        except OSError as e:
            log.warning("Não foi possível persistir liquidações: %s", e)

    def add(self, ts_ms: int, pos_side: str, notional_usd: float) -> None:
        with self.lock:
            self.events.append([ts_ms, pos_side, notional_usd])
            if len(self.events) > MAX_EVENTS:
                self.events = self.events[-MAX_EVENTS:]
        self.updated_at = time.time()

    def _prune(self, now_ms: int) -> None:
        cutoff = now_ms - WINDOW_MS
        self.events = [e for e in self.events if e[0] >= cutoff]

    def totals_24h(self) -> dict:
        """Totais das últimas 24h: long/short em USD e contagens."""
        now_ms = time.time() * 1000
        with self.lock:
            self._prune(now_ms)
            long_usd = sum(e[2] for e in self.events if e[1] == "long")
            short_usd = sum(e[2] for e in self.events if e[1] == "short")
            long_n = sum(1 for e in self.events if e[1] == "long")
            short_n = sum(1 for e in self.events if e[1] == "short")
            total = long_usd + short_usd
        return {
            "long_usd": long_usd, "short_usd": short_usd, "total_usd": total,
            "long_count": long_n, "short_count": short_n,
            "updated_at": self.updated_at,
        }

    # ------------------------------------------------------------- websocket
    def _handle_message(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            return
        if msg.get("event") == "subscribe":
            log.info("OKX: assinatura confirmada (%s)", msg.get("arg", {}).get("channel"))
            return
        if msg.get("event") == "error":
            log.warning("OKX: erro no stream: %s", text[:200])
            return
        data = msg.get("data")
        if not isinstance(data, list):
            return
        for item in data:
            if not isinstance(item, dict):
                continue
            inst = item.get("instId")
            for d in item.get("details") or []:
                try:
                    ts = int(d["ts"])
                    sz = float(d["sz"])
                    bk = float(d.get("bkPx") or 0)
                    notional = sz * CTVAL_BTC_SWAP * bk
                    if notional <= 0:
                        continue
                    self.received_count += 1
                    if inst != INST_ID:
                        continue
                    pos = d.get("posSide") or ("long" if d.get("side") == "sell" else "short")
                    self.add(ts, pos, notional)
                except (KeyError, TypeError, ValueError) as e:
                    log.debug("Evento de liquidação ignorado (%s): %s", e, str(d)[:120])

    def run_worker(self, stop_event: threading.Event) -> None:
        """Loop principal: conecta, assina, acumula; reconecta com backoff."""
        backoff = RECONNECT_BASE
        last_persist = time.time()
        while not stop_event.is_set():
            ws = WsConnection(OKX_HOST, OKX_PORT, OKX_PATH, timeout=15)
            try:
                ws.connect()
                log.info("OKX WS conectado (%s)", INST_ID)
                # Sem filtro instFamily: o stream entrega liquidações de todos os
                # SWAPs; o filtro por instId é feito client-side (_handle_message).
                ws.send_text(json.dumps({
                    "op": "subscribe",
                    "args": [{"channel": "liquidation-orders",
                              "instType": "SWAP"}],
                }))
                backoff = RECONNECT_BASE
                last_frame = time.time()
                last_summary = time.time()
                while not stop_event.is_set():
                    try:
                        opcode, payload = ws.recv_frame(timeout=20)
                    except socket.timeout:
                        if time.time() - last_frame > FRAME_IDLE_LIMIT:
                            raise ConnectionError("sem frames do servidor — reconectando")
                    else:
                        last_frame = time.time()
                        if opcode == OP_PING:
                            ws.send_text("pong")
                        elif opcode == OP_PONG:
                            pass
                        elif opcode == OP_CLOSE:
                            log.warning("OKX fechou a conexão")
                            break
                        elif opcode == OP_TEXT:
                            text = payload.decode("utf-8", errors="replace")
                            if text == "ping":
                                # OKX usa ping/pong como mensagens de texto
                                ws.send_text("pong")
                            else:
                                self._handle_message(text)
                    if time.time() - last_persist > 60:
                        self.persist()
                        last_persist = time.time()
                    if time.time() - last_summary > 600:
                        t = self.totals_24h()
                        log.info("Liquidações 24h (BTC): long $%.1fM / short $%.1fM "
                                 "(%d+%d eventos) · recebidos no total: %d",
                                 t["long_usd"] / 1e6, t["short_usd"] / 1e6,
                                 t["long_count"], t["short_count"],
                                 self.received_count)
                        last_summary = time.time()
            except Exception as e:
                log.warning("OKX WS falhou: %s (reconecta em %ds)", e, backoff)
            finally:
                ws.close()
            self.persist()
            last_persist = time.time()
            if stop_event.wait(backoff):
                break
            backoff = min(backoff * 2, RECONNECT_MAX)

