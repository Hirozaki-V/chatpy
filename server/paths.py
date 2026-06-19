"""
P0-FIX: Resolução centralizada de caminhos de arquivos persistentes.

ANTES: vários módulos usavam os.getcwd() ou os.path.dirname(__file__) para
decidir onde gravar arquivos como o JWT_SECRET auto-gerado. Se o operador
executasse o servidor a partir de diretórios diferentes em momentos
diferentes (ex: `python server/main.py` um dia, `cd .. && python
chatpy/server/main.py` no outro), o arquivo não era encontrado — o servidor
regenerava o secret e invalidava TODAS as sessões JWT em uso.

AGORA: todos os arquivos persistentes ficam em um único diretório base,
resolvido por ordem de precedência:
  1. CHATPY_DATA_DIR env var (se definida)
  2. Diretório do projeto (parent de server/) — útil em dev
  3. ~/.chatpy/ — fallback universal (funciona mesmo sem permissão de
     escrita no diretório do projeto)

O operador pode inspecionar qual foi usado via get_data_dir().

T2-FIX: no Windows, os.chmod(0o600) NÃO restringe efetivamente o acesso ao
arquivo — Windows usa ACLs, não POSIX mode bits. Adicionamos
_restrict_file_windows() que usa icacls para permitir acesso apenas ao
usuário atual e SYSTEM. Chamado por todos os arquivos sensíveis (JWT secret,
chave de federação).
"""
import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("chatpy.paths")


def _restrict_dir_windows(path: Path):
    """
    T2-FIX: restringe acesso ao diretório no Windows via icacls.

    Remove herança de permissões do diretório pai e concede acesso apenas
    ao usuário atual e SYSTEM. Isto impede que outros usuários da máquina
    leiam o JWT secret e a chave de federação.

    Silenciosamente falha se icacls não estiver disponível (Windows antigo)
    — o diretório ainda é criado, apenas sem restrição extra.
    """
    if os.name != "nt":
        return
    try:
        # Pega o nome do usuário atual
        import getpass
        username = getpass.getuser()

        # Desabilita herança e remove ACEs existentes, depois adiciona
        # apenas o usuário atual e SYSTEM com acesso total
        subprocess.run(
            [
                "icacls", str(path),
                "/inheritance:r",
                "/grant:r", f"{username}:(OI)(CI)F",
                "/grant:r", "SYSTEM:(OI)(CI)F",
            ],
            check=True,
            capture_output=True,
            timeout=10,
        )
        logger.info("Permissões do diretório %s restritas ao usuário atual (Windows ACL)", path)
    except subprocess.CalledProcessError as e:
        logger.warning(
            "Falha ao restringir permissões do diretório %s via icacls: %s. "
            "O diretório está acessível a outros usuários da máquina.",
            path, e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e),
        )
    except FileNotFoundError:
        # icacls não encontrado (Windows muito antigo?) — silencia
        logger.debug("icacls não disponível — pulando restrição de permissões no Windows")
    except Exception as e:
        logger.warning("Erro inesperado ao restringir permissões no Windows: %s", e)


def _restrict_file_windows(path):
    """
    T2-FIX: restringe acesso a um arquivo específico no Windows via icacls.

    Mesma lógica de _restrict_dir_windows mas para arquivo individual.
    Usado para o JWT secret e a chave de federação (que são arquivos, não
    diretórios).

    Aceita str ou Path.
    """
    if os.name != "nt":
        return
    try:
        import getpass
        username = getpass.getuser()

        subprocess.run(
            [
                "icacls", str(path),
                "/inheritance:r",
                "/grant:r", f"{username}:F",
                "/grant:r", "SYSTEM:F",
            ],
            check=True,
            capture_output=True,
            timeout=10,
        )
        logger.debug("Permissões do arquivo %s restritas ao usuário atual (Windows ACL)", path)
    except Exception as e:
        logger.debug("Falha ao restringir arquivo %s no Windows: %s", path, e)


def _candidate_dirs() -> list:
    """Lista de diretórios candidatos a base de dados, em ordem de preferência."""
    candidates = []

    env_dir = os.getenv("CHATPY_DATA_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    # Diretório do projeto (parent do diretório server/)
    # Em dev isto é o clone do repositório; em produção (Docker) é /app
    try:
        server_dir = Path(__file__).resolve().parent
        project_dir = server_dir.parent
        if project_dir.exists() and os.access(project_dir, os.W_OK):
            candidates.append(project_dir)
    except Exception:
        pass

    # Fallback universal: ~/.chatpy/
    candidates.append(Path.home() / ".chatpy")

    return candidates


_data_dir: Optional[Path] = None


def get_data_dir() -> Path:
    """
    Retorna o diretório base onde arquivos persistentes devem ser gravados.
    Cria o diretório se não existir. Garante permissões 0700 no Unix.
    """
    global _data_dir
    if _data_dir is not None:
        return _data_dir

    for candidate in _candidate_dirs():
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            # Testa escrita efetiva
            test_file = candidate / ".chatpy_write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
            _data_dir = candidate
            # Restringe permissões no Unix
            if os.name != "nt":
                try:
                    os.chmod(candidate, 0o700)
                except OSError:
                    pass
            else:
                # T2-FIX: no Windows, os.chmod não restringe efetivamente o
                # acesso ao arquivo (Windows usa ACLs, não POSIX mode bits).
                # Usamos icacls via subprocess para restringir o diretório
                # ao usuário atual e SYSTEM. Sem isto, qualquer usuário da
                # máquina pode ler o JWT secret e a chave de federação.
                _restrict_dir_windows(candidate)
            return _data_dir
        except (OSError, PermissionError):
            continue

    # Último recurso: diretório atual (pode quebrar consistência mas ao
    # menos não impede o servidor de iniciar)
    _data_dir = Path.cwd()
    return _data_dir


def resolve(filename: str) -> Path:
    """
    Resolve um nome de arquivo relativo ao diretório base de dados.
    Retorna o caminho absoluto.
    """
    return get_data_dir() / filename


# Conveniências para os arquivos mais comuns
def auto_secret_path() -> Path:
    """Caminho do arquivo .chatpy_auto_secret (JWT_SECRET auto-gerado)."""
    return resolve(".chatpy_auto_secret")


def federation_key_path() -> Path:
    """Caminho do arquivo .chatpy_federation_key.pem (chave Ed25519)."""
    return resolve(".chatpy_federation_key.pem")


def cli_theme_path() -> Path:
    """
    Tema da CLI — tentamos manter no diretório de dados para consistência
    entre execuções a partir de cwd diferentes. O código legado em
    views/interface.py lê de um path diferente — atualizamos para usar
    este helper.
    """
    return resolve("cli_theme.txt")


def cli_history_cache_path(username: str) -> Path:
    """
    Cache de histórico da CLI por usuário (paridade com Desktop que já tem
    history_cache_<user>.json em models/state.py).
    """
    import re
    safe = re.sub(r"[^A-Za-z0-9_-]", "", username) or "default"
    return resolve(f"cli_history_cache_{safe}.json")
