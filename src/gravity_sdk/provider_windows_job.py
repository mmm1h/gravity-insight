"""Private Windows Job Object lifecycle for subprocess Provider trees."""

from __future__ import annotations

import os
from typing import Any


_JOB_ATTRIBUTE = "_gravity_provider_job"
_CREATE_SUSPENDED = 0x00000004


def windows_job_creation_flags() -> int:
    """Create Windows Providers suspended until their Job assignment succeeds."""

    return _CREATE_SUSPENDED if os.name == "nt" else 0


def attach_windows_job(process: Any) -> bool:
    """Attach a suspended Provider before it can spawn descendants."""

    if os.name != "nt":
        return False
    return _attach_windows_job(process)


def resume_windows_job_process(process: Any) -> bool:
    """Resume a Provider only after its kill-on-close Job is attached."""

    if os.name != "nt":
        return False
    return _resume_windows_job_process(process)


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
    _TH32CS_SNAPTHREAD = 0x00000004
    _THREAD_SUSPEND_RESUME = 0x0002
    _ERROR_NO_MORE_FILES = 18
    _RESUME_FAILED = 0xFFFFFFFF
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

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

    class _ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
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
    _CREATE_THREAD_SNAPSHOT = _KERNEL32.CreateToolhelp32Snapshot
    _CREATE_THREAD_SNAPSHOT.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _CREATE_THREAD_SNAPSHOT.restype = wintypes.HANDLE
    _THREAD_FIRST = _KERNEL32.Thread32First
    _THREAD_FIRST.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    _THREAD_FIRST.restype = wintypes.BOOL
    _THREAD_NEXT = _KERNEL32.Thread32Next
    _THREAD_NEXT.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    _THREAD_NEXT.restype = wintypes.BOOL
    _OPEN_THREAD = _KERNEL32.OpenThread
    _OPEN_THREAD.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _OPEN_THREAD.restype = wintypes.HANDLE
    _RESUME_THREAD = _KERNEL32.ResumeThread
    _RESUME_THREAD.argtypes = [wintypes.HANDLE]
    _RESUME_THREAD.restype = wintypes.DWORD

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

    def _resume_windows_job_process(process: Any) -> bool:
        handles = _suspended_process_threads(int(process.pid))
        if not handles:
            return False
        resumed = True
        try:
            for handle in handles:
                if _RESUME_THREAD(handle) == _RESUME_FAILED:
                    resumed = False
                    break
        finally:
            for handle in handles:
                _CLOSE_HANDLE(handle)
        return resumed

    def _suspended_process_threads(process_id: int) -> list[Any] | None:
        snapshot = _CREATE_THREAD_SNAPSHOT(_TH32CS_SNAPTHREAD, 0)
        if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
            return None
        thread_ids: list[int] = []
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            available = bool(_THREAD_FIRST(snapshot, ctypes.byref(entry)))
            while available:
                if int(entry.th32OwnerProcessID) == process_id:
                    thread_ids.append(int(entry.th32ThreadID))
                ctypes.set_last_error(0)
                available = bool(_THREAD_NEXT(snapshot, ctypes.byref(entry)))
            if ctypes.get_last_error() not in {0, _ERROR_NO_MORE_FILES}:
                return None
        finally:
            _CLOSE_HANDLE(snapshot)
        handles: list[Any] = []
        for thread_id in thread_ids:
            handle = _OPEN_THREAD(_THREAD_SUSPEND_RESUME, False, thread_id)
            if not handle:
                for opened in handles:
                    _CLOSE_HANDLE(opened)
                return None
            handles.append(handle)
        return handles or None

else:
    _CLOSE_HANDLE = None

    def _attach_windows_job(process: Any) -> bool:
        return False

    def _resume_windows_job_process(process: Any) -> bool:
        return False


__all__ = [
    "attach_windows_job",
    "close_windows_job",
    "resume_windows_job_process",
    "windows_job_creation_flags",
]
