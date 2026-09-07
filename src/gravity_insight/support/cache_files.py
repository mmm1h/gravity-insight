"""Metadata-only allocation accounting and bounded, identity-checked deletion."""

from __future__ import annotations

import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator


def linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


def identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink)


def assert_unlinked(path: Path) -> None:
    for part in (*reversed(path.parents), path):
        if linked(part.lstat()):
            raise OSError("CACHE_LINK_REFUSED")


def allocated_bytes(path: Path, info: os.stat_result) -> int | None:
    if hasattr(info, "st_blocks"):
        return info.st_blocks * 512
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class StandardInfo(ctypes.Structure):
        _fields_ = [("allocation", ctypes.c_longlong), ("size", ctypes.c_longlong),
                    ("links", wintypes.DWORD), ("deleting", ctypes.c_ubyte),
                    ("directory", ctypes.c_ubyte)]

    try:
        with _windows_handle(path) as (kernel, handle):
            value = StandardInfo()
            if not kernel.GetFileInformationByHandleEx(
                handle, 1, ctypes.byref(value), ctypes.sizeof(value)
            ):
                return None
            return value.allocation
    except OSError:
        return None


@contextmanager
def _windows_handle(path: Path, *, delete: bool = False) -> Iterator[tuple]:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD]
    # No FILE_SHARE_DELETE: pin every ancestor and the final file while deleting.
    handle = kernel.CreateFileW(str(path), 0x80 | (0x10000 if delete else 0),
                                3, None, 3, 0x02200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise OSError("CACHE_FILE_IN_USE_OR_INACCESSIBLE")
    try:
        yield kernel, handle
    finally:
        kernel.CloseHandle(handle)


def unlink_unchanged(root: Path, path: Path, expected: os.stat_result) -> None:
    """Delete only a regular single-link file within the checked root.

    Windows pins ancestors against rename/reparse substitution; POSIX traverses
    through no-follow directory descriptors and unlinks relative to the parent.
    """

    relative = path.relative_to(root)
    if not relative.parts or ".." in relative.parts:
        raise OSError("CACHE_OUTSIDE_ROOT")
    if os.name == "nt":
        import ctypes

        with ExitStack() as stack:
            for parent in reversed(path.parents):
                stack.enter_context(_windows_handle(parent))
                if linked(parent.lstat()):
                    raise OSError("CACHE_LINK_REFUSED")
            kernel, handle = stack.enter_context(_windows_handle(path, delete=True))
            _check_file(path.lstat(), expected)
            delete = ctypes.c_ubyte(1)
            if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), 1):
                raise OSError("CACHE_DELETE_FAILED")
        return
    with ExitStack() as stack:
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, descriptor)
        for name in path.parts[1:-1]:
            descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                 dir_fd=descriptor)
            stack.callback(os.close, descriptor)
        info = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        _check_file(info, expected)
        os.unlink(path.name, dir_fd=descriptor)


def _check_file(actual: os.stat_result, expected: os.stat_result) -> None:
    if (linked(actual) or not stat.S_ISREG(actual.st_mode)
            or actual.st_nlink != 1 or identity(actual) != identity(expected)):
        raise OSError("CACHE_FILE_CHANGED")
