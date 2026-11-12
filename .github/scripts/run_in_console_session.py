# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run one command in the logged-on desktop session of a Windows CI runner.

The GitHub runner service runs each job as SYSTEM in session 0. In session 0,
the WebRTC and native servers of StreamSDK (ovstream) cannot create their
Direct3D device (NVST_DISCONN_SERVER_VIDEO_ADAPTER_INITIALIZE_D3D_FAILED). This
script starts the command as the user who is logged on to the active console
session (WTSQueryUserToken and CreateProcessAsUserW on winsta0\\default), with
that user's environment and the job variables named with --env. The output of
the command goes to the log file; the script prints it while the command runs
and returns the exit status of the command. The user must be able to read the
files of the command and to write the log file.

It needs SeTcbPrivilege, which SYSTEM has. When no user is logged on to the
console, it fails with that cause.

Usage:
    python run_in_console_session.py --log FILE [--cwd DIR] [--env NAME]...
        [--timeout SECONDS] -- PROGRAM [ARGUMENT]...
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

MAXIMUM_ALLOWED = 0x02000000
SECURITY_IMPERSONATION = 2
TOKEN_PRIMARY = 1
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x00000002
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NEW_CONSOLE = 0x00000010
NO_CONSOLE_SESSION = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x00000102


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]


def _windows_api():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
    uenv = ctypes.WinDLL("userenv", use_last_error=True)
    HANDLE, DWORD, BOOL = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    k32.GetCurrentProcess.argtypes = []
    k32.GetCurrentProcess.restype = HANDLE
    k32.WTSGetActiveConsoleSessionId.argtypes = []
    k32.WTSGetActiveConsoleSessionId.restype = DWORD
    k32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
    k32.WaitForSingleObject.restype = DWORD
    k32.GetExitCodeProcess.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
    k32.GetExitCodeProcess.restype = BOOL
    k32.CloseHandle.argtypes = [HANDLE]
    k32.CloseHandle.restype = BOOL
    adv.OpenProcessToken.argtypes = [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
    adv.OpenProcessToken.restype = BOOL
    adv.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
    adv.LookupPrivilegeValueW.restype = BOOL
    adv.AdjustTokenPrivileges.argtypes = [
        HANDLE, BOOL, ctypes.POINTER(TOKEN_PRIVILEGES), DWORD, ctypes.c_void_p, ctypes.c_void_p,
    ]
    adv.AdjustTokenPrivileges.restype = BOOL
    adv.DuplicateTokenEx.argtypes = [
        HANDLE, DWORD, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(HANDLE),
    ]
    adv.DuplicateTokenEx.restype = BOOL
    adv.CreateProcessAsUserW.argtypes = [
        HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, BOOL, DWORD,
        ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    adv.CreateProcessAsUserW.restype = BOOL
    wts.WTSQueryUserToken.argtypes = [wintypes.ULONG, ctypes.POINTER(HANDLE)]
    wts.WTSQueryUserToken.restype = BOOL
    uenv.CreateEnvironmentBlock.argtypes = [ctypes.POINTER(ctypes.c_void_p), HANDLE, BOOL]
    uenv.CreateEnvironmentBlock.restype = BOOL
    uenv.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]
    uenv.DestroyEnvironmentBlock.restype = BOOL
    return k32, adv, wts, uenv


def _check(ok, what: str) -> None:
    if not ok:
        error = ctypes.get_last_error()
        raise OSError(error, f"{what} failed: {ctypes.FormatError(error).strip()}")


def _enable_privilege(k32, adv, name: str) -> None:
    token = wintypes.HANDLE()
    _check(adv.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                ctypes.byref(token)), "OpenProcessToken")
    try:
        luid = LUID()
        _check(adv.LookupPrivilegeValueW(None, name, ctypes.byref(luid)), f"LookupPrivilegeValueW({name})")
        privileges = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES * 1)(LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED)))
        _check(adv.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None),
               f"AdjustTokenPrivileges({name})")
        # AdjustTokenPrivileges succeeds without the privilege and sets ERROR_NOT_ALL_ASSIGNED.
        if ctypes.get_last_error() != 0:
            raise OSError(ctypes.get_last_error(), f"this process does not have {name}; run it as SYSTEM")
    finally:
        k32.CloseHandle(token)


