# Próximos Passos

## Para usuários

Se você quer **usar** o ChatPy:

1. **Suba um servidor** — siga [INSTALAÇÃO-RAPIDA.md](../INSTALACAO-RAPIDA.md)
2. **Instale o cliente** — Desktop ou CLI
3. **Convide amigos** — compartilhe o IP ou use [Tailscale](guia-tailscale.md)
4. **Administre** — acesse `http://servidor:5000/admin`

## Para desenvolvedores

Se você quer **contribuir** ou **estender** o ChatPy:

1. Leia [CONTRIBUTING.md](../CONTRIBUTING.md) — setup de desenvolvimento
2. Leia [ARCHITECTURE.md](../ARCHITECTURE.md) — como o código funciona
3. Leia [docs/protocolo.md](protocolo.md) — protocolo REST e WebSocket

### Criar um bot

```python
from server.bots import ChatPyBot, bot_command

class MeuBot(ChatPyBot):
    name = "meubot"
    description = "Meu bot customizado"

    @bot_command("hora", help="Mostra a hora atual")
    async def handle_hora(self, args, context):
        from datetime import datetime
        return f"🕐 {datetime.now().strftime('%H:%M:%S')}"

# Registrar no startup do servidor
from server.bots import register_bot
register_bot(MeuBot())
```

Na sala, digite `!hora` e o bot responde.

### Criar um tema customizado

```json
{
    "name": "Meu Tema",
    "author": "voce",
    "version": "1.0",
    "colors": {
        "bg_main": "#1a1a2e",
        "text_main": "#e0e0e0",
        "accent_color": "#e94560",
        ...
    }
}
```

Salve como `.chatpy-theme` e importe com `/theme import arquivo.chatpy-theme`.

### Federar com outro servidor

1. No servidor A, cadastre o servidor B como peer:
   ```
   POST /api/admin/peers
   {"domain": "chatpy.outro.com", "base_url": "https://chatpy.outro.com"}
   ```
2. No servidor B, faça o mesmo com o servidor A
3. Usuários podem mandar DMs federadas: `/fmsg @user@chatpy.outro.com olá!`

## Para quem quer privacidade real

O E2E encryption está parcialmente implementado (scaffold). Para usar:
1. Cliente gera par Ed25519 (Identity Key)
2. Publica via `PUT /api/keys/identity`
3. Gera pool de One-Time PreKeys e publica via `POST /api/keys/prekeys`
4. Para iniciar DM E2E, busca chaves do destinatário via `GET /api/keys/{username}`
5. Executa X3DH localmente para derivar chave compartilhada
6. Implementa Double Ratchet para cifrar mensagens

O passo 6 (Double Ratchet) ainda não está implementado — é a próxima grande feature.
