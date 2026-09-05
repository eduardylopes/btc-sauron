"""Fontes de dados gratuitas (sem API key):

- Coin Metrics Community API: on-chain (MVRV, market cap, price, supply, hashrate,
  fees, emissão, endereços ativos). Sem chave, 10 req/6s por IP, uso não comercial.
- Binance Public API: preço spot, candles e funding rate (sem chave).
- Alternative.me: Fear & Greed Index (sem chave).
"""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("btcsauron.sources")

CM_BASE = "https://community-api.coinmetrics.io/v4"
BINANCE_BASE = "https://api.binance.com"
BINANCE_FAPI_BASE = "https://fapi.binance.com"
FNG_URL = "https://api.alternative.me/fng/"

# Métricas community confirmadas disponíveis (testado 2025):
CM_METRICS = (
    "CapMrktCurUSD,CapMVRVCur,PriceUSD,SplyCur,HashRate,FeeTotNtv,"
    "IssTotNtv,AdrActCnt,TxCnt,BlkCnt"
)


def _get_json(url: str, timeout: int, retries: int = 3) -> dict | list:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "btc-sauron/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as e:
            last_err = e
            log.warning("GET %s falhou (tentativa %d/%d): %s", url.split("?")[0], attempt + 1, retries, e)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Falha ao buscar {url.split('?')[0]}: {last_err}")


# ---------------------------------------------------------------------------
# Coin Metrics Community
# ---------------------------------------------------------------------------

def fetch_coinmetrics_daily(timeout: int = 15) -> dict:
    """Baixa histórico diário completo do BTC (2010→hoje) das métricas community.

    Retorna {metric: [valor ou None por dia], "time": [datas]}.
    Campos ausentes (métricas que não existiam na época) viram None.
    """
    url = (
        f"{CM_BASE}/timeseries/asset-metrics?assets=btc&metrics={CM_METRICS}"
        f"&frequency=1d&start_time=2010-07-18&page_size=10000"
    )
    series: dict[str, list] = {"time": []}
    for m in CM_METRICS.split(","):
        series[m] = []

    next_url: str | None = url
    while next_url:
        data = _get_json(next_url, timeout)
        points = data.get("data", [])
        if not points:
            break
        for p in points:
            series["time"].append(p["time"][:10])
            for m in CM_METRICS.split(","):
                raw = p.get(m)
                series[m].append(float(raw) if raw is not None else None)
        next_url = data.get("next_page_url")
    if not series["time"]:
        raise RuntimeError("Coin Metrics retornou vazio")
    log.info("Coin Metrics: %d pontos diários (%s → %s)",
             len(series["time"]), series["time"][0], series["time"][-1])
    return series


# ---------------------------------------------------------------------------
# Binance
# ---------------------------------------------------------------------------

def fetch_binance_ticker(timeout: int = 15) -> dict:
    """Ticker 24h BTCUSDT: preço atual, variação %, volume."""
    data = _get_json(f"{BINANCE_BASE}/api/v3/ticker/24hr?symbol=BTCUSDT", timeout)
    return {
        "price": float(data["lastPrice"]),
        "change_24h_pct": float(data["priceChangePercent"]),
        "volume_24h_btc": float(data["volume"]),
        "quote_volume_24h_usd": float(data["quoteVolume"]),
        "high_24h": float(data["highPrice"]),
        "low_24h": float(data["lowPrice"]),
    }


def fetch_binance_klines(interval: str = "1h", limit: int = 25, timeout: int = 15) -> list[dict]:
    """Candles BTCUSDT. Cada item: {time, open, high, low, close}."""
    url = f"{BINANCE_BASE}/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
    rows = _get_json(url, timeout)
    return [
        {
            "time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
        }
        for r in rows
    ]


def fetch_binance_funding(timeout: int = 15) -> float | None:
    """Funding rate atual do futuro perpétuo BTCUSDT (fapi)."""
    try:
        data = _get_json(f"{BINANCE_FAPI_BASE}/fapi/v1/premiumIndex?symbol=BTCUSDT", timeout)
        return float(data.get("lastFundingRate"))
    except Exception as e:  # funding é opcional
        log.warning("Funding rate indisponível: %s", e)
        return None


# ---------------------------------------------------------------------------
# Alternative.me — Fear & Greed
# ---------------------------------------------------------------------------

