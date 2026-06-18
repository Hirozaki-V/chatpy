# Estratégia de Deploy

O ChatPy é desenhado nativamente para a facilidade de auto-hospedagem (self-hosted), sem fricção.

## Deploy Oficial: Docker Compose
- Existirá um arquivo `docker-compose.yml` que provisionará todo o back-end em uma única instrução de terminal (`docker compose up -d`).
- **Serviços** da Arquitetura:
  - `chatpy-server`: Imagem Python baseada em Alpine (ex: `python:3.11-alpine`) encapsulando o FastAPI e o runner Uvicorn.
  - `postgres` (Opcional): Usado em cenários de alta disponibilidade. O default fallback é mapear o arquivo do SQLite num volume docker.
  - `redis` (Opcional): Preparado na arquitetura para ser o message-broker no futuro para escalar workers múltiplos.

## Deploy em Raspberry Pi
- O servidor é construído ativamente com foco no Raspberry Pi (Modelos 3B, 4 e 5).
- As imagens Docker disponibilizadas suportam arquitetura ARM64.
- O modo padrão (`SQLite + WAL Mode`) otimiza IOPS limitadas de cartões MicroSD, mantendo a performance rápida em hardware minúsculo de 1GB/2GB RAM.

## Tailscale Integrado (VPN Mesh / Zero-Tier)
A filosofia do projeto apoia conexões limpas e eficientes, driblando obstáculos de Carrier-Grade NAT.
1. O administrador roda a infraestrutura e instala o `Tailscale` na VPS/Raspberry Pi.
2. A máquina obtém um "Magic IP" isolado (ex. `100.x.y.z`).
3. O administrador e amigos se conectam rodando seus clientes PySide apontados diretamente para o IP Tailscale.
4. Consequência: Instância 100% oculta da Internet aberta (protegida contra scanners) e sem necessidade de abrir portas (`port-forwarding`) no roteador doméstico.
