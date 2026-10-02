from dataclasses import dataclass
from pathlib import Path
import ctypes
import os


BLOCKED_ROOTS = [
    Path(r"C:\Users\vijay koripella"),
]

DELETE_OPS = {
    "delete",
    "remove",
    "unlink",
    "rmdir",
}

MUTATING_OPS = {
    "write",
    "move",
    "rename",
    "mkdir",
    "create",
}


def resolve_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def is_within(path: str | Path, root: str | Path) -> bool:
    candidate = os.path.normcase(os.path.abspath(str(resolve_path(path))))
    root_path = os.path.normcase(os.path.abspath(str(resolve_path(root))))

    try:
        return os.path.commonpath([candidate, root_path]) == root_path
    except ValueError:
        return False


def check_path(path: str | Path) -> Path:
    resolved = resolve_path(path)

    for blocked in BLOCKED_ROOTS:
        if is_within(resolved, blocked):
            raise PermissionError(
                f"Access denied: {resolved} is inside a blocked user profile."
            )

    return resolved


def assert_not_admin() -> None:
    if os.name == "nt":
        try:
            if ctypes.windll.shell32.IsUserAnAdmin():
                raise PermissionError(
                    "Jarvis must never run with Administrator privileges."
                )
        except (AttributeError, OSError) as exc:
            raise PermissionError("Jarvis cannot verify its privilege level; startup is blocked.") from exc


def browser_launch_context() -> str:
    """Read the current Windows token; never change privileges or escape a job."""
    if os.name != "nt":
        return "unsupported"
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.IsTokenRestricted.argtypes = [w.HANDLE]
    advapi.IsTokenRestricted.restype = w.BOOL
    token = w.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        return "unknown"
    try:
        ctypes.set_last_error(0)
        restricted = advapi.IsTokenRestricted(token)
        if not restricted and ctypes.get_last_error():
            return "unknown"
        return "restricted" if restricted else "normal"
    finally:
        kernel.CloseHandle(token)


def require_browser_launch_context():
    assert_not_admin()
    if browser_launch_context() != "normal":
        raise PermissionError("Browser launch blocked: Jarvis has a restricted or unverified Windows token. Start Jarvis from a normal, non-administrator terminal.")


@dataclass(frozen=True)
class Action:
    operation: str
    path: str


def authorize(action: Action, approved: bool = False) -> bool:
    operation = action.operation.lower().strip()

    if operation in DELETE_OPS:
        raise PermissionError(
            "Deletion is permanently disabled in Jarvis."
        )

    check_path(action.path)

    if operation in MUTATING_OPS and not approved:
        raise PermissionError(
            "This action changes the filesystem and requires explicit approval."
        )

    return True