def fetch_fear_greed(timeout: int = 15) -> dict | None:
    try:
        data = _get_json(f"{FNG_URL}?limit=1", timeout)
        row = data["data"][0]
        return {"value": int(row["value"]), "classification": row["value_classification"]}
    except Exception as e:
        log.warning("Fear & Greed indisponível: %s", e)
        return None


# ---------------------------------------------------------------------------
# ETF Flow (Supabase) — fluxo líquido diário dos ETFs spot de BTC
# ---------------------------------------------------------------------------

ETF_FLOW_URL = "https://ubzimdhjaqeirdhhwzug.supabase.co/functions/v1/smooth-handler"


def fetch_etf_flows(timeout: int = 15) -> list[dict]:
    """Fluxo líquido diário (USD) dos ETFs spot de BTC, últimos 3 dias.

    Fonte: ETF Flow (terceiro, preview gratuito sem chave — 3 registros,
    1 dia de atraso; dados consolidados dos emissores após o fechamento EUA).
    """
    try:
        data = _get_json(f"{ETF_FLOW_URL}?ticker=BTC&limit=3", timeout)
        return [
            {"date": r["flow_date"], "net_usd": float(r["net_flow_usd"])}
            for r in data.get("data", [])
        ]
    except Exception as e:
        log.warning("ETF flows indisponível: %s", e)
        return []


# ---------------------------------------------------------------------------
# Google Trends — interesse em "bitcoin" (90 dias)
# ---------------------------------------------------------------------------

_TRENDS_OPENER = None  # opener com cookie jar (criado sob demanda)
_TRENDS_HOME = "https://trends.google.com/trends/explore?q=bitcoin"


def _trends_get_text(url: str, timeout: int, referer: str = "https://trends.google.com/") -> str:
    """GET com cookie jar e headers de navegador (Google Trends exige)."""
    global _TRENDS_OPENER
    if _TRENDS_OPENER is None:
        import http.cookiejar
        jar = http.cookiejar.CookieJar()
        _TRENDS_OPENER = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Referer": referer,
    })
    with _TRENDS_OPENER.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _trends_warm(timeout: int) -> None:
    """Cookie warming: visita google.com e a home do Trends antes da API.

    Sem isso o Google responde 429 (Too Many Requests) — o IP precisa dos
    cookies de consentimento (NID/SOCS) antes de chamar os endpoints da API.
    """
    _trends_get_text("https://www.google.com/", timeout)
    _trends_get_text(_TRENDS_HOME, timeout)


def fetch_google_trends(timeout: int = 15) -> dict | None:
    """Interesse do Google Trends para 'bitcoin' (últimos 90 dias).

    Retorna {"value": 0-100, "delta_7d": %} ou None (429/erro → degradação).
    Fluxo não-oficial (warm → explore → widget TIMESERIES → multiline), como o
    pytrends — o warming com cookies é o que evita o 429.
    """
    try:
        import urllib.parse as up
        _trends_warm(timeout)
        payload = {
            "comparisonItem": [{"keyword": "bitcoin", "geo": "", "time": "today 3-m"}],
            "category": 0, "property": "",
        }
        url = ("https://trends.google.com/trends/api/explore"
               f"?hl=en-US&tz=-180&req={up.quote(json.dumps(payload))}")
        body = _trends_get_text(url, timeout, referer=_TRENDS_HOME)
        if body.lstrip().startswith("<"):
            log.warning("Google Trends bloqueado (resposta HTML, provável 429)")
            return None
        data = json.loads(body[body.index("{") :])  # remove prefixo ")]}',"
        widget = next(w for w in data["widgets"] if w["id"] == "TIMESERIES")
        req2 = up.quote(json.dumps(widget["request"]))
        url2 = ("https://trends.google.com/trends/api/widgetdata/multiline"
                f"?hl=en-US&tz=-180&req={req2}&token={up.quote(widget['token'])}")
        body2 = _trends_get_text(url2, timeout, referer=_TRENDS_HOME)
        if body2.lstrip().startswith("<"):
            log.warning("Google Trends bloqueado no multiline")
            return None
        data2 = json.loads(body2[body2.index("{") :])
        rows = data2["default"]["timelineData"]
        if not rows:
            return None
        latest = rows[-1]["value"][0]
        delta = None
        if len(rows) >= 8:
            prev = rows[-8]["value"][0]
            if prev:
                delta = (latest - prev) / prev * 100
        return {"value": latest, "delta_7d": delta}
    except Exception as e:
        log.warning("Google Trends indisponível: %s", e)
        return None
