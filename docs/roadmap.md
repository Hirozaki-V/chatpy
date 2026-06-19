# Roadmap do ChatPy V2

## ✅ Concluído

### Estabilidade
- [x] Docker compose funcional
- [x] Testes corrigidos (54/54 passando)
- [x] Logout autenticado
- [x] XSS e path traversal corrigidos no Desktop
- [x] Memory leak e segfault corrigidos
- [x] Anti brute-force persistente (SQLite)
- [x] Rate limit REST + WebSocket configurável
- [x] Limites para usuários guest
- [x] Healthcheck multi-componente
- [x] Backup automático SQLite

### Qualidade
- [x] Tab-completion de @nick e #sala
- [x] Badges de não-lidas por aba
- [x] Indicador "digitando..." em tempo real
- [x] Refatoração do main_window.py (diálogos extraídos)
- [x] Helper de threading unificado (QThreadPool)
- [x] Diálogos redimensionáveis
- [x] Testes para clientes (54 testes)
- [x] CI/CD com GitHub Actions
- [x] Logging estruturado JSON
- [x] Auto-away por ociosidade

### Visão de longo prazo
- [x] Federação MVP (DMs cross-server, assinatura Ed25519)
- [x] Modo convidado (anonimato)
- [x] Empacotamento Desktop (PyInstaller spec)
- [x] CLI Unix com input não-bloqueante (prompt_toolkit)
- [x] Métricas Prometheus
- [x] Design doc E2E (Signal Protocol)
- [x] Design doc Web client

### Features adicionais
- [x] Sync de presença federada
- [x] LAN discovery via mDNS
- [x] Framework de bots
- [x] Painel admin web
- [x] E2E scaffold (schema de chaves + endpoints)
- [x] Salas federadas (schema)
- [x] Offline sync queue
- [x] Auto-update do cliente
- [x] Marketplace de temas
- [x] Guia Postgres
- [x] Schema migration com Alembic
- [x] Tema light na CLI
- [x] Admin de peers federados (UI Desktop + REST)

## 🔲 Futuro

### Prioridade alta
- [ ] E2E encryption real (Double Ratchet no cliente)
- [ ] Empacotar Desktop em .exe/.dmg e publicar release
- [ ] Web client (Next.js + PWA)
- [ ] Salas federadas completas (sync de mensagens)

### Prioridade média
- [ ] Mobile (React Native ou Flutter)
- [ ] Sync de presença federada (já tem scaffold, falta entregar via WS)
- [ ] Painel admin com mais features (gerenciar usuários, banir, etc.)
- [ ] Voice/video (WebRTC)

### Prioridade baixa
- [ ] DNS SRV para descoberta automática de peers
- [ ] Marketplace de temas (comunidade)
- [ ] Integração com IRC (bridge)
- [ ] Multi-device (mesma conta em vários dispositivos)
