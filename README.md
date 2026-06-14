# ChatPy 💬🐍

O **ChatPy** é um sistema de chat de arquitetura Cliente-Servidor robusto, seguro e leve, desenvolvido em Python. Ele combina a simplicidade do framework gráfico `tkinter` (utilizando o tema nativo `clam`) com mecanismos modernos de comunicação segura via SSL/TLS, banco de dados relacional concorrente (SQLite em modo WAL) e interface otimizada por eventos.

Este projeto foi refatorado para transformar um protótipo básico em uma aplicação de nível de produção adequada para implantação (como em um servidor doméstico Raspberry Pi), mantendo o consumo de recursos extremamente baixo.

---

## 🚀 Funcionalidades Principais

### 🔒 1. Segurança e Criptografia Real (SSL/TLS)
* **Transporte Seguro Obrigatório**: Toda a comunicação trafega sobre sockets criptografados com SSL/TLS. Não há fallback para texto plano (segurança absoluta contra interceptações de tráfego/Sniffing).
* **Autocomprovação e Geração de Certificados**: Na ausência dos arquivos `server.crt` e `server.key`, o próprio servidor gera dinamicamente chaves criptográficas autoassinadas RSA robustas utilizando a biblioteca `cryptography`.
* **Validação Rígida no Cliente**: O cliente exige que o certificado do servidor (`server.crt`) esteja no mesmo diretório para validar a autenticidade da conexão. Se removido intencionalmente pelo usuário, o cliente opera em modo de criptografia sem validação de host (útil para testes rápidos).

### ⚡ 2. Backend SQLite de Alta Performance
* **Modo WAL (Write-Ahead Logging)**: Configurado nativamente (`PRAGMA journal_mode=WAL` e `PRAGMA synchronous=NORMAL`) para permitir leituras simultâneas sem bloquear gravações no banco de dados.
* **Isolamento de Conexões por Thread**: O servidor gerencia o banco criando conexões independentes por thread concorrente, evitando conflitos de acesso.
* **Sem Trava Global (`db_lock`)**: O locking global foi removido, sendo substituído por um timeout de lock de banco estendido para 15 segundos para máxima concorrência.

### 👥 3. Salas Múltiplas e Concorrentes
* **Inscrição Não-Excludente**: Os usuários podem entrar e estar presentes em várias salas (canais) simultaneamente.
* **Isolamento de Logs e DMs**: O cliente salva os logs de mensagens de forma isolada (ex: `logs/#geral.log` para canais ou `logs/dm_usuarioA_usuarioB.log` para mensagens diretas). O isolamento baseia-se unicamente no cabeçalho do pacote recebido da rede, garantindo que mesmo recebendo mensagens simultâneas em segundo plano, os logs não se misturem.

### 🌐 4. Otimização de Rede por Eventos (Deltas)
* **Protocolo Baseado em JSON**: Toda a troca de dados acontece por meio de pacotes JSON delimitados e sanitizados contra quebras de linha (`\n` e `\r`).
* **Estado Incremental (Deltas)**: Em vez de requisitar e transmitir o estado inteiro do servidor a cada segundo, o servidor envia apenas atualizações pontuais e atômicas quando um evento ocorre (ex: novos usuários entram, mudam de status ou salas são criadas). Isso poupa largura de banda e ciclos de CPU tanto do servidor quanto do cliente.

### 🎨 5. Interface Gráfica Inteligente e Responsiva
* **Layout Fluido (Ordem de Empacotamento)**: O layout foi reorganizado utilizando `.pack()` de forma que a barra inferior de digitação (`bottom_bar`) e a barra de controle superior (`top_bar`) permaneçam sempre visíveis mesmo se o usuário redimensionar a janela para tamanhos mínimos.
* **Markdown Básico Integrado**: Renderiza textos no chat utilizando formatação em tempo de execução:
  * `**negrito**` -> Texto em negrito.
  * `*itálico*` -> Texto em itálico.
  * `` `código` `` -> Texto estilizado com fonte monoespaçada e fundo contrastante.
