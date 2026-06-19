# MVP — ChatPy V2

O ChatPy V2 começou como um MVP (Produto Mínimo Viável) com estes objetivos:

## Objetivos do MVP

1. **Chat funcional**: salas públicas, DMs, presença
2. **Self-hosted**: roda em qualquer lugar com Docker
3. **Leve**: SQLite, sem dependências externas
4. **Dois clientes**: Desktop (GUI) e CLI (terminal)
5. **Seguro**: Argon2, JWT, rate limiting
6. **Retrô**: visual terminal cibernético

## O que foi além do MVP

Ao longo do desenvolvimento, adicionamos:
- Federação entre servidores (DMs cross-server)
- Modo convidado (anonimato)
- Bots (framework para criar bots)
- Painel admin web
- Métricas Prometheus + Grafana
- Backup automático
- LAN discovery (mDNS)
- E2E scaffold (Signal Protocol)
- Offline sync queue
- Marketplace de temas

## Status atual

Todas as funcionalidades do MVP estão implementadas e testadas. As features adicionais estão em vários níveis de maturidade — algumas prontas para produção, outras como scaffold para desenvolvimento futuro.
