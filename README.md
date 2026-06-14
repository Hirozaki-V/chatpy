# ChatPy 💬🐍

O **ChatPy** é um sistema de bate-papo moderno, assíncrono e multiplataforma desenvolvido em Python. Ele combina a robustez e a escalabilidade de conexões **WebSockets assíncronas** (`asyncio` + `websockets`) com uma interface gráfica super leve baseada em **PyWebView** (HTML/CSS/JS locais) que emula com fidelidade o design clássico do **mIRC** e **Windows 98** dos anos 2000, além de oferecer um cliente de terminal (**CLI**) alternativo de ultra-baixo consumo de recursos.

Adequado para ser hospedado offline em redes locais ou dispositivos embarcados limitados (como o Raspberry Pi), o ChatPy funciona 100% sem dependências de rede externa ou conexões com a nuvem.

---

## 🚀 Funcionalidades Principais

### 📡 1. Rede Baseada em WebSockets Assíncronos
* **Modelo Não Bloqueante (`asyncio`)**: O servidor e o cliente rodam sobre loops de eventos assíncronos de thread única, dispensando o modelo ineficiente de "uma thread por cliente".
* **Conectividade Segura**: Comunicação cifrada sob TLS/SSL nativo com geração automatizada de certificados locais autoassinados no servidor (`server.crt` e `server.key`).
* **Conexão e Reconexão Resiliente**: O motor central `ChatEngine` cuida de reconectar automaticamente o cliente caso a rede sofra oscilações.

### 🎨 2. Interface Gráfica Retrô Clássica (mIRC & Windows 98)
* **Visual dos Anos 2000**: Front-end minimalista com cantos perfeitamente quadrados (`border-radius: 0`), esquema de cinza corporativo clássico, bordas 3D chanfradas em relevo e tipografia pixelada.
* **Emojis Coloridos Nativos**: Exibição e renderização nativas e leves de emojis no chat através de fontes do sistema (`Segoe UI Emoji`, `Apple Color Emoji`, sans-serif), sem a necessidade de processamento gráfico pesado.
* **Ponte Python-JS Segura (Bridge)**: A lógica do front-end comunica-se com a API do PyWebView (`window.pywebview.api`) de maneira totalmente assíncrona e segura entre threads.

### 💻 3. Cliente de Terminal CLI Alternativo
* **Super-Leveza**: Um cliente executado diretamente no terminal/prompt de comando (`cliente_cli.py`), ideal para uso via SSH ou em computadores extremamente antigos.
* **Mesmo Motor Central**: Compartilha a mesma classe `ChatEngine` que o cliente gráfico, garantindo consistência nas regras de negócio e de comunicação.

### 👥 4. Salas Múltiplas, DMs e Amizades
* **Salas Privadas e Senhas**: Suporte para criação e entrada em salas com senha. Canais protegidos exibem um indicador visual no painel.
* **Logs Locais Individuais**: Gravação automática do histórico de mensagens em arquivos `.log` separados por sala ou DMs na pasta local `logs/`.
* **Sistema de Moderação**: Expulse (`/kick`), bana (`/ban`) ou desbana (`/unban`) usuários das suas salas criadas.

### ⚡ 5. Otimizações de Banco de Dados
* **SQLite Otimizado**: Escrita concorrente no SQLite utilizando modo WAL (`PRAGMA journal_mode=WAL` e `PRAGMA synchronous=NORMAL`).
* **Operações Não Bloqueantes**: Todas as queries síncronas do banco de dados no servidor e escritas de arquivos no cliente rodam em executores paralelos (`asyncio.to_thread`) para nunca congelar as conexões WebSocket.

---

## 📂 Estrutura do Repositório

```
ChatPy/
│
├── chat_engine.py       # Motor lógico central assíncrono do cliente
├── cliente_gui.py       # Inicializador da GUI nativa leve com PyWebView
├── cliente_cli.py       # Interface interativa de terminal (CLI fallback)
├── servidor.py          # Servidor WebSocket assíncrono (websockets + sqlite3)
├── requirements.txt     # Arquivo com as dependências do ecossistema
├── README.md            # Este guia de documentação
│
├── web/                 # Pasta contendo os recursos locais do front-end
│   ├── index.html       # Estrutura HTML do visual mIRC / Windows 98
│   ├── style.css        # Estilos clássicos de 3D chanfrado retrô
│   └── script.js        # Lógica JS e chamadas da ponte pywebview
│
├── tests/               # Testes unitários de banco e lógica
│   └── test_database.py
│
# Arquivos gerados localmente (NÃO comitados):
├── chat.db              # Banco de dados SQLite de mensagens e estados
├── server.key           # Chave privada TLS/SSL gerada pelo servidor
├── server.crt           # Certificado público TLS/SSL autoassinado
└── logs/                # Histórico de conversas locais em formato de texto (.log)
```

---

## 🛠️ Requisitos e Configuração

### 1. Instalação de Dependências
Instale as bibliotecas necessárias declaradas em `requirements.txt`:
```bash
pip install -r requirements.txt
```

*(Nota: O PyWebView utiliza o renderizador nativo do sistema operacional - ex: WebView2 no Windows, WebKit no macOS/Linux Debian - sendo extremamente leve e dispensando o empacotamento do Chromium).*

---

## 🚀 Como Executar

### Passo 1: Inicializando o Servidor
Execute o servidor no console:
```bash
python servidor.py
```
* O servidor gerará as chaves criptográficas SSL/TLS (`server.crt` e `server.key`) na primeira inicialização se elas não existirem.
* Ele começará a escutar conexões de maneira segura na porta padrão `5000`.

### Passo 2: Executando o Cliente Gráfico (GUI)
Certifique-se de que o certificado `server.crt` gerado está no mesmo diretório do cliente para autenticação de rede, e inicie:
```bash
python cliente_gui.py
```
* A janela retrô será iniciada e tentará se conectar ao IP especificado em `config_local.json` (ou localhost por padrão).

### Passo 3: Executando o Cliente Terminal (CLI)
Caso queira rodar diretamente no terminal sem interface gráfica:
```bash
python cliente_cli.py
```
Insira o IP/Porta no prompt e digite suas credenciais para entrar no chat de texto.

---

## 📡 Protocolo de Payloads JSON (Exemplos)

### Login de Usuário (Cliente -> Servidor)
```json
{
  "type": "login",
  "username": "usuario1",
  "password": "hash_da_senha"
}
```

### Mensagem em Sala (Cliente -> Servidor)
```json
{
  "type": "msg",
  "room": "#geral",
  "content": "Olá mundo! 🚀"
}
```

### Mensagem Privada DM (Cliente -> Servidor)
```json
{
  "type": "private_msg",
  "to": "usuario2",
  "content": "Conversa privada direta!"
}
```
