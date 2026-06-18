# Visão Geral da Arquitetura do ChatPy

## 1. Princípios de Design
O ChatPy adota uma abordagem **API-First**, na qual o servidor é a única fonte da verdade e de lógica de negócios. Todos os clientes (Desktop e CLI) são estritamente consumidores dessa API.

### Princípios:
- **Desacoplamento Rigoroso**: Separação clara entre a lógica de servidor (FastAPI + WebSockets) e os clientes (PySide6 / Rich).
- **Event-Driven**: Comunicação assíncrona orientada a eventos via WebSocket, essencial para chats em tempo real.
- **Leveza e Performance**: Construído para rodar eficientemente tanto em servidores VPS robustos quanto em dispositivos limitados como Raspberry Pi 3B/4/5.
- **Proibido Webviews**: A interface do usuário não utilizará tecnologias web embarcadas (como Electron ou PyWebView). Os clientes utilizarão bibliotecas nativas (Qt) ou de terminal.

## 2. Componentes Principais
- **Servidor Backend**: Desenvolvido em Python com FastAPI, lidando com o ciclo de vida do WebSocket, banco de dados (SQLite/PostgreSQL) e regras de negócios.
- **Cliente Desktop (GUI)**: Interface real nativa construída com PySide6 (Qt para Python). Temática retrô inspirada no MSN e IRC.
- **Cliente Terminal (CLI)**: Interface baseada em texto usando `Rich` e `Typer`, com total paridade de recursos da GUI.
- **Shared (Camada Compartilhada)**: Um pacote/módulo compartilhado entre servidor e clientes com a definição do protocolo, estruturas de dados (Pydantic models) e tipos.