* **Filtro e Busca no Histórico**: Diálogo gráfico (`Toplevel`) que permite buscar mensagens passadas no banco de dados. A busca é segura: o servidor garante que você só consiga buscar mensagens de salas públicas ou mensagens diretas (DMs) onde você mesmo seja um dos participantes.
* **Status Automático de Ociosidade**: O cliente monitora a atividade do mouse e do teclado globalmente na janela do chat. Após 5 minutos sem interação, o status do usuário muda automaticamente para "Ausente" no servidor. Qualquer nova interação restaura o status para "Online".
* **Controles de Notificação (Sons e Nudge)**: Configurações de som de novas mensagens e de "Nudge" (chamar atenção balançando a janela do cliente) podem ser habilitadas/desabilitadas em um menu de configurações, sendo persistidas localmente no arquivo `config_local.json`.
* **Visualização de Imagens no Chat**: Se o usuário enviar um arquivo de imagem (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`), o chat exibirá uma miniatura estilizada de até 120x120px no corpo da conversa. A aplicação usa a biblioteca `Pillow` se disponível (e provê fallback nativo via Tkinter `PhotoImage` para formatos PNG/GIF caso não esteja instalada).
* **Drag & Drop de Arquivos**: O cliente suporta arrastar e soltar arquivos de imagem/texto diretamente na área de conversa para envio rápido (utilizando a biblioteca `tkinterdnd2`, com fallback seguro se o sistema não possuir suporte).
* **Criação de Salas Unificada**: Interface simples e direta para criar canais protegidos por senha. Canais privados são indicados visualmente por um ícone de cadeado (`🔒`) na lista de salas.

---

## 📂 Estrutura do Repositório

```
ChatPy/
│
├── cliente.py          # Interface gráfica e lógica do cliente Tkinter
├── servidor.py         # Servidor multithread sockets com SSL/TLS e SQLite
├── limpar_db.py        # Utilitário administrativo de limpeza e otimização do banco
├── .gitignore          # Filtros para não versionar dados locais e credenciais
├── README.md           # Este manual de documentação
│
# Gerados localmente (NÃO comitados):
├── chat.db             # Banco de dados SQLite de mensagens e estados
├── server.key          # Chave privada SSL/TLS do servidor
├── server.crt          # Certificado SSL público para autenticação
├── config_local.json   # Configurações de preferências do cliente
└── logs/               # Registros locais de histórico do cliente (.log)
```

---

## 🛠️ Requisitos e Configuração

### 1. Requisitos do Sistema
* Python 3.8 ou superior instalado.
* Acesso à internet ou rede local estável.

### 2. Dependências
As dependências do projeto são mínimas. O núcleo funciona apenas com a biblioteca padrão do Python, exceto pela criptografia SSL dinâmica:

#### Dependências Obrigatórias no Servidor:
* `cryptography` (Usado para gerar o certificado SSL autoassinado de forma automática).

No Windows/macOS:
```bash
pip install cryptography
```
No Raspberry Pi / Linux Debian (PEP 668):
```bash
sudo apt install python3-cryptography -y
```

#### Dependências Opcionais no Cliente (Melhoria de UI/UX):
* `Pillow` (Exibição de miniaturas de imagem no chat):
  ```bash
  pip install Pillow
  # No Linux: sudo apt install python3-pil python3-pil.imagetk -y
  ```
* `tkinterdnd2` (Drag and Drop de arquivos):
  ```bash
  pip install tkinterdnd2
  ```

---

## 🚀 Como Executar

### Passo 1: Inicializando o Servidor
Execute o servidor na sua máquina ou em um dispositivo da rede local (ex: Raspberry Pi):
```bash
python servidor.py
```
* O servidor gerará o arquivo `server.key` e `server.crt` na primeira inicialização se eles não existirem.
* Ele começará a escutar conexões seguras na porta padrão `5000`.

### Passo 2: Configurando o Cliente
1. Certifique-se de copiar o arquivo `server.crt` gerado pelo servidor para a mesma pasta do script `cliente.py` na máquina cliente (isso garante a autenticação SSL segura).
2. Inicie o cliente:
```bash
python cliente.py
```
3. Digite o endereço IP do seu servidor (ex: `127.0.0.1` para testes locais, ou o IP privado da sua rede local) e faça login ou crie uma conta.

---

## 🧹 Script de Limpeza Administrativa (`limpar_db.py`)

Caso precise resetar o servidor para iniciar um histórico limpo e otimizar o espaço em disco ocupado, o script administrativo `limpar_db.py` está disponível. Para usá-lo:

1. Pare o processo do servidor (`servidor.py`).
2. Execute o script:
   ```bash
   python limpar_db.py
   ```
3. O script irá:
   * Limpar todo o histórico de mensagens e anexos.
   * Apagar salas customizadas (preservando o canal principal `#geral`).
   * Remover contas de usuários comuns (mantendo os administradores).
   * Limpar listas de amizade e banimentos.
   * Executar o comando `VACUUM` no SQLite, reorganizando fisicamente o banco e reduzindo o tamanho do arquivo `chat.db` em disco ao mínimo absoluto.
4. Reinicie o servidor.

---

## 📡 Detalhes do Protocolo JSON (Payloads)

O protocolo de sockets do **ChatPy** trafega objetos JSON terminados em quebra de linha. Abaixo, alguns exemplos de payload:

### Login de Usuário (Cliente -> Servidor)
```json
{
  "action": "login",
  "username": "usuario1",
  "password": "senha_criptografada_ou_plain"
}
```

### Transmissão de Mensagem (Cliente -> Servidor)
```json
{
  "action": "send_msg",
  "room": "#geral",
  "msg": "Olá **mundo**! `print('Hello')`"
}
```

### Envio de Mensagem Direta (DM)
```json
{
  "action": "send_dm",
  "to_user": "usuario2",
  "msg": "Esta é uma conversa secreta!"
}
```

### Evento Incremental do Servidor (Servidor -> Clientes)
```json
{
  "event": "user_status_changed",
  "username": "usuario1",
  "status": "Ausente"
}
```

---

## 🗄️ Estrutura do Banco de Dados SQLite

O banco `chat.db` é composto pelas seguintes tabelas principais:
1. `usuarios`: Cadastro de usuários, hash de senhas, permissões (admin ou comum) e data de criação.
2. `salas`: Cadastro de salas públicas e privadas (com hash de senha).
3. `mensagens`: Registro de todas as mensagens com carimbo de data/hora (timestamp), remetente, destino (sala ou usuário em caso de DM) e tipo de payload.
4. `amigos`: Controle de convites e conexões diretas aceitas.
5. `banimentos`: Registros de usuários banidos das salas ou do servidor.

---

## ⚖️ Licença
Este projeto é fornecido "como está" para fins de aprendizado e uso privado. Sinta-se livre para clonar, modificar e expandir conforme suas necessidades!
