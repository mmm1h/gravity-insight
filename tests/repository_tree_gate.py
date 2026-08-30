"""Cross-process reader/writer gate for tests that inspect the repository tree."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import BinaryIO, Iterator, Literal


DEFAULT_TIMEOUT_SECONDS = 120.0
_POLL_INTERVAL_SECONDS = 0.01
_PROCESS_LOCKS = threading.local()


class RepositoryTreeGateError(RuntimeError):
    """Raised when repository tree coordination cannot be trusted."""


class RepositoryTreeGateTimeout(RepositoryTreeGateError, TimeoutError):
    """Raised instead of continuing when repository tree coordination times out."""


def _lock_paths(root: Path) -> tuple[Path, Path]:
    identity = os.path.normcase(str(root.resolve())).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:24]
    directory = Path(tempfile.gettempdir()) / "gravity-insight-repository-tree-gates"
    directory.mkdir(parents=True, exist_ok=True)
    return (
        directory / f"{digest}.turnstile.lock",
        directory / f"{digest}.access.lock",
    )


def _open_lock(path: Path) -> BinaryIO:
    stream = path.open("a+b", buffering=0)
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"\0")
    stream.seek(0)
    return stream


def _try_lock(stream: BinaryIO, *, shared: bool) -> bool:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        mode = msvcrt.LK_NBRLCK if shared else msvcrt.LK_NBLCK
        try:
            msvcrt.locking(stream.fileno(), mode, 1)
            return True
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return False
            raise

    import fcntl

    mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    try:
        fcntl.flock(stream.fileno(), mode | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock(stream: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _acquire(
    stream: BinaryIO,
    *,
    shared: bool,
    deadline: float,
    timeout_seconds: float,
    mode: str,
    stage: str,
    purpose: str,
    root: Path,
    lock_path: Path,
) -> None:
    while True:
        try:
            if _try_lock(stream, shared=shared):
                return
        except OSError as exc:
            raise RepositoryTreeGateError(
                f"failed closed acquiring {mode} repository tree gate for "
                f"{purpose!r} at {stage}; root={root} lock={lock_path}: {exc}"
            ) from exc
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RepositoryTreeGateTimeout(
                f"timed out after {timeout_seconds:.3f}s acquiring {mode} "
                f"repository tree gate for {purpose!r} at {stage}; "
                f"root={root} lock={lock_path}"
            )
        time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))


def _held_modes() -> dict[Path, Literal["shared", "exclusive"]]:
    held = getattr(_PROCESS_LOCKS, "held", None)
    if held is None:
        held = {}
        _PROCESS_LOCKS.held = held
    return held


@contextmanager
def _repository_tree_gate(
    *,
    root: Path,
    purpose: str,
    mode: Literal["shared", "exclusive"],
    timeout_seconds: float,
) -> Iterator[None]:
    resolved = root.resolve()
    if not purpose.strip():
        raise ValueError("repository tree gate purpose must be non-empty")
    if timeout_seconds <= 0:
        raise ValueError("repository tree gate timeout_seconds must be positive")

    held = _held_modes()
    current = held.get(resolved)
    if current is not None:
        if current == "shared" and mode == "exclusive":
            raise RepositoryTreeGateError(
                f"cannot upgrade shared repository tree gate to exclusive for "
                f"{purpose!r}; root={resolved}"
            )
        yield
        return

    turnstile_path, access_path = _lock_paths(resolved)
    turnstile = _open_lock(turnstile_path)
    try:
        access = _open_lock(access_path)
    except BaseException:
        turnstile.close()
        raise
    deadline = time.monotonic() + timeout_seconds
    turnstile_locked = False
    access_locked = False
    try:
        _acquire(
            turnstile,
            shared=False,
            deadline=deadline,
            timeout_seconds=timeout_seconds,
            mode=mode,
            stage="writer-fair turnstile",
            purpose=purpose,
            root=resolved,
            lock_path=turnstile_path,
        )
        turnstile_locked = True
        _acquire(
            access,
            shared=mode == "shared",
            deadline=deadline,
            timeout_seconds=timeout_seconds,
            mode=mode,
            stage="shared/exclusive access",
            purpose=purpose,
            root=resolved,
            lock_path=access_path,
        )
        access_locked = True
        if mode == "shared":
            _unlock(turnstile)
            turnstile_locked = False
        held[resolved] = mode
        try:
            yield
        finally:
            del held[resolved]
    finally:
        if access_locked:
            _unlock(access)
        access.close()
        if turnstile_locked:
            _unlock(turnstile)
        turnstile.close()


def repository_tree_read(
    *,
    root: Path,
    purpose: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Hold shared repository access or fail closed within ``timeout_seconds``."""
    return _repository_tree_gate(
        root=root,
        purpose=purpose,
        mode="shared",
        timeout_seconds=timeout_seconds,
    )


def repository_tree_write(
    *,
    root: Path,
    purpose: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Hold exclusive repository access or fail closed within ``timeout_seconds``."""
    return _repository_tree_gate(
        root=root,
        purpose=purpose,
        mode="exclusive",
        timeout_seconds=timeout_seconds,
    )
