"""Windows facts and process control through ctypes (no psutil, no pywin32).

* ``Job``: a job object with KILL_ON_JOB_CLOSE. The server process is put in one,
  so if the controller dies (or its scheduled task is ended) Windows ends the
  server too and no orphan keeps port 8742.
* ``process_usage``: working set, private bytes and CPU seconds of a process.
* ``service_state``: 'running', 'stopped', ... or 'missing' / 'unknown'.

Every function degrades to a harmless answer on other platforms so the tests and
the manager can import this module anywhere.
"""
from __future__ import annotations

import ctypes
import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _adv = ctypes.WinDLL("advapi32", use_last_error=True)

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMIT(ctypes.Structure):
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

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMIT),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _PMC_EX(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]

    class _SERVICE_STATUS(ctypes.Structure):
        _fields_ = [(n, wintypes.DWORD) for n in (
            "dwServiceType", "dwCurrentState", "dwControlsAccepted", "dwWin32ExitCode",
            "dwServiceSpecificExitCode", "dwCheckPoint", "dwWaitHint")]

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                             wintypes.DWORD]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    _k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC_EX),
                                             wintypes.DWORD]
    _k32.GetProcessTimes.restype = wintypes.BOOL
    _k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _adv.OpenSCManagerW.restype = wintypes.HANDLE
    _adv.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    _adv.OpenServiceW.restype = wintypes.HANDLE
    _adv.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    _adv.QueryServiceStatus.restype = wintypes.BOOL
    _adv.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(_SERVICE_STATUS)]
    _adv.CloseServiceHandle.argtypes = [wintypes.HANDLE]

_JOB_EXTENDED_LIMIT_INFORMATION = 9
_KILL_ON_JOB_CLOSE = 0x2000


class Job:
    """A job object whose processes all end when the last handle closes."""

    def __init__(self) -> None:
        self._handle = None
        if not IS_WINDOWS:
            return
        handle = _k32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(handle, _JOB_EXTENDED_LIMIT_INFORMATION,
                                            ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            _k32.CloseHandle(handle)
            raise ctypes.WinError(err)
        self._handle = handle

    def assign(self, process_handle: int) -> None:
        if self._handle and not _k32.AssignProcessToJobObject(self._handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self, code: int = 1) -> None:
        if self._handle:
            _k32.TerminateJobObject(self._handle, code)

    def close(self) -> None:
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None


def process_usage(process_handle: int) -> dict | None:
    """``{working_set_mb, private_mb, cpu_seconds}`` or None if it cannot be read."""
    if not IS_WINDOWS:
        return None
    h = wintypes.HANDLE(int(process_handle))
    pmc = _PMC_EX()
    pmc.cb = ctypes.sizeof(pmc)
    if not _k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
        return None
    created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
    cpu = None
    if _k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                            ctypes.byref(kernel), ctypes.byref(user)):
        def ticks(ft):  # 100-nanosecond units
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        cpu = (ticks(kernel) + ticks(user)) / 10_000_000.0
    return {"working_set_mb": round(pmc.WorkingSetSize / 1048576, 1),
            "private_mb": round(pmc.PrivateUsage / 1048576, 1),
            "cpu_seconds": cpu}


_SERVICE_STATES = {1: "stopped", 2: "starting", 3: "stopping", 4: "running",
                   5: "continuing", 6: "pausing", 7: "paused"}


def service_state(name: str) -> str:
    """State of a Windows service. Needs no special rights."""
    if not IS_WINDOWS or not name:
        return "unknown"
    scm = _adv.OpenSCManagerW(None, None, 0x0001)          # SC_MANAGER_CONNECT
    if not scm:
        return "unknown"
    try:
        svc = _adv.OpenServiceW(scm, name, 0x0004)         # SERVICE_QUERY_STATUS
        if not svc:
            return "missing" if ctypes.get_last_error() == 1060 else "unknown"
        try:
            st = _SERVICE_STATUS()
            if not _adv.QueryServiceStatus(svc, ctypes.byref(st)):
                return "unknown"
            return _SERVICE_STATES.get(st.dwCurrentState, "unknown")
        finally:
            _adv.CloseServiceHandle(svc)
    finally:
        _adv.CloseServiceHandle(scm)
