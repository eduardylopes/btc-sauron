"""Cálculo dos indicadores a partir do histórico diário da Coin Metrics.

Fórmulas (todas derivadas localmente; fontes gratuitas, sem chave):
- MVRV              = CapMVRVCur (direto da Coin Metrics)
- NUPL              = (MC - RC) / MC = 1 - 1/MVRV   (exato, pois MVRV = MC/RC)
- Realized Price    = RC / supply ≈ PriceUSD / MVRV  (estimado)
- MVRV Z-Score      = (MC - RC) / desvio padrão(MC) em janela de 730d
                      (mesma fórmula do LookIntoBitcoin; RC = MC/MVRV)
- Mayer Multiple    = PriceUSD / SMA200(PriceUSD)
- MM200 (200W MA)   = PriceUSD / SMA1400(PriceUSD)  (média de 200 semanas)
- Pi Cycle Top      = PriceUSD vs 2*SMA111 e SMA350 (sinal clássico de topo)
- Puell Multiple    = receita minerador USD / SMA365(receita USD)
                      receita = (IssTotNtv + FeeTotNtv) * PriceUSD
- Hash Ribbons      = SMA30(HashRate) / SMA60(HashRate)
"""
from __future__ import annotations

import statistics
from typing import Sequence


def sma(values: Sequence[float | None], window: int) -> list[float | None]:
    """Média móvel simples sobre valores possivelmente None (ignorados)."""
    out: list[float | None] = []
    acc: list[float] = []
    for v in values:
        if v is not None:
            acc.append(v)
            if len(acc) > window:
                acc.pop(0)
        out.append(sum(acc) / len(acc) if acc else None)
    return out


def stddev_trailing(values: Sequence[float | None], window: int) -> list[float | None]:
    """Desvio padrão populacional em janela deslizante."""
    out: list[float | None] = []
    acc: list[float] = []
    for v in values:
        if v is not None:
            acc.append(v)
            if len(acc) > window:
                acc.pop(0)
        out.append(statistics.pstdev(acc) if len(acc) >= 2 else None)
    return out


def _latest(series: Sequence[float | None]) -> float:
    for v in reversed(series):
        if v is not None:
            return v
    raise ValueError("série sem valores válidos")


def _pair(price: Sequence[float | None], rc: Sequence[float | None], mc: Sequence[float | None]) -> None:
    """Validação: séries devem ter o mesmo comprimento."""
    assert len(price) == len(rc) == len(mc)


def compute_indicators(daily: dict) -> dict:
    """daily: saída de sources.fetch_coinmetrics_daily()."""
    t = daily["time"]
    price = daily["PriceUSD"]
    mc = daily["CapMrktCurUSD"]
    mvrv_raw = daily["CapMVRVCur"]
    supply = daily["SplyCur"]
    hash_rate = daily["HashRate"]
    issued = daily["IssTotNtv"]
    fees = daily["FeeTotNtv"]

    # Índice da última linha COMPLETA (a Coin Metrics adiciona um ponto parcial
    # do dia atual no fim da série — usar só dias finalizados evita "—").
    core = [mc, mvrv_raw, supply, issued, fees]
    idx = len(t) - 1
    for i in range(len(t) - 1, -1, -1):
        if all(s[i] is not None for s in core):
            idx = i
            break

    # MVRV e derivados (RC = MC / MVRV) — no dia completo
    mvrv = mvrv_raw[idx]
    rc = [ (m / r) if (m is not None and r) else None for m, r in zip(mc, mvrv_raw) ]
    _pair(price, rc, mc)

    z = stddev_trailing(mc, 730)
    mvrv_z = [ ((m - r) / s) if (m is not None and r is not None and s) else None
               for m, r, s in zip(mc, rc, z) ]

    # Médias móveis de preço
    ma111 = sma(price, 111)
    ma350 = sma(price, 350)
    ma200 = sma(price, 200)
    ma1400 = sma(price, 1400)

    # Puell: receita do minerador em USD
    revenue_usd = [ (i + f) * px if (i is not None and f is not None and px is not None) else None
                    for i, f, px in zip(issued, fees, price) ]
    rev_ma365 = sma(revenue_usd, 365)
    puell = [ (rv / ma) if (rv is not None and ma) else None
              for rv, ma in zip(revenue_usd, rev_ma365) ]

    # Hash ribbons
    hr30 = sma(hash_rate, 30)
    hr60 = sma(hash_rate, 60)
    ribbons = [ (a / b) if (a is not None and b) else None
                for a, b in zip(hr30, hr60) ]

    p = price[idx]

    def _at(series, i=idx, default=None):
        v = series[i] if 0 <= i < len(series) else None
        return v if v is not None else default

    def _ratio(numerator, base):
        b = _at(base)
        return (numerator / b) if (b is not None and b) else None

    return {
        "date": t[idx],
        "price": p,
        "market_cap": _at(mc),
        "supply": _at(supply),
        "mvrv": mvrv,
        "nupl": 1.0 - 1.0 / mvrv,
        "realized_price_est": p / mvrv,
        "mvrv_z": _at(mvrv_z),
        "mayer": _ratio(p, ma200),
        "mm200_ratio": _ratio(p, ma1400),
        "mm200_value": _at(ma1400),
        "ma111": _at(ma111),
        "ma350": _at(ma350),
        "pi_cycle_2x111": _ratio(2.0, ma111) if _at(ma111) else None,
        "pi_cycle_signal": (
            _at(ma111) is not None and _at(ma350) is not None
            and 2.0 * _at(ma111) > _at(ma350)
        ),
        "puell": _at(puell),
        "hash_ribbons_ratio": _at(ribbons),
        "hash_ribbons_bull": _at(ribbons) is not None and _at(ribbons) > 1.0,
        "hashrate": _at(hash_rate),
        "active_addresses": _at(daily["AdrActCnt"]),
        "tx_count": _at(daily["TxCnt"]),
    }


def nupl_label(nupl: float) -> str:
    """Zonas clássicas do NUPL."""
    if nupl < 0:
        return "Capitulação"
    if nupl < 0.25:
        return "Esperança"
    if nupl < 0.50:
        return "Otimismo"
    if nupl < 0.75:
        return "Crença"
    return "Euforia"


def mvrv_z_label(z: float) -> str:
    if z < 0:
        return "fundo histórico"
    if z < 2:
        return "neutro"
    if z < 4:
        return "elevado"
    return "zona de topo"


def puell_label(v: float) -> str:
    if v < 0.5:
        return "estresse de mineradores (fundo)"
    if v > 4:
        return "mineradores superfaturando (topo)"
    return "neutro"
