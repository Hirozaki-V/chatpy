"""
#11: Framework de bots para ChatPy.

Permite criar bots que respondem a comandos em salas e DMs, estilo IRC.
Um bot é uma classe que herda de ChatPyBot e implementa handlers.

Exemplo de bot (weather_bot.py):
    from server.bots import ChatPyBot, bot_command

    class WeatherBot(ChatPyBot):
        name = "weatherbot"
        description = "Previsão do tempo"

        @bot_command("previsao", help="Mostra previsão para uma cidade")
        async def handle_previsao(self, args, context):
            city = " ".join(args)
            return f"☀️ Previsão para {city}: ensolarado, 25°C"

Para registrar um bot no servidor:
    from server.bots import register_bot
    register_bot(WeatherBot())

Bots escutam mensagens via WebSocket dispatcher — quando uma mensagem
chega numa sala onde o bot é membro, o bot processa comandos que
começam com ! (ex: !previsao São Paulo).

P0-FIX: cada bot agora tem um UUID fixo derivado do seu nome (via UUID v5
no namespace ChatPy). Antes, o dispatcher setava sender_id=user_id (o
UUID de quem invocou o bot) no payload WS da resposta do bot — isto
confundia clientes que mostravam a mensagem do bot como se fosse do
usuário que invocou. Agora cada bot tem identidade própria.
"""
import logging
import re
import uuid
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass

logger = logging.getLogger("chatpy.bots")

# Registry global de bots
_registered_bots: List["ChatPyBot"] = []

# Namespace fixo para gerar UUIDs determinísticos por nome de bot (UUID v5)
# Isto garante que o "echobot" tenha sempre o mesmo UUID em todas as
# instâncias do servidor — clientes podem confiar que mensagens com
# sender_id=uuid(echobot) são sempre do bot, nunca de um usuário.
_CHATPY_BOT_NAMESPACE = uuid.UUID("a4c4b3a2-1d8b-4d2e-9c1f-7e5b6a3c2d10")


def bot_uuid_for_name(name: str) -> uuid.UUID:
    """Deriva um UUID determinístico a partir do nome do bot."""
    return uuid.uuid5(_CHATPY_BOT_NAMESPACE, name.lower())


@dataclass
class BotContext:
    """Contexto passado para o handler de um comando de bot."""
    room_id: Optional[str] = None  # UUID da sala (None se DM)
    sender_id: str = ""            # UUID de quem enviou
    sender_name: str = ""          # Username de quem enviou
    is_dm: bool = False            # True se veio via DM


class ChatPyBot:
    """
    Classe base para bots do ChatPy.

    Subclasses definem:
      - name: nome do bot (ex: "weatherbot")
      - description: descrição curta
      - métodos decorados com @bot_command que respondem a comandos

    O bot é registrado no dispatcher e recebe todas as mensagens de salas
    onde é membro. Se a mensagem começa com !comando, o bot executa o
    handler correspondente.
    """
    name: str = "bot"
    description: str = "Bot sem descrição"
    command_prefix: str = "!"  # padrão IRC: !comando

    @property
    def uuid(self) -> uuid.UUID:
        """UUID determinístico derivado do nome do bot."""
        return bot_uuid_for_name(self.name)

    def get_commands(self) -> Dict[str, Callable]:
        """Retorna dict {comando: handler} dos comandos registrados."""
        commands = {}
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if hasattr(attr, "_bot_command_name"):
                commands[attr._bot_command_name] = attr
        return commands

    async def on_message(self, content: str, context: BotContext) -> Optional[str]:
        """
        Chamado quando uma mensagem chega numa sala onde o bot é membro.
        Retorna a resposta do bot (ou None se não deve responder).
        """
        if not content.startswith(self.command_prefix):
            return None

        # Parse: !comando arg1 arg2 ...
        parts = content[len(self.command_prefix):].split()
        if not parts:
            return None

        command = parts[0].lower()
        args = parts[1:]

        commands = self.get_commands()
        if command in commands:
            try:
                handler = commands[command]
                return await handler(args, context) if _is_async(handler) else handler(args, context)
            except Exception as e:
                logger.error("Erro no bot %s comando %s: %s", self.name, command, e)
                return f"❌ Erro ao executar comando: {e}"

        # Comando especial: !help
        if command == "help":
            return self._format_help()

        return None

    def _format_help(self) -> str:
        """Gera texto de ajuda com todos os comandos do bot."""
        commands = self.get_commands()
        lines = [f"🤖 {self.name} — {self.description}"]
        lines.append(f"Comandos (prefixo: {self.command_prefix}):")
        for cmd_name, handler in sorted(commands.items()):
            help_text = getattr(handler, "_bot_command_help", "")
            lines.append(f"  {self.command_prefix}{cmd_name} — {help_text}")
        if not commands:
            lines.append("  (nenhum comando registrado)")
        return "\n".join(lines)


def bot_command(name: str, help: str = ""):
    """
    Decorator que registra um método como comando de bot.

    Uso:
        @bot_command("previsao", help="Mostra previsão do tempo")
        async def handle_previsao(self, args, context):
            return "Ensolarado"
    """
    def decorator(func):
        func._bot_command_name = name
        func._bot_command_help = help
        return func
    return decorator


def _is_async(func):
    import asyncio
    return asyncio.iscoroutinefunction(func)


def register_bot(bot: ChatPyBot):
    """Registra um bot no servidor."""
    _registered_bots.append(bot)
    logger.info(
        "Bot registrado: %s (UUID=%s, %d comandos)",
        bot.name, bot.uuid, len(bot.get_commands()),
    )


def get_registered_bots() -> List[ChatPyBot]:
    """Retorna todos os bots registrados."""
    return list(_registered_bots)


async def process_bots(content: str, context: BotContext) -> List[tuple]:
    """
    Processa uma mensagem através de todos os bots registrados.

    P0-FIX: retorna lista de tuplas (bot, response) em vez de strings
    formatadas — o dispatcher usa bot.uuid e bot.name para montar o
    payload WS com sender_id e sender_name corretos.
    """
    responses = []
    for bot in _registered_bots:
        try:
            response = await bot.on_message(content, context)
            if response:
                responses.append((bot, response))
        except Exception as e:
            logger.error("Erro no bot %s: %s", bot.name, e)
    return responses


# ---------------------------------------------------------------------------
# Bot de exemplo: echo (útil para testes)
# ---------------------------------------------------------------------------
class EchoBot(ChatPyBot):
    """Bot simples que repete o que você diz. Útil para testes."""
    name = "echobot"
    description = "Repete mensagens (bot de teste)"

    @bot_command("echo", help="Repete o texto enviado")
    async def handle_echo(self, args, context):
        if not args:
            return "Uso: !echo <texto>"
        return " ".join(args)

    @bot_command("ping", help="Responde pong")
    async def handle_ping(self, args, context):
        return "🏓 pong!"


# Registra o bot de exemplo por padrão (pode ser desativado via env)
import os as _os
if _os.getenv("BOT_ECHO_ENABLED", "true").lower() == "true":
    register_bot(EchoBot())
