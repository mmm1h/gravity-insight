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


def allocation_units(path: Path) -> dict[str, int | None]:
    """Query volume metadata; do not infer cluster or resident-record sizes."""
    result = {"cluster_bytes": None, "resident_record_bytes": None}
    if os.name != "nt":
        return result
    import ctypes
    from ctypes import wintypes

    class NtfsVolumeData(ctypes.Structure):
        _fields_ = [("serial", ctypes.c_longlong), ("sectors", ctypes.c_longlong),
                    ("clusters", ctypes.c_longlong), ("free", ctypes.c_longlong),
                    ("reserved", ctypes.c_longlong), ("sector_bytes", wintypes.DWORD),
                    ("cluster_bytes", wintypes.DWORD), ("record_bytes", wintypes.DWORD),
                    ("record_clusters", wintypes.DWORD), ("mft_size", ctypes.c_longlong),
                    ("mft_start", ctypes.c_longlong), ("mft_mirror", ctypes.c_longlong),
                    ("mft_zone_start", ctypes.c_longlong), ("mft_zone_end", ctypes.c_longlong)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumeNameForVolumeMountPointW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetDiskFreeSpaceW.argtypes = [wintypes.LPCWSTR] + [ctypes.POINTER(wintypes.DWORD)] * 4
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    volume = ctypes.create_unicode_buffer(32768)
    if not kernel.GetVolumePathNameW(str(path), volume, len(volume)):
        return result
    space = [wintypes.DWORD() for _ in range(4)]
    if kernel.GetDiskFreeSpaceW(volume.value, *(ctypes.byref(value) for value in space)):
        result["cluster_bytes"] = space[0].value * space[1].value or None
    name = ctypes.create_unicode_buffer(32768)
    if not kernel.GetVolumeNameForVolumeMountPointW(volume.value, name, len(name)):
        return result
    # FSCTL_GET_NTFS_VOLUME_DATA requires read access to the volume, not its files.
    handle = kernel.CreateFileW(name.value.rstrip("\\"), 0x80000000, 7, None, 3, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        return result
    try:
        value, returned = NtfsVolumeData(), wintypes.DWORD()
        if kernel.DeviceIoControl(handle, 0x90064, None, 0, ctypes.byref(value),
                                  ctypes.sizeof(value), ctypes.byref(returned), None):
            result["resident_record_bytes"] = value.record_bytes or None
    finally:
        kernel.CloseHandle(handle)
    return result


def allocated_bytes(path: Path, info: os.stat_result, *, metadata_only: bool = False) -> int | None:
    if hasattr(info, "st_blocks"):
        return info.st_blocks * 512
    if os.name != "nt":
        return None
    if metadata_only:
        return _directory_allocation(path, info)
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


def _directory_allocation(path: Path, info: os.stat_result) -> int | None:
    """Query the parent directory, never open the sensitive child file."""
    import ctypes
    from ctypes import wintypes

    class FullDirectoryInfo(ctypes.Structure):
        _fields_ = [("next", wintypes.DWORD), ("index", wintypes.DWORD),
                    ("created", ctypes.c_longlong), ("accessed", ctypes.c_longlong),
                    ("written", ctypes.c_longlong), ("changed", ctypes.c_longlong),
                    ("size", ctypes.c_longlong), ("allocation", ctypes.c_longlong),
                    ("attributes", wintypes.DWORD), ("name_bytes", wintypes.DWORD),
                    ("ea_size", wintypes.DWORD), ("name", wintypes.WCHAR * 1)]

    try:
        with _windows_handle(path.parent, list_directory=True) as (kernel, handle):
            buffer = ctypes.create_string_buffer(65536)
            while kernel.GetFileInformationByHandleEx(handle, 14, buffer, len(buffer)):
                offset = 0
                while True:
                    value = FullDirectoryInfo.from_buffer(buffer, offset)
                    name = ctypes.wstring_at(ctypes.addressof(buffer) + offset + FullDirectoryInfo.name.offset,
                                             value.name_bytes // ctypes.sizeof(wintypes.WCHAR))
                    if name == path.name:
                        return value.allocation if value.size == info.st_size else None
                    if not value.next:
                        break
                    offset += value.next
    except OSError:
        pass
    return None


@contextmanager
def _windows_handle(path: Path, *, delete: bool = False, list_directory: bool = False) -> Iterator[tuple]:
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
    handle = kernel.CreateFileW(str(path), 0x80 | (0x10000 if delete else 0) | int(list_directory),
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
