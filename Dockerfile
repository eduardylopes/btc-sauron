# btc-sauron — relatório diário de indicadores on-chain do Bitcoin + alertas
# de variação brusca via Telegram. Python puro, sem dependências externas.
FROM python:3.12-alpine

# tzdata: base de fusos para agendar o relatório na hora local (Brasília)
RUN apk add --no-cache tzdata

WORKDIR /app
COPY btcsauron/ /app/btcsauron/

RUN chmod 755 /app \
    && find /app -type f -exec chmod 644 {} + \
    && mkdir -p /data \
    && chown 65534:65534 /data

# Configuração (todas sobrescrevíveis via env)
ENV TELEGRAM_BOT_TOKEN="" \
    TELEGRAM_CHAT_ID="" \
    REPORT_TIME="08:00" \
    REPORT_ON_START="true" \
    ALERT_ENABLED="true" \
    ALERT_INTERVAL_SECONDS="600" \
    ALERT_1H_PCT="3.0" \
    ALERT_4H_PCT="5.0" \
    ALERT_24H_PCT="8.0" \
    ALERT_COOLDOWN_HOURS="6.0" \
    STATE_FILE="/data/state.json" \
    HTTP_TIMEOUT_SECONDS="15" \
    LOG_LEVEL="INFO" \
    TZ="America/Sao_Paulo"

# Roda como usuário sem privilégios
USER 65534:65534

# Daemon padrão: relatório diário + alertas 24/7
CMD ["python", "-m", "btcsauron.main", "run"]
