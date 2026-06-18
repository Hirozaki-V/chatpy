# Estrutura de Diretórios (V1)

A estrutura do repositório deve garantir a ausência de arquivos e classes gigantes, separando cada domínio de responsabilidade.

```text
chatpy/
├── client-desktop/        # Cliente Gráfico (PySide6)
│   ├── main.py            # Ponto de entrada do cliente GUI
│   ├── ui/                # Componentes visuais, janelas, widgets
│   ├── services/          # Lógica de conexão WebSocket e chamadas de API
│   ├── models/            # Estado local do cliente
│   └── controllers/       # Intermediação entre UI e Services
│
├── client-cli/            # Cliente Terminal (Rich/Typer)
│   ├── main.py            # Ponto de entrada do cliente CLI
│   ├── views/             # Telas e renderização do terminal
│   └── services/          # Lógica de conexão
│
├── server/                # Servidor Backend (FastAPI)
│   ├── main.py            # Inicialização da aplicação servidor
│   ├── api/               # Endpoints REST (ex: registro, login inicial)
│   ├── websocket/         # Gerenciamento de conexões, broadcasting
│   ├── database/          # Configuração, migrações, sessões do banco
│   ├── auth/              # Hashing Argon2, geração e validação de JWT
│   ├── rooms/             # Lógica de negócio de salas (CRUD, permissões)
│   └── users/             # Lógica de negócio de usuários e perfis
│
├── shared/                # Código compartilhado entre Servidor e Clientes
│   ├── protocol/          # Definições do protocolo de comunicação
│   ├── events/            # Enumerações dos tipos de eventos
│   └── types/             # Schemas Pydantic base
│
└── docs/                  # Documentação de arquitetura e especificações
```
