"""
Helper de threading unificado para o cliente Desktop.

P1-5: Centraliza o pattern de "rodar função bloqueante em background e
notificar a UI thread via signal". Antes deste helper, o pattern
`def worker(): try: ... except Exception as e: ...; threading.Thread(
target=worker, daemon=True).start()` era repetido ~15 vezes em
main_window.py e chat_controller.py.

Este módulo oferece:
  - run_in_background(func, on_success, on_error): roda func em QThreadPool
    (limite de concorrência controlado pelo Qt) e emite signals tipados
    para a UI thread.
  - O caller passa os signals Qt a serem emitidos (ou callbacks opcionais).
"""
from __future__ import annotations

import logging
from typing import Callable, Any, Optional, TypeVar

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)

T = TypeVar("T")


class _BackgroundTaskSignals(QObject):
    """
    Signals emitidos por uma tarefa em background.
    Conectados a slots na UI thread para marshalling thread-safe.
    """
    finished = Signal(object)  # resultado de func
    error = Signal(str)        # mensagem de erro
    # `object` em vez de `T` porque PySide6 não suporta generic signals


class _BackgroundTask(QRunnable):
    """
    QRunnable que executa `func` em background e emite signals ao terminar.
    """
    def __init__(
        self,
        func: Callable[..., T],
        *args,
        on_success: Optional[Callable[[T], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        **kwargs,
    ):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self._on_success = on_success
        self._on_error = on_error
        self.signals = _BackgroundTaskSignals()

    @Slot()
    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            if self._on_success is not None:
                self.signals.finished.connect(self._on_success)
            self.signals.finished.emit(result)
        except Exception as e:
            logger.exception("Erro em tarefa background: %s", e)
            if self._on_error is not None:
                self.signals.error.connect(self._on_error)
            self.signals.error.emit(str(e))


# ThreadPool global — Qt gerencia concorrência (default: 4 threads simultâneas)
_thread_pool = QThreadPool.globalInstance()
# Aumenta um pouco o limite padrão para evitar starvation em operações de rede
_thread_pool.setMaxThreadCount(max(_thread_pool.maxThreadCount(), 8))


def run_in_background(
    func: Callable[..., T],
    *args,
    on_success: Optional[Callable[[T], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    **kwargs,
) -> _BackgroundTask:
    """
    Roda `func(*args, **kwargs)` em background (QThreadPool) e chama
    `on_success(result)` ou `on_error(error_message)` na UI thread quando
    termina.

    Os callbacks são conectados a signals Qt e disparados via
    `QueuedConnection` implícita — logo executam na thread do QObject
    receptor (geralmente a UI thread).

    Retorna o QRunnable criado (raramente necessário — uso principal é
    fire-and-forget).
    """
    task = _BackgroundTask(func, *args, on_success=on_success,
                           on_error=on_error, **kwargs)
    _thread_pool.start(task)
    return task


def run_in_background_with_signal(
    func: Callable[..., T],
    finished_signal: Signal,
    error_signal: Optional[Signal] = None,
    *args,
    **kwargs,
) -> _BackgroundTask:
    """
    Variante para uso com signals existentes (em vez de callbacks).

    Exemplo:
        self.image_downloaded_signal = Signal(str, bytes)
        run_in_background_with_signal(
            download_image,
            self.image_downloaded_signal,
            args=(url,),
        )
    """
    task = _BackgroundTask(func, *args, **kwargs)
    task.signals.finished.connect(finished_signal)
    if error_signal is not None:
        task.signals.error.connect(error_signal)
    _thread_pool.start(task)
    return task
