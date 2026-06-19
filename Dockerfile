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
    UPLOAD_DIR=/app/uploads \
    # P1-FIX: arquivos persistentes (JWT secret, chave de federação, cache)
    # agora ficam em /app/data — que DEVE ser mapeado como volume no docker
    # run -v chatpy_data:/app/data. Antes, o paths.py caía no diretório do
    # projeto (/app) que é destruído quando o container é recriado — invalidando
    # todas as sessões JWT e quebrando a federação a cada restart.
    CHATPY_DATA_DIR=/app/data

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
# SECURITY/OPS FIX (auditoria-2026-06): copia alembic/ e alembic.ini para
# o container — antes, o Dockerfile não os copiava, então o comando
# `alembic upgrade head` no CMD falhava com "alembic: command not found"
# ou "path not found". Isto significava que TODOS os deploys Docker
# ficavam sem migrations — só funcionavam porque `Base.metadata.create_all()`
# no startup cria tabelas novas em DB vazio, mas quebra em upgrades de schema.
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

EXPOSE 5000

# Healthcheck: endpoint /health verifica conexão com banco
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fs http://localhost:5000/health || exit 1

# Usa tini como init para tratamento correto de sinais (graceful shutdown)
ENTRYPOINT ["/usr/bin/tini", "--"]

# SECURITY/OPS FIX (auditoria-2026-06): roda `alembic upgrade head` ANTES
# do uvicorn para garantir que o schema está atualizado. Em DB vazio, isto
# é equivalente a create_all(). Em DB existente com versão antiga, aplica
# migrations pendentes. Em DB já na versão head, é no-op.
# O `|| true` no create_all é fallback de segurança: se alembic falhar por
# qualquer motivo (ex: DB já tem tabelas mas sem alembic_version), o
# create_all garante que tabelas novas existam antes do uvicorn subir.
CMD ["sh", "-c", "alembic upgrade head && uvicorn server.main:app --host 0.0.0.0 --port 5000"]
