"""
#7: Descoberta automática de servidores ChatPy na rede local via mDNS.

Usa o protocolo mDNS (Multicast DNS) para anunciar e descobrir servidores
ChatPy na mesma rede LAN — sem necessidade de configurar IPs manualmente.

Funciona como o AirPlay/Bonjour da Apple: o servidor se anuncia como
`_chatpy._tcp.local` e os clientes podem descobrir servidores disponíveis.

Requer a biblioteca `zeroconf` (pip install zeroconf). Se não estiver
instalada, o módulo funciona em modo silencioso (sem descoberta).

Configuração:
  - LAN_DISCOVERY_ENABLED (default true): liga/desliga
  - LAN_DISCOVERY_PORT (default 5000): porta do servidor
"""
import os
import socket
import logging
from typing import List, Dict

logger = logging.getLogger("chatpy.lan_discovery")

_LAN_DISCOVERY_ENABLED = os.getenv("LAN_DISCOVERY_ENABLED", "true").lower() == "true"
_LAN_DISCOVERY_PORT = int(os.getenv("LAN_DISCOVERY_PORT", "5000"))

_SERVICE_TYPE = "_chatpy._tcp.local."
_SERVICE_NAME = "chatpy._chatpy._tcp.local."

_announcer = None
_browser = None


def is_lan_discovery_enabled() -> bool:
    return _LAN_DISCOVERY_ENABLED and _try_import_zeroconf() is not None


def _try_import_zeroconf():
    try:
        from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser
        return Zeroconf, ServiceInfo, ServiceBrowser
    except ImportError:
        return None


def get_local_ip() -> str:
    """Retorna o IP local da máquina (não 127.0.0.1)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def start_announcing(server_name: str = "ChatPy Server", port: int = None):
    """
    Anuncia este servidor ChatPy na rede local via mDNS.

    Deve ser chamado no startup do servidor. Idempotente — se já
    está anunciando, não faz nada.
    """
    global _announcer

    if not _LAN_DISCOVERY_ENABLED:
        return

    zeroconf_classes = _try_import_zeroconf()
    if not zeroconf_classes:
        logger.info("LAN discovery: zeroconf não instalado — anunciamento desativado")
        return

    if _announcer is not None:
        return  # já está anunciando

    Zeroconf, ServiceInfo, _ = zeroconf_classes
    port = port or _LAN_DISCOVERY_PORT
    local_ip = get_local_ip()

    try:
        zc = Zeroconf()
        info = ServiceInfo(
            type_=_SERVICE_TYPE,
            name=_SERVICE_NAME,
            addresses=[socket.inet_aton(local_ip)],
            port=port,
            properties={
                b"name": server_name.encode("utf-8"),
                b"version": b"2.0.1",
            },
            server=f"{socket.gethostname()}.local.",
        )
        zc.register_service(info)
        _announcer = (zc, info)
        logger.info("LAN discovery: anunciando ChatPy em %s:%d (mDNS)", local_ip, port)
    except Exception as e:
        logger.warning("LAN discovery: erro ao iniciar anunciamento: %s", e)


def stop_announcing():
    """Para de anunciar o servidor. Chamado no shutdown."""
    global _announcer
    if _announcer is not None:
        try:
            zc, info = _announcer
            zc.unregister_service(info)
            zc.close()
        except Exception:
            pass
        _announcer = None


def discover_servers(timeout: float = 3.0) -> List[Dict[str, str]]:
    """
    Descobre servidores ChatPy na rede local.

    Bloqueia por `timeout` segundos enquanto escuta respostas mDNS.
    Retorna lista de dicts: [{name, host, port, ip}, ...]

    Usado por clientes para mostrar "servidores disponíveis na sua rede"
    na tela de login — sem precisar digitar IP manualmente.
    """
    zeroconf_classes = _try_import_zeroconf()
    if not zeroconf_classes:
        return []

    Zeroconf, _, ServiceBrowser = zeroconf_classes

    discovered = []

    class ChatPyListener:
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name)
            if info:
                for addr in info.addresses:
                    ip = socket.inet_ntoa(addr)
                    props = {k.decode(): v.decode() for k, v in (info.properties or {}).items()}
                    discovered.append({
                        "name": props.get("name", "ChatPy Server"),
                        "host": info.server,
                        "ip": ip,
                        "port": str(info.port),
                        "version": props.get("version", "?"),
                    })

        def remove_service(self, zc, type_, name):
            pass

    try:
        zc = Zeroconf()
        listener = ChatPyListener()
        ServiceBrowser(zc, _SERVICE_TYPE, listener)

        # Espera o timeout coletar respostas
        import time
        time.sleep(timeout)

        zc.close()
    except Exception as e:
        logger.warning("LAN discovery: erro ao descobrir servidores: %s", e)

    return discovered
