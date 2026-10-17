"""Shut the desktop sidecar down when the Electron process that launched it is gone.

Electron spawns the sidecar with stdin as a pipe it never writes to. However
Electron exits (crash, kill, force-quit), the OS closes its end and a read on
ours returns EOF. That works the same on Windows, Linux and macOS, unlike
signals. A poll of the parent PID backs it up in case stdin can't be read.
"""

import logging
import os
import threading
from collections.abc import Callable

import psutil

logger = logging.getLogger(__name__)


class ParentWatchdog:
    """Calls *on_parent_gone* once, when stdin hits EOF or the parent process exits.

    If the process is still alive *grace_secs* later (graceful shutdown hung),
    *hard_exit* ends it, since an orphaned backend is what this exists to prevent.
    """

    def __init__(
        self,
        on_parent_gone: Callable[[], None],
        *,
        parent_pid: int,
        stdin_fd: int | None = 0,
        poll_interval: float = 2.0,
        grace_secs: float = 90.0,
        hard_exit: Callable[[int], object] = os._exit,
    ):
        self._on_parent_gone = on_parent_gone
        self._parent_pid = parent_pid
        self._stdin_fd = stdin_fd
        self._poll_interval = poll_interval
        self._grace_secs = grace_secs
        self._hard_exit = hard_exit
        self._fired = threading.Event()
        self._lock = threading.Lock()

    @property
    def fired(self) -> bool:
        return self._fired.is_set()

    def start(self) -> None:
        try:
            # Process identity includes its start time, so a reused PID isn't mistaken for it.
            parent: psutil.Process | None = psutil.Process(self._parent_pid)
        except psutil.Error:
            parent = None
        if parent is None:
            self._trigger(f"parent process {self._parent_pid} is not running")
            return
        threading.Thread(
            target=self._poll_parent, args=(parent,), name="parent-watchdog-pid", daemon=True
        ).start()
        if self._stdin_fd is not None:
            threading.Thread(
                target=self._watch_stdin, name="parent-watchdog-stdin", daemon=True
            ).start()

    def _watch_stdin(self) -> None:
        assert self._stdin_fd is not None
        try:
            while os.read(self._stdin_fd, 4096):
                pass  # Electron never writes; ignore anything that arrives.
        except OSError as exc:
            logger.warning(
                "Cannot watch stdin for the desktop app exiting (%s); polling its PID only", exc
            )
            return
        self._trigger("stdin closed")

    def _poll_parent(self, parent: psutil.Process) -> None:
        while not self._fired.wait(self._poll_interval):
            try:
                # An exited parent can linger as a zombie until its own parent reaps it.
                alive = parent.is_running() and parent.status() != psutil.STATUS_ZOMBIE
            except psutil.Error:
                alive = False
            if not alive:
                self._trigger(f"parent process {self._parent_pid} exited")
                return

    def _trigger(self, reason: str) -> None:
        with self._lock:
            if self._fired.is_set():
                return
            self._fired.set()
        logger.warning("Desktop app is gone (%s); shutting down", reason)
        threading.Thread(
            target=self._backstop, name="parent-watchdog-backstop", daemon=True
        ).start()
        self._on_parent_gone()

    def _backstop(self) -> None:
        threading.Event().wait(self._grace_secs)
        logger.critical("Graceful shutdown took over %ss; exiting", self._grace_secs)
        self._hard_exit(1)
