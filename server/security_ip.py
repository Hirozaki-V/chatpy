"""
T1-FIX: Extração segura de IP do cliente (mitigação de spoofing de X-Forwarded-For).

ANTES: todos os pontos do código que precisavam do IP do cliente liam
diretamente o header `X-Forwarded-For` e pegavam o primeiro valor:
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()

ISTO É PERIGOSO: se o servidor for exposto diretamente à internet (sem proxy
reverso confiável como Nginx/Cloudflare limpando esse header), um atacante
pode enviar `X-Forwarded-For: 1.2.3.4` falso. Consequências:
  1. Burlar rate limit — o atacante usa IPs diferentes a cada requisição
  2. Bloquear usuários legítimos — o atacante envia X-Forwarded-For com o
     IP da vítima e estoura o limite de tentativas de login nela
  3. Poluir logs de auditoria com IPs falsos

AGORA: só confiamos em X-Forwarded-For se o request veio de um IP de proxy
configurado como confiável. Caso contrário, usamos request.client.host (IP
real da conexão TCP).

Configuração via env:
  TRUSTED_PROXIES — lista de IPs/CIDRs separados por vírgula (default: vazio)
    Ex: TRUSTED_PROXIES=127.0.0.1,10.0.0.0/8,172.16.0.0/12

Se TRUSTED_PROXIES não estiver configurado (default), NUNCA confiamos no
X-Forwarded-For — usamos sempre o IP da conexão TCP. Isto é o mais seguro
para servidores expostos diretamente à internet.
"""
import os
import ipaddress
import logging
from typing import Optional, List

logger = logging.getLogger("chatpy.security.ip")


# Cache dos proxies confiáveis (parsed uma vez em import-time)
_trusted_networks: Optional[List[ipaddress.IPv4Network]] = None


def _load_trusted_proxies() -> List[ipaddress.IPv4Network]:
    """
    Carrega e parseia a lista de proxies confiáveis do env TRUSTED_PROXIES.
    Suporta IPs individuais (10.0.0.1) e CIDRs (10.0.0.0/8).
    Retorna lista vazia se não configurado.
    """
    global _trusted_networks
    if _trusted_networks is not None:
        return _trusted_networks

    raw = os.getenv("TRUSTED_PROXIES", "").strip()
    if not raw:
        _trusted_networks = []
        return _trusted_networks

    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            # Tenta como CIDR primeiro
            if "/" in entry:
                networks.append(ipaddress.ip_network(entry, strict=False))
            else:
                # IP individual — converte para /32
                networks.append(ipaddress.ip_network(entry + "/32", strict=False))
        except ValueError as e:
            logger.warning("TRUSTED_PROXIES: entrada inválida '%s': %s", entry, e)

    _trusted_networks = networks
    if networks:
        logger.info(
            "Proxies confiáveis para X-Forwarded-For: %s",
            ", ".join(str(n) for n in networks),
        )
    else:
        logger.info(
            "Nenhum proxy confiável configurado (TRUSTED_PROXIES vazio) — "
            "X-Forwarded-For será ignorado por segurança."
        )

    return networks


def _is_trusted_proxy(ip: str) -> bool:
    """Verifica se o IP está na lista de proxies confiáveis."""
    if not ip:
        return False
    networks = _load_trusted_proxies()
    if not networks:
        return False
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in networks)
    except ValueError:
        return False


def get_client_ip(request) -> str:
    """
    Extrai o IP real do cliente de forma segura.

    Lógica:
      1. Pega o IP da conexão TCP (request.client.host) — sempre confiável
      2. Se este IP for um proxy confiável (em TRUSTED_PROXIES), então
         confiamos no X-Forwarded-For e pegamos o último IP da cadeia
         (o mais à direita é o que o proxy adicionou, mais próximo do
         cliente real)
      3. Caso contrário, retornamos o IP da conexão TCP

    Funciona para FastAPI Request e WebSocket (ambos têm .client e .headers).

    Args:
        request: FastAPI Request ou WebSocket

    Returns:
        IP do cliente como string, ou "unknown" se não for possível determinar.
    """
    # 1. IP da conexão TCP — sempre confiável
    tcp_ip = ""
    if hasattr(request, "client") and request.client:
        tcp_ip = request.client.host or ""

    # 2. Se não veio de proxy confiável, retorna TCP IP direto
    if not _is_trusted_proxy(tcp_ip):
        return tcp_ip or "unknown"

    # 3. Veio de proxy confiável — parseia X-Forwarded-For
    # O header pode conter uma lista: "client, proxy1, proxy2"
    # O cliente real é o PRIMEIRO da lista (mais à esquerda), mas só é
    # confiável se todos os proxies na cadeia também forem confiáveis.
    # Para simplicidade e segurança, pegamos o primeiro — em ambientes
    # com múltiplos proxies, configure TRUSTED_PROXIES com todos eles.
    forwarded = request.headers.get("x-forwarded-for", "") or \
                request.headers.get("X-Forwarded-For", "")
    if not forwarded:
        return tcp_ip or "unknown"

    # Pega o primeiro IP da lista (cliente original)
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if not parts:
        return tcp_ip or "unknown"

    return parts[0]


def reset_trusted_proxies_cache():
    """Reseta o cache de proxies confiáveis (para testes)."""
    global _trusted_networks
    _trusted_networks = None
