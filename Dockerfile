# ---------------------------------------------------------------------------
# Dockerfile — ChatPy V2 Server
# Multi-stage build para imagem final menor (ideal para Raspberry Pi)
# ---------------------------------------------------------------------------

# --- Estágio 1: Builder (instala dependências em camada cacheável) ---
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Copia apenas o requirements para cache eficiente de camadas
COPY requirements.txt /build/

# Instala dependências em diretório isolado para_stage final
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Estágio 2: Runtime (imagem final enxuta) ---
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////app/data/chatpy.db \
    UPLOAD_DIR=/app/uploads

# Instala curl para healthcheck e tini para init correto de processos
RUN apt-get update && \
    apt-get install --no-install-recommends -y curl tini && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /app/data /app/uploads

WORKDIR /app

# Copia dependências instaladas no estágio builder
COPY --from=builder /install /usr/local

# Copia apenas os módulos necessários (server e shared)
COPY server/ /app/server/
COPY shared/ /app/shared/

EXPOSE 5000

# Healthcheck: endpoint /health verifica conexão com banco
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fs http://localhost:5000/health || exit 1

# Usa tini como init para tratamento correto de sinais (graceful shutdown)
ENTRYPOINT ["/usr/bin/tini", "--"]

# Executa o servidor via Uvicorn
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "5000"]
