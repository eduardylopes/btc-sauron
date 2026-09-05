"""Montagem do relatório diário em texto HTML para o Telegram."""
import html
from datetime import datetime

from .indicators import mvrv_z_label, nupl_label, puell_label


def _fmt_usd(v: float | None, decimals: int = 0) -> str:
    if v is None:
        return "—"
    return f"${v:,.{decimals}f}"


def _fmt_pct(v: float | None, sign: bool = False) -> str:
    if v is None:
        return "—"
    s = f"{v:+.2f}%" if sign else f"{v:.2f}%"
    return s


def _fmt_num(v: float | None, decimals: int = 0) -> str:
    if v is None:
        return "—"
    return f"{v:,.{decimals}f}"


def colorize_pct(v: float | None, decimals: int = 2) -> str:
    """Percentual com emoji de cor: 🟢 positivo, 🔴 negativo, ⚪ neutro.

    (Telegram não suporta cor de texto — emojis são o padrão dos bots.)
    """
    if v is None:
        return "—"
    dot = "🟢" if v > 0 else ("🔴" if v < 0 else "⚪")
    return f"{dot} {v:+.{decimals}f}%"


def build_report(ind: dict, market: dict, fng: dict | None, now: datetime,
                 extra: dict | None = None) -> str:
    """ind: compute_indicators(); market: {price, change_24h_pct, moves_1h, moves_4h, funding, ...}
    extra (opcional): {long_short, etf, trends} das novas fontes."""
    extra = extra or {}
    p = market.get("price") or ind.get("price")
    chg = market.get("change_24h_pct")
    m1 = market.get("move_1h")
    m4 = market.get("move_4h")

    nupl = ind.get("nupl")
    nupl_txt = f"{nupl:.3f} ({nupl_label(nupl)})" if nupl is not None else "—"

    mvrv_z = ind.get("mvrv_z")
    z_txt = f"{mvrv_z:.2f} ({mvrv_z_label(mvrv_z)})" if mvrv_z is not None else "—"

    mm200 = ind.get("mm200_value")
    mm200_ratio = ind.get("mm200_ratio")
    mm200_txt = "—"
    if mm200 is not None:
        base = f"{_fmt_usd(mm200)}"
        mm200_txt = base + (f" ({(mm200_ratio - 1) * 100:+.0f}% vs)" if mm200_ratio is not None else "")

    pi = "—"
    if ind.get("ma350"):
        above = ind.get("price", 0) / ind["ma350"]
        pi = f"{_fmt_usd(ind['ma350'])} (preço {above * 100:.0f}% da MA350)"
        if ind.get("pi_cycle_signal"):
            pi += " · ⚠️ 2×MA111 cruzou MA350 (zona de topo)"

    ribbons = ind.get("hash_ribbons_ratio")
    ribbons_txt = f"{ribbons:.3f} (capitulação)" if (ribbons is not None and not ind.get("hash_ribbons_bull")) else (
        f"{ribbons:.3f} (alta)" if ribbons is not None else "—")

    puell = ind.get("puell")
    puell_txt = f"{puell:.2f} ({puell_label(puell)})" if puell is not None else "—"

    fng_txt = "—"
    if fng:
        # classification vem de API externa — escapar antes de inserir em HTML
        fng_txt = f"{fng['value']} ({html.escape(str(fng['classification']))})"

    # --- Liquidações (24h) ---
    liq = extra.get("liquidations") or {}
    if liq.get("total_usd"):
        liq_txt = (f"Long {_fmt_usd(liq['long_usd'] / 1e6, 1)}M · "
                   f"Short {_fmt_usd(liq['short_usd'] / 1e6, 1)}M · "
                   f"Total {_fmt_usd(liq['total_usd'] / 1e6, 1)}M")
        liq_n = liq.get("long_count", 0) + liq.get("short_count", 0)
        liq_extra = f" ({liq_n} eventos)"
    else:
        liq_txt = "sem dados ainda (acumulando em tempo real)"
        liq_extra = ""

    # --- ETFs ---
    etf_lines: list[str] = []
    etf = extra.get("etf") or []
    for r in etf:
        d = r["date"][5:]  # MM-DD
        v = r["net_usd"]
        dot = "🟢" if v > 0 else ("🔴" if v < 0 else "⚪")
        etf_lines.append(f"{d}: {dot} {v / 1e6:+,.1f}M")
    etf_txt = " · ".join(etf_lines) if etf_lines else "indisponível"

    # --- Google Trends ---
    tr = extra.get("trends")
    if tr:
        delta = tr.get("delta_7d")
        delta_txt = f" · 7d: {delta:+.0f}%" if delta is not None else ""
        trends_txt = f"{tr['value']}/100{delta_txt}"
    else:
        trends_txt = "indisponível"

    emoji_price = "📈" if (chg or 0) >= 0 else "📉"

    lines = [
        f"📊 <b>BTC — Relatório Diário</b> — {now:%d/%m/%Y %H:%M}",
        "",
        f"{emoji_price} <b>Preço:</b> {_fmt_usd(p, 2)}  ({colorize_pct(chg)} 24h)",
        f"💹 <b>Movimentos:</b> 1h {colorize_pct(m1)} · 4h {colorize_pct(m4)}",
        f"🏦 <b>Market Cap:</b> {_fmt_usd(ind.get('market_cap'))}",
        "",
        "🔗 <b>On-chain</b>",
        f"• MVRV: <b>{ind.get('mvrv', 0):.2f}</b>",
        f"• MVRV Z-Score: <b>{z_txt}</b>",
        f"• NUPL: <b>{nupl_txt}</b>",
        f"• Realized Price (est.): {_fmt_usd(ind.get('realized_price_est'), 0)}",
        f"• Puell Multiple: <b>{puell_txt}</b>",
        f"• Hash Ribbons: <b>{ribbons_txt}</b>",
        f"• Endereços ativos (24h): {_fmt_num(ind.get('active_addresses'))}",
        "",
        "📐 <b>Preço vs Médias</b>",
        f"• Mayer Multiple (200d): <b>{ind.get('mayer', 0):.2f}</b>",
        f"• 200W MA (MM200): {mm200_txt}",
        f"• Pi Cycle Top: {pi}",
        "",
        "💥 <b>Liquidações (24h) — OKX perpétuo BTC</b>",
        f"• <b>{liq_txt}</b>{liq_extra}",
        "",
        "💵 <b>ETFs spot BTC (fluxo líquido/dia)</b>",
        f"• {etf_txt}",
        "ℹ️ 1 dia de atraso · fonte: ETF Flow",
        "",
        "🔎 <b>Google Trends \"bitcoin\" (90d)</b>",
        f"• Interesse: <b>{trends_txt}</b>",
        "",
        "😱 <b>Sentimento</b>",
        f"• Fear & Greed: <b>{fng_txt}</b>",
        "",
        "ℹ️ Fontes: Coin Metrics · Binance · OKX · ETF Flow · Google Trends · Alternative.me (gratuitas)",
    ]
    return "\n".join(lines)
