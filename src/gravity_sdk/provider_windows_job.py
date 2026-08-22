"""Private Windows Job Object lifecycle for subprocess Provider trees."""

from __future__ import annotations

import os
from typing import Any


_JOB_ATTRIBUTE = "_gravity_provider_job"


def attach_windows_job(process: Any) -> bool:
    """Attach a just-launched Provider before it can spawn descendants."""

    if os.name != "nt":
        return False
    return _attach_windows_job(process)


def close_windows_job(process: Any) -> bool:
    """Close one assigned job exactly once, terminating every descendant."""

    if os.name != "nt":
        return False
    handle = getattr(process, _JOB_ATTRIBUTE, None)
    if handle is None:
        return False
    setattr(process, _JOB_ATTRIBUTE, None)
    return bool(_CLOSE_HANDLE(handle))


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CREATE_JOB = _KERNEL32.CreateJobObjectW
    _CREATE_JOB.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _CREATE_JOB.restype = wintypes.HANDLE
    _SET_JOB = _KERNEL32.SetInformationJobObject
    _SET_JOB.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _SET_JOB.restype = wintypes.BOOL
    _ASSIGN_JOB = _KERNEL32.AssignProcessToJobObject
    _ASSIGN_JOB.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _ASSIGN_JOB.restype = wintypes.BOOL
    _CLOSE_HANDLE = _KERNEL32.CloseHandle
    _CLOSE_HANDLE.argtypes = [wintypes.HANDLE]
    _CLOSE_HANDLE.restype = wintypes.BOOL

    def _attach_windows_job(process: Any) -> bool:
        job = _CREATE_JOB(None, None)
        if not job:
            return False
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = _SET_JOB(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        process_handle = wintypes.HANDLE(int(getattr(process, "_handle")))
        if not configured or not _ASSIGN_JOB(job, process_handle):
            _CLOSE_HANDLE(job)
            return False
        setattr(process, _JOB_ATTRIBUTE, job)
        return True

else:
    _CLOSE_HANDLE = None

    def _attach_windows_job(process: Any) -> bool:
        return False


__all__ = ["attach_windows_job", "close_windows_job"]
