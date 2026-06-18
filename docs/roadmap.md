# Roadmap do ChatPy

A evolução do ChatPy será tratada em 3 grandes épicos de desenvolvimento, garantindo que o software escale de um protótipo viável para uma robusta ferramenta de comunicação interconectada.

## Fase V1: O Núcleo Retrô
**Foco:** Estabelecer a arquitetura fundacional, estabilidade básica da API, protocolo JSON e clientes baseados em componentes de interface ricos (saindo do mundo Web UI).
- Criação e validação do pacote `shared/`.
- Construção do servidor assíncrono (FastAPI/WebSockets/SQLite).
- Lógica de Registro/Login (Argon2, JWT).
- Cliente Desktop nativo (PySide6) com UX limpa estilo IRC/MSN.
- Cliente CLI paritário, focado em power-users (`Rich`).
- Funcionalidades principais: DMs, Criação/Ingresso em Salas, Lista de Amigos, Presença e Histórico local.

## Fase V2: Privacidade e Customização
**Foco:** Refinar a segurança, privacidade da comunicação e personalização da interface nativa.
- Implementação de Criptografia Ponta a Ponta (E2EE) para mensagens diretas (DMs).
- Suporte para salas efêmeras (mensagens destruídas automaticamente, operando apenas em RAM no lado do servidor).
- Engine robusta de Plugins para permitir que os clientes carreguem scrips próprios ou modifiquem comportamento da GUI.
- Suporte nativo a extensões de Temas visuais (Dark/Light estendidos).
- Perfis de usuário ricos e customizáveis.

## Fase V3: A Rede Federation/Bridge (Expansão Global)
**Foco:** Quebrar o isolamento de instâncias individuais usando uma estrutura de Bridge nativa.
- Introdução dos **Bridge Servers**: um protocolo de comunicação Server-to-Server que permite que instâncias independentes de ChatPy se conversem.
- Compartilhamento federado: um usuário no servidor `foo.pi` pode convidar alguém de `bar.net` para um chat cruzado sem criar uma conta no outro sistema.
- API consolidada para integrações externas de serviços corporativos ou de automação.