def _user_environment(uenv, token, names: list) -> dict:
    """The environment of the console user, with the job variables in ``names``."""
    block = ctypes.c_void_p()
    _check(uenv.CreateEnvironmentBlock(ctypes.byref(block), token, False), "CreateEnvironmentBlock")
    try:
        environment = {}
        offset = 0
        while True:
            entry = ctypes.wstring_at(block.value + offset)
            if not entry:
                break
            offset += (len(entry) + 1) * ctypes.sizeof(ctypes.c_wchar)
            key, _, value = entry.partition("=")
            if key:
                environment[key] = value
    finally:
        uenv.DestroyEnvironmentBlock(block)
    for name in names:
        if name not in os.environ:
            raise SystemExit(f"[console-session] --env {name}: the variable is not set in this job")
        environment = {key: value for key, value in environment.items() if key.upper() != name.upper()}
        environment[name] = os.environ[name]
    return environment


def _environment_block(environment: dict) -> ctypes.Array:
    """A Unicode environment block, sorted by name as Windows needs it."""
    items = sorted(environment.items(), key=lambda item: item[0].upper())
    return ctypes.create_unicode_buffer("".join(f"{key}={value}\0" for key, value in items) + "\0")


def _print_new_output(log: str, printed: int, final: bool = False) -> int:
    """Print the output that the command wrote since the last call; return the new offset.

    While the command runs, a read that fails is tried again at the next call.
    """
    try:
        with open(log, "rb") as stream:
            stream.seek(printed)
            data = stream.read()
    except OSError:
        if final:
            raise
        return printed
    if data:
        sys.stdout.write(data.decode("utf-8", errors="replace"))
        sys.stdout.flush()
    return printed + len(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", required=True, help="file for the output of the command")
    parser.add_argument("--cwd", default=os.getcwd(), help="working directory of the command")
    parser.add_argument("--env", action="append", default=[], help="job variable to pass to the command")
    parser.add_argument("--timeout", type=int, default=3600, help="seconds before the command is stopped")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command")

    k32, adv, wts, uenv = _windows_api()
    for privilege in ("SeTcbPrivilege", "SeAssignPrimaryTokenPrivilege", "SeIncreaseQuotaPrivilege"):
        _enable_privilege(k32, adv, privilege)
    session = k32.WTSGetActiveConsoleSessionId()
    if session == NO_CONSOLE_SESSION:
        raise SystemExit("[console-session] this computer has no active console session")
    user_token = wintypes.HANDLE()
    if not wts.WTSQueryUserToken(session, ctypes.byref(user_token)):
        error = ctypes.get_last_error()
        raise SystemExit(
            f"[console-session] no user is logged on to console session {session} "
            f"(WTSQueryUserToken: {ctypes.FormatError(error).strip()}); the command needs a desktop session"
        )
    token = wintypes.HANDLE()
    _check(adv.DuplicateTokenEx(user_token, MAXIMUM_ALLOWED, None, SECURITY_IMPERSONATION, TOKEN_PRIMARY,
                                ctypes.byref(token)), "DuplicateTokenEx")
    environment = _user_environment(uenv, token, args.env)
    user = f"{environment.get('USERDOMAIN', '?')}\\{environment.get('USERNAME', '?')}"

    log = os.path.abspath(args.log)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    open(log, "wb").close()
    line = f"{subprocess.list2cmdline(command)} > {subprocess.list2cmdline([log])} 2>&1"
    command_line = ctypes.create_unicode_buffer(f'cmd.exe /d /s /c "{line}"')
    startup = STARTUPINFOW()
    startup.cb = ctypes.sizeof(startup)
    startup.lpDesktop = "winsta0\\default"
    process = PROCESS_INFORMATION()
    _check(adv.CreateProcessAsUserW(token, None, command_line, None, None, False,
                                    CREATE_UNICODE_ENVIRONMENT | CREATE_NEW_CONSOLE,
                                    _environment_block(environment),
                                    os.path.abspath(args.cwd), ctypes.byref(startup), ctypes.byref(process)),
           "CreateProcessAsUserW")
    print(f"[console-session] session {session}, user {user}, process {process.dwProcessId}: "
          f"{command_line.value}", flush=True)

    printed = 0
    deadline = time.monotonic() + args.timeout
    while k32.WaitForSingleObject(process.hProcess, 2000) == WAIT_TIMEOUT:
        printed = _print_new_output(log, printed)
        if time.monotonic() > deadline:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.dwProcessId)], check=False)
            k32.WaitForSingleObject(process.hProcess, 30000)
            _print_new_output(log, printed, final=True)
            print(f"[console-session] the command did not end in {args.timeout} s; it was stopped",
                  flush=True)
            return 124
    _print_new_output(log, printed, final=True)
    code = wintypes.DWORD()
    _check(k32.GetExitCodeProcess(process.hProcess, ctypes.byref(code)), "GetExitCodeProcess")
    for handle in (process.hProcess, process.hThread, token, user_token):
        k32.CloseHandle(handle)
    print(f"[console-session] exit status {code.value}", flush=True)
    return code.value


if __name__ == "__main__":
    sys.exit(main())
