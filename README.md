# btc-sauron

Relatório diário dos principais indicadores on-chain do Bitcoin + alertas de
variação brusca de preço, entregues via **Telegram**. 100% gratuito — usa
apenas APIs públicas **sem API key** (uso não comercial, conforme termos da
Coin Metrics Community).

## Indicadores

| Indicador | Fonte | Cálculo |
|---|---|---|
| Preço, market cap, supply | Coin Metrics Community | direto |
| MVRV | Coin Metrics `CapMVRVCur` | direto |
| NUPL | derivado | `1 − 1/MVRV` (exato) |
| MVRV Z-Score | derivado | `(MC − RC) / σ₇₃₀(MC)`, RC = MC/MVRV |
| Realized Price (est.) | derivado | `Price / MVRV` |
| Mayer Multiple (200d) | derivado | `Price / SMA200` |
| MM200 (200 semanas) | derivado | `Price / SMA1400` |
| Pi Cycle Top | derivado | `Price` vs `2×SMA111` e `SMA350` |
| Puell Multiple | derivado | `(IssTotNtv + FeeTotNtv) × Price` / `SMA365` |
| Hash Ribbons | derivado | `SMA30 / SMA60` do hashrate |
| Movimentos 1h/4h/24h | Binance klines | direto |
| **Liquidações long/short (24h, USD)** | **OKX WS público** | agregado em tempo real (notional est. via preço de falência) |
| Fluxo líquido ETFs spot (USD/dia) | ETF Flow (Supabase) | direto (grátis, 1 dia de atraso) |
| Google Trends "bitcoin" (90d) | Google Trends (não-oficial) | direto (degrade se 429) |
| Fear & Greed | Alternative.me | direto |

> Nota: a API community da Coin Metrics **não** expõe realized cap, então
> `RC = MC/MVRV` e o Z-Score usam janela de 730 dias (mesma fórmula do
> LookIntoBitcoin). Métricas proprietárias da Glassnode (SOPR, HODL Waves,
> Reserve Risk) não estão incluídas — possíveis follow-ups via BGeometrics.

### Limitações conhecidas (fontes gratuitas)

- **Liquidações (24h)**: vêm do **stream público da OKX** (`wss://ws.okx.com:443`,
  canal `liquidation-orders`), acumuladas pelo daemon em janela de 24h com
  notional estimado (`sz × ctVal × preço de falência`). Só cobre a OKX e, em
  mercado calmo, o BTC pode ter poucos eventos — a janela enche conforme o
  tempo passa. (Binance não expõe isso grátis; Coinglass é pago.)
- **Google Trends**: o IP do homelab recebeu `429` do Google durante o setup —
  o bot tenta a cada relatório e mostra "indisponível" quando bloqueado.
- **ETFs**: preview gratuito entrega os últimos 3 dias com **1 dia de atraso**
  (dados consolidados após o fechamento dos EUA).

## Como usar

1. **Crie o bot no Telegram**: fale com o [@BotFather](https://t.me/BotFather),
   use `/newbot`, copie o token.
2. **Descubra seu chat_id**: envie uma mensagem ao bot e consulte
   `https://api.telegram.org/bot<TOKEN>/getUpdates` (campo `chat.id`).
3. **Crie o `.env`** (nunca versionado — está no `.gitignore`) a partir do
   `.env.example` e preencha o token e o chat_id:

```bash
cp .env.example .env
# edite .env com TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
chmod 600 .env
```

4. Rode em Docker:

```bash
docker compose up -d --build
```

ou no **Portainer**: *Stacks → + Add stack* com o conteúdo de `compose.yaml`
(aponta para `/opt/btc-sauron` no host).

## Estrutura

O app mantém as regras de negócio independentes das integrações externas:

| Parte | Responsabilidade |
|---|---|
| `btcsauron/domain.py` | Decide quais movimentos de preço viram alertas. |
| `btcsauron/schedule.py` | Calcula a próxima execução diária no fuso configurado. |
| `btcsauron/main.py` | Expõe os comandos públicos `run`, `report` e `check`. |
| `btcsauron/sources.py`, `telegram.py`, `wsclient.py` | Adaptadores para APIs de mercado, Telegram e WebSocket. |

As regras de alertas e agendamento são testadas sem rede, Docker ou Telegram.

### Modos

```bash
python -m btcsauron.main run      # daemon (padrão): relatório diário + alertas + comandos
python -m btcsauron.main report   # relatório único (teste)
python -m btcsauron.main check    # verificação única de alertas (teste)
```

### Comandos do bot no Telegram

Mande mensagens para o bot no Telegram:

| Comando | O que faz |
|---|---|
| `/indicadores` | explica cada indicador do relatório (on-chain, médias, liquidações, ETFs, sentimentos) |
| `/help` | mesma explicação |
| `/start` | boas-vindas e lista de comandos |

### Configuração (env)

| Variável | Padrão | Descrição |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | — (via `.env`) | obrigatórios p/ notificar |
| `REPORT_TIME` | `08:00` | hora do relatório diário (TZ local) |
| `REPORT_ON_START` | `true` | envia relatório ao iniciar o container |
| `ALERT_ENABLED` | `true` | liga/desliga alertas de variação |
| `ALERT_INTERVAL_SECONDS` | `600` | intervalo do polling de preço |
| `ALERT_1H_PCT` / `ALERT_4H_PCT` / `ALERT_24H_PCT` | `3` / `5` / `8` | thresholds % |
| `ALERT_COOLDOWN_HOURS` | `6` | silêncio entre alertas da mesma janela |
| `STATE_FILE` | `/data/state.json` | estado (último relatório, cooldowns) |
| `TZ` | `America/Sao_Paulo` | fuso para agendamento |

Segredos (`TELEGRAM_*`) entram pelo `env_file: .env` do compose; sem eles o app
roda normalmente e loga o relatório no console (útil para testes).

## Testes

```bash
python -m unittest discover -s tests -v
```

## Fontes (gratuitas, sem chave)

- **Coin Metrics Community API** — `community-api.coinmetrics.io` (10 req/6s/IP)
- **Binance Public API** — spot ticker/klines
- **OKX WebSocket** — stream público `liquidation-orders` (liquidações 24h)
- **ETF Flow** — endpoint Supabase (3 registros, 1 dia de atraso)
- **Google Trends** — endpoint não-oficial (sujeito a 429)
- **Alternative.me** — Fear & Greed
