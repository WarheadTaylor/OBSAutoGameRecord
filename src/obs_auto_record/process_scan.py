from __future__ import annotations

from ctypes import POINTER, Structure, WinDLL, byref, c_size_t, c_void_p, sizeof
from ctypes.wintypes import BOOL, DWORD, HANDLE, LONG, WCHAR
from dataclasses import dataclass


TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = c_void_p(-1).value
MAX_PATH = 260


@dataclass(frozen=True)
class RunningProcess:
    pid: int
    exe_name: str


class PROCESSENTRY32W(Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("cntUsage", DWORD),
        ("th32ProcessID", DWORD),
        ("th32DefaultHeapID", c_size_t),
        ("th32ModuleID", DWORD),
        ("cntThreads", DWORD),
        ("th32ParentProcessID", DWORD),
        ("pcPriClassBase", LONG),
        ("dwFlags", DWORD),
        ("szExeFile", WCHAR * MAX_PATH),
    ]


kernel32 = WinDLL("kernel32", use_last_error=True)
CreateToolhelp32Snapshot = kernel32.CreateToolhelp32Snapshot
CreateToolhelp32Snapshot.argtypes = [DWORD, DWORD]
CreateToolhelp32Snapshot.restype = HANDLE

Process32FirstW = kernel32.Process32FirstW
Process32FirstW.argtypes = [HANDLE, POINTER(PROCESSENTRY32W)]
Process32FirstW.restype = BOOL

Process32NextW = kernel32.Process32NextW
Process32NextW.argtypes = [HANDLE, POINTER(PROCESSENTRY32W)]
Process32NextW.restype = BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [HANDLE]
CloseHandle.restype = BOOL


def iter_processes() -> list[RunningProcess]:
    snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise OSError("CreateToolhelp32Snapshot failed.")

    entry = PROCESSENTRY32W()
    entry.dwSize = sizeof(PROCESSENTRY32W)
    processes: list[RunningProcess] = []

    try:
        success = Process32FirstW(snapshot, byref(entry))
        while success:
            exe_name = entry.szExeFile.lower()
            processes.append(RunningProcess(pid=int(entry.th32ProcessID), exe_name=exe_name))
            success = Process32NextW(snapshot, byref(entry))
    finally:
        CloseHandle(snapshot)

    return processes
