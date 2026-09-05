"""Cliente WebSocket mínimo (RFC 6455) — apenas stdlib.

Usado para o stream público de liquidações da OKX (wss://ws.okx.com:443).
Funcionalidades: handshake com TLS, frames mascarados do cliente, parse de
frames (texto/binary/ping/pong/close), heartbeat ping/pong.
"""
from __future__ import annotations

import base64
import logging
import os
import socket
import ssl
import struct

log = logging.getLogger("btcsauron.wsclient")

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def build_client_frame(text: str) -> bytes:
    """Frame de texto mascarado (cliente DEVE mascarar segundo RFC 6455)."""
    payload = text.encode("utf-8")
    mask = os.urandom(4)
    n = len(payload)
    if n < 126:
        hdr = bytes([0x81, 0x80 | n])
    elif n < 65536:
        hdr = bytes([0x81, 0x80 | 126]) + struct.pack(">H", n)
    else:
        hdr = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", n)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return hdr + mask + masked


def parse_frame(buf: bytearray) -> tuple[int, bytes, int]:
    """Lê um frame do buffer. Retorna (opcode, payload, bytes_consumidos).

    Levanta ValueError se o buffer estiver incompleto (chamador aguarda mais
    dados). Não desmascara (frames de servidor não são mascarados).
    """
    if len(buf) < 2:
        raise ValueError("frame incompleto")
    b1, b2 = buf[0], buf[1]
    if b2 & 0x80:
        raise ValueError("frame de servidor não pode estar mascarado")
    ln = b2 & 0x7F
    off = 2
    if ln == 126:
        if len(buf) < 4:
            raise ValueError("frame incompleto")
        ln = struct.unpack(">H", buf[2:4])[0]
        off = 4
    elif ln == 127:
        if len(buf) < 10:
            raise ValueError("frame incompleto")
        ln = struct.unpack(">Q", buf[2:10])[0]
        off = 10
    if len(buf) < off + ln:
        raise ValueError("frame incompleto")
    return (b1 & 0x0F), bytes(buf[off:off + ln]), off + ln


class WsConnection:
    """Conexão WebSocket com handshake TLS e helpers de envio/recepção."""

    def __init__(self, host: str, port: int, path: str, timeout: float = 15.0):
        self.host = host
        self.port = port
        self.path = path
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self._buf = bytearray()

    def connect(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        self.sock.settimeout(self.timeout)
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("conexão fechada durante handshake")
            resp += chunk
        head, rest = resp.split(b"\r\n\r\n", 1)
        self._buf = bytearray(rest)
        status = head.split(b"\r\n", 1)[0].decode(errors="replace")
        if b"101" not in status.encode():
            raise ConnectionError(f"handshake falhou: {status}")

    def send_text(self, text: str) -> None:
        if not self.sock:
            raise ConnectionError("socket não conectado")
        self.sock.sendall(build_client_frame(text))

    def recv_frame(self, timeout: float | None = None) -> tuple[int, bytes]:
        """Lê um frame completo. Levanta socket.timeout se sem dados no prazo."""
        if not self.sock:
            raise ConnectionError("socket não conectado")
        if timeout is not None:
            self.sock.settimeout(timeout)
        while True:
            try:
                opcode, payload, consumed = parse_frame(self._buf)
                del self._buf[:consumed]
                return opcode, payload
            except ValueError:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("conexão fechada pelo servidor")
                self._buf.extend(chunk)

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
