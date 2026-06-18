# ChatPy V2 💬🐍

O **ChatPy V2** é um ecossistema completo de comunicação auto-hospedável (self-hosted) inspirado na simplicidade do MSN Messenger, na filosofia textual do IRC/WeeChat e na estética terminal cibernética. 

O projeto foi totalmente reconstruído do zero, adotando uma arquitetura **API-First** moderna e assíncrona, composta por um servidor central robusto e dois clientes oficiais (gráfico e terminal) que se comunicam sob o mesmo protocolo de rede JSON via WebSockets.

---

## 🏛️ Arquitetura do Projeto

O ChatPy V2 é dividido de forma estrita em componentes independentes:

* **`server/`**: Servidor assíncrono construído sobre **FastAPI** e **Uvicorn**, utilizando **SQLAlchemy** para persistência no banco de dados. Gerencia sessões JWT, rate limit e dispatching de eventos em tempo real no WebSocket.
* **`shared/`**: Contratos de validação (via **Pydantic**), enums de eventos (`shared/events`) e modelos comuns (`shared/types`) consumidos tanto pelo servidor quanto pelos clientes. Conta também com wrappers de conexão reutilizáveis (`shared/client`).
* **`client-desktop/`**: Interface gráfica nativa de alta performance construída com **PySide6 (Qt)**. Adota um visual retrô escuro limpo, sem cantos arredondados, estruturado em abas e com suporte a notificações desktop do sistema.
* **`client-cli/`**: Interface de linha de comando baseada em **Typer** e **Rich**, oferecendo painéis WeeChat-style em tempo real e captura não-bloqueante de teclado.

---

## 🚀 Como Executar o Servidor (Docker Compose)

O deploy do servidor é otimizado para ser realizado em segundos em qualquer máquina (incluindo **Raspberry Pi 3B/4/5** e servidores domésticos) usando Docker.

> [!IMPORTANT]
> **Configuração Obrigatória de Segurança (`JWT_SECRET`)**:
> O servidor do ChatPy V2 exige a definição da variável de ambiente `JWT_SECRET` para a assinatura e validação segura dos tokens JWT. Caso essa variável não esteja definida no ambiente, a inicialização falhará.
>
> Você pode definí-la temporariamente no terminal antes de rodar os comandos:
> ```bash
> export JWT_SECRET="sua-chave-secreta-super-segura"
> ```
> Ou criando um arquivo `.env` no diretório raiz do projeto com o conteúdo:
> ```env
> JWT_SECRET="sua-chave-secreta-super-segura"
> ```

### 1. Inicialização Padrão (Leve com SQLite)
Por padrão, o servidor rodará de forma extremamente leve usando SQLite (configurado em modo WAL de alta concorrência) gravado em um volume docker:

```bash
docker compose up -d
```
*O servidor estará escutando requisições em `http://localhost:5000` e conexões WebSocket em `ws://localhost:5000/ws`.*

### 2. Inicialização com Banco de Dados Postgres e Cache Redis
Para cenários de alta disponibilidade e escalabilidade, você pode ativar os serviços de suporte via Perfis do Docker Compose:

```bash
# Sobe o servidor juntamente com Postgres e Redis
docker compose --profile database --profile cache up -d
```

### 3. Parando a Infraestrutura
Para parar e remover todos os containers iniciados:
```bash
docker compose down
```

---

## 🖥️ Como Executar os Clientes

### Instalação de Dependências
Certifique-se de instalar as dependências de runtime antes de rodar os clientes locais:
```bash
pip install -r requirements.txt
```
*(Além de `PySide6`, `typer` e `rich`, certifique-se de ter `httpx` e `websockets` instalados).*

---

### 🟢 1. Cliente Desktop (PySide6)
Inicie a interface de usuário gráfica rodando:

```bash
python client-desktop/main.py
```

* **Login/Registro**: Na primeira janela, preencha o endereço do servidor (padrão: `127.0.0.1:5000`), apelido e senha. Clique em "ENTRAR" (ou "CADASTRAR" caso seja seu primeiro acesso).
* **Navegação**: Use duplo clique em usuários online ou contatos para iniciar DMs e clique duas vezes nos canais para alternar abas de chat.

---

### 📟 2. Cliente de Terminal (CLI)
Inicie a interface clássica IRC no terminal rodando:

```bash
python client-cli/main.py --host 127.0.0.1 --port 5000
```

* **Comandos Úteis**:
  * `/join #canal` - Entrar em uma sala pública.
  * `/leave` - Sair da aba/sala ativa.
  * `/dm username mensagem` - Enviar DM direta para um usuário.
  * `/status away` - Mudar presença para ausente.
  * `TAB` - Alternar rapidamente entre as abas ativas.
  * `/help` - Ver a lista de comandos completa.

---

## 📚 Documentação Adicional

Para guias de deploy avançados e arquitetura, leia:
* 📖 [Estratégia de Deploy](docs/deploy.md)
* 📖 [Guia de Hospedagem no Raspberry Pi](docs/guia-raspberry-pi.md)
* 📖 [Guia de VPN e Acesso Remoto com Tailscale](docs/guia-tailscale.md)
* 📖 [Especificação do Protocolo V1](docs/protocolo.md)
