"""Narrow user-initiated OS actions. This module is never passed to Ollama."""

from pathlib import Path
import ctypes
from ctypes import wintypes
import json
import os
import re
import subprocess
import winreg
from urllib.parse import quote, urlsplit
from functools import wraps
import safety as safety_runtime
import zipfile
from xml.etree import ElementTree

from memory import MemoryStore
from security import Action, authorize, check_path, is_within, require_browser_launch_context


PROJECT_ROOT = Path(__file__).resolve().parent


def running_tool(function):
    @wraps(function)
    def checked(*args, **kwargs):
        with safety_runtime.safety.operation() as epoch:
            result = function(*args, **kwargs)
            safety_runtime.safety.ensure_running(epoch)
            return result
    return checked


def validate_document_query(query):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 80 \
            or any(char in query for char in '/\\:') or query.strip() in {".", ".."}:
        raise PermissionError("Use a filename fragment, not a path")
    return query.strip()
MAX_READ_BYTES = 64 * 1024
READABLE_SUFFIXES = {".py", ".md", ".txt", ".html", ".css", ".js", ".json"}
EXCLUDED_PARTS = {".venv", ".git", "__pycache__", "data", "config"}
MAX_DOCUMENT_ENTRIES = 100
MAX_PERSONAL_TEXT_BYTES = 64 * 1024
MAX_DOCX_BYTES = 2 * 1024 * 1024
MAX_DOCX_XML_BYTES = 512 * 1024
PERSONAL_TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json"}
ALLOWED_SITES = {
    "Spotify Web": "https://open.spotify.com/",
}
ALLOWED_PACKAGED_APPS = {
    "Spotify": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
}
ALLOWED_SETTINGS = {
    "Bluetooth": "ms-settings:bluetooth",
    "Sound": "ms-settings:sound",
}


def documents_root() -> Path:
    """Resolve this user's Windows Documents known folder, including OneDrive redirects."""
    if os.name != "nt":
        raise OSError("Document browsing is available only on Windows.")
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
    ) as key:
        raw, _ = winreg.QueryValueEx(key, "Personal")
    root = check_path(Path(os.path.expandvars(raw)))
    if not is_within(root, Path.home()) or not root.is_dir():
        raise PermissionError("The Documents folder is outside this Windows profile or unavailable.")
    return root


def load_allowed_apps() -> dict[str, Path]:
    """Load a static project config; HTTP requests cannot alter the allowlist."""
    config = PROJECT_ROOT / "config" / "allowed_apps.json"
    if not config.exists():
        return {}
    entries = json.loads(config.read_text(encoding="utf-8"))
    if not isinstance(entries, dict):
        raise ValueError("App allowlist must be a JSON object.")
    apps = {}
    for name, raw_path in entries.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9 _-]{1,40}", name):
            raise ValueError("Invalid app name in allowlist.")
        if not isinstance(raw_path, str):
            raise ValueError("Invalid app path in allowlist.")
        path = Path(raw_path)
        if not path.is_absolute() or path.suffix.lower() != ".exe":
            raise ValueError("Allowlisted apps need absolute .exe paths.")
        apps[name] = check_path(path)
    return apps


ALLOWED_APPS = load_allowed_apps()


def registered_webpage(url):
    """Fixed HTTPS documentation links, never a model-supplied browser command."""
    if not isinstance(url, str) or not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::443)?(?:/[A-Za-z0-9/_~.+-]*)?", url):
        raise PermissionError("Registered webpages require a plain HTTPS URL without credentials, query or fragment")
    labels = (urlsplit(url).hostname or "").split(".")
    if len(labels) < 2 or not re.search(r"[a-z]", labels[-1]) or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels) \
            or labels[-1] in {"localhost", "local", "internal", "home", "test", "invalid", "example"}:
        raise PermissionError("Local hosts and IP addresses cannot be registered as webpages")
    return url


def known_resources():
    """Local static aliases; neither HTTP nor Qwen can register new paths."""
    config = PROJECT_ROOT / "config" / "known_resources.json"
    def unique_keys(pairs):
        result, seen = {}, set()
        for key, value in pairs:
            normalized = key.casefold()
            if normalized in seen:
                raise PermissionError("Ambiguous duplicate names in known-resource configuration")
            seen.add(normalized)
            result[key] = value
        return result
    entries = json.loads(config.read_text(encoding="utf-8"), object_pairs_hook=unique_keys) if config.exists() else {}
    if not isinstance(entries, dict):
        raise PermissionError("Invalid known-resource configuration")
    for name, item in entries.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9 _-]{1,60}", name) \
                or not isinstance(item, dict) or not isinstance(item.get("kind"), str):
            raise PermissionError("Invalid known-resource configuration")
        if item["kind"] == "playlist":
            if set(item) not in ({"kind", "uri"}, {"kind", "uri", "view_name"}) or not isinstance(item["uri"], str) \
                    or not re.fullmatch(r"spotify:playlist:[A-Za-z0-9]{22}", item["uri"]):
                raise PermissionError("Only a registered Spotify playlist URI can open")
            if 'view_name' in item and (not isinstance(item['view_name'],str) or not 1<=len(item['view_name'])<=160
                    or any(c in item['view_name'] for c in '\\/:\r\n') or ' - playlist by ' not in item['view_name']):
                raise PermissionError('Invalid registered playlist view identity')
        elif item["kind"] == "webpage":
            if set(item) != {"kind", "url"}:
                raise PermissionError("Invalid registered webpage configuration")
            registered_webpage(item["url"])
        elif item["kind"] not in {"document", "project"} or set(item) != {"kind", "path"} \
                or not isinstance(item["path"], str) or not item["path"].strip():
            raise PermissionError("Invalid known-resource configuration")
    return entries


def resource_path(name):
    item = known_resources().get(name)
    if item is None:
        raise PermissionError("That resource is not registered")
    if item["kind"] == "playlist":
        return "playlist", item["uri"]
    if item["kind"] == "webpage":
        return "webpage", registered_webpage(item["url"])
    path = check_path(PROJECT_ROOT / item["path"])
    if not is_within(path, Path.home()):
        raise PermissionError("Registered resources must stay within this Windows profile")
    if item["kind"] == "project":
        if not path.is_dir():
            raise PermissionError("The registered project is unavailable")
    elif not path.is_file() or path.suffix.lower() not in {".txt", ".md", ".pdf", ".docx"}:
        raise PermissionError("Only existing registered documents can open")
    return item["kind"], path


class ToolBroker:
    def __init__(self, memory: MemoryStore):
        self.memory = memory
        self._launched: dict[str, subprocess.Popen] = {}

    @running_tool
    def open_resource(self, name, approved=False):
        if not approved:
            raise PermissionError("Registered resource opening requires fresh approval")
        try:
            require_browser_launch_context()
            def open_checked():
                kind, path = resource_path(name)
                if kind == "project":
                    # Supported VS Code file URI. No CLI, process ownership, or commands.
                    os.startfile("vscode://file/" + quote(path.as_posix(), safe="/:"))
                elif kind in {"playlist", "webpage"}:
                    os.startfile(path)
                else:
                    os.startfile(str(path))
                return kind
            kind = safety_runtime.safety.effect(open_checked)
        except Exception as exc:
            self._audit("open_resource", name, approved, False, type(exc).__name__)
            raise
        self._audit("open_resource", name, True, True, "Windows accepted registered resource request")
        return {"request_sent": True, "resource_kind": kind,
                "playback_confirmed": False} if kind == "playlist" else {"request_sent": True}

    def _audit(self, action: str, target: str, approved: bool, allowed: bool, reason: str):
        self.memory.log_action(
            action=action,
            target=target,
            approved=approved,
            allowed=allowed,
            reason=reason,
            write_approved=True,
        )

    @running_tool
    def guarded_read_file(self, relative_path: str, approved: bool = False) -> str:
        try:
            requested = Path(relative_path)
            if requested.is_absolute() or requested.drive or ".." in requested.parts:
                raise PermissionError("Only project-relative paths are allowed.")
            if any(part.lower() in EXCLUDED_PARTS for part in requested.parts):
                raise PermissionError("This project area is not readable through Jarvis.")
            path = check_path(PROJECT_ROOT / requested)
            if not is_within(path, PROJECT_ROOT):
                raise PermissionError("The file is outside the Jarvis project.")
            if any(part.lower() in EXCLUDED_PARTS for part in path.relative_to(PROJECT_ROOT).parts):
                raise PermissionError("This project area is not readable through Jarvis.")
            authorize(Action("read", str(path)))
            if path.suffix.lower() not in READABLE_SUFFIXES or not path.is_file():
                raise PermissionError("Only existing project text files are readable.")
            if path.stat().st_size > MAX_READ_BYTES:
                raise PermissionError("The file is too large to read through Jarvis.")
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            self._audit("guarded_read_file", relative_path, approved, False, type(exc).__name__)
            raise

        self._audit("guarded_read_file", relative_path, True, True, "User-authorized read-only action succeeded")
        return content

    @running_tool
    def list_documents(self, relative_folder: str = "", approved: bool = False) -> list[dict]:
        """List one folder in this user's Documents without reading file contents."""
        try:
            root = documents_root()
            requested = Path(relative_folder or ".")
            if requested.is_absolute() or requested.drive or ".." in requested.parts:
                raise PermissionError("Only paths relative to Documents are allowed.")
            folder = check_path(root / requested)
            if not is_within(folder, root) or not folder.is_dir():
                raise PermissionError("That Documents folder is unavailable.")
            entries = []
            for entry in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                safe = check_path(entry)
                if not is_within(safe, root):
                    continue
                entries.append({"name": entry.name, "kind": "folder" if entry.is_dir() else "file"})
                if len(entries) >= MAX_DOCUMENT_ENTRIES:
                    break
        except Exception as exc:
            self._audit("list_documents", relative_folder or ".", approved, False, type(exc).__name__)
            raise
        self._audit("list_documents", relative_folder or ".", True, True, "User-authorized read-only listing succeeded")
        return entries

    @running_tool
    def find_documents(self, query, approved=False):
        """Bounded filename-only search; never follow child links or reparse points."""
        try:
            if not approved:
                raise PermissionError("Filename search requires a user request")
            query = validate_document_query(query)
            root = documents_root()
            stack, matches, scanned, limited = [(root, 0)], [], 0, False
            while stack and scanned < 1000 and len(matches) < 50:
                safety_runtime.safety.ensure_running()
                folder, depth = stack.pop()
                # Recheck each folder before enumeration.
                safe_folder = check_path(folder)
                if not is_within(safe_folder, root):
                    continue
                try:
                    with os.scandir(safe_folder) as entries:
                        for entry in entries:
                            safety_runtime.safety.ensure_running()
                            scanned += 1
                            if scanned > 1000:
                                limited = True
                                break
                            if entry.name.startswith('.') or entry.is_symlink():
                                continue
                            info = entry.stat(follow_symlinks=False)
                            if getattr(info, 'st_file_attributes', 0) & 0x400:
                                continue
                            path = check_path(entry.path)
                            if not is_within(path, root):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if depth < 5:
                                    stack.append((path, depth + 1))
                                else:
                                    limited = True
                            elif entry.is_file(follow_symlinks=False) and query.strip().casefold() in entry.name.casefold():
                                matches.append({"name": entry.name, "path": path.relative_to(root).as_posix()})
                                if len(matches) >= 50:
                                    limited = True
                                    break
                except safety_runtime.StoppedError:
                    raise
                except (OSError, PermissionError):
                    limited = True
            result = {"matches": sorted(matches, key=lambda item: item['path'].casefold()),
                      "partial": limited or bool(stack), "scanned": min(scanned, 1000)}
        except Exception as exc:
            self._audit("find_documents", "Windows Documents", approved, False, type(exc).__name__)
            raise
        self._audit("find_documents", "Windows Documents", True, True, "Filename-only search completed; partial=" + str(result['partial']))
        return result

    @running_tool
    def open_documents(self, approved: bool = False) -> bool:
        """Request Explorer for only this user's Windows Documents known folder."""
        try:
            if os.name != "nt":
                raise OSError("Windows Documents is available only on Windows.")
            root = documents_root()
            safety_runtime.safety.effect(lambda: os.startfile(str(root)))
        except Exception as exc:
            self._audit("open_documents", "Windows Documents", approved, False, type(exc).__name__)
            raise
        self._audit("open_documents", "Windows Documents", True, True, "Explorer accepted folder request")
        return True

    @running_tool
    def open_site(self, name: str, approved: bool = False) -> bool:
        try:
            url = ALLOWED_SITES.get(name)
            if url is None:
                raise PermissionError("That site is not on the allowlist.")
            require_browser_launch_context()
            safety_runtime.safety.effect(lambda: os.startfile(url))
        except Exception as exc:
            self._audit("open_site", name, approved, False, type(exc).__name__)
            raise
        self._audit("open_site", name, True, True, "Browser accepted page request")
        return True

    @running_tool
    def read_document(self, relative_path: str, approved: bool = False) -> str:
        """Read one selected text or DOCX file from this user's Documents."""
        try:
            requested = Path(relative_path)
            if requested.is_absolute() or requested.drive or ".." in requested.parts or not requested.name:
                raise PermissionError("Only a file relative to Documents is allowed.")
            root = documents_root()
            path = check_path(root / requested)
            if not is_within(path, root) or not path.is_file():
                raise PermissionError("That document is unavailable.")
            size = path.stat().st_size
            if path.suffix.lower() in PERSONAL_TEXT_SUFFIXES:
                if size > MAX_PERSONAL_TEXT_BYTES:
                    raise PermissionError("The text document is too large.")
                content = path.read_text(encoding="utf-8-sig")
            elif path.suffix.lower() == ".docx":
                if size > MAX_DOCX_BYTES:
                    raise PermissionError("The Word document is too large.")
                with zipfile.ZipFile(path) as archive:
                    member = archive.getinfo("word/document.xml")
                    if member.file_size > MAX_DOCX_XML_BYTES:
                        raise PermissionError("The Word document text is too large.")
                    xml = archive.read(member)
                root_xml = ElementTree.fromstring(xml)
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                content = "\n".join(
                    "".join(node.text or "" for node in paragraph.findall(".//w:t", ns))
                    for paragraph in root_xml.findall(".//w:p", ns)
                )
                if len(content) > MAX_PERSONAL_TEXT_BYTES:
                    raise PermissionError("The extracted document is too large.")
            else:
                raise PermissionError("Only TXT, MD, CSV, JSON, and DOCX files are supported.")
        except Exception as exc:
            self._audit("read_document", relative_path, approved, False, type(exc).__name__)
            raise
        self._audit("read_document", relative_path, True, True, "User-authorized selected document read")
        return content

    @running_tool
    def open_packaged_app(self, name: str, approved: bool = False) -> bool:
        try:
            app_id = ALLOWED_PACKAGED_APPS.get(name)
            if app_id is None or os.name != "nt":
                raise PermissionError("That packaged app is not available through Jarvis.")
            safety_runtime.safety.effect(lambda: os.startfile("shell:AppsFolder\\" + app_id))
        except Exception as exc:
            self._audit("open_packaged_app", name, approved, False, type(exc).__name__)
            raise
        self._audit("open_packaged_app", name, True, True, "Windows accepted launch request")
        return True

    @running_tool
    def spotify_playback(self, target: str, approved: bool = False) -> dict:
        """Request only play or pause on Spotify's own Windows media session."""
        try:
            if not approved: raise PermissionError('Spotify playback requires permission')
            if target in known_resources() and known_resources()[target]['kind'] == 'playlist':
                self.open_resource(target, approved=True)
                from spotify_media import play_registered_playlist
                result = play_registered_playlist(target)
                self._audit('spotify_playback', target, True, True, 'Playlist playback verified' if result.get('playback_confirmed') else 'Playlist opened; playback unverified')
                return result
            if target not in {"Spotify Play", "Spotify Pause"}:
                raise PermissionError("Only Spotify play and pause are available.")
            from spotify_media import control_spotify
            result = control_spotify("play" if target == "Spotify Play" else "pause")
        except Exception as exc:
            self._audit("spotify_playback", target, approved, False, type(exc).__name__)
            raise
        self._audit("spotify_playback", target, True, True, "Spotify media session accepted request")
        return result

    @running_tool
    def open_settings(self, name: str) -> bool:
        try:
            uri = ALLOWED_SETTINGS.get(name)
            if uri is None or os.name != "nt":
                raise PermissionError("That settings page is not available through Jarvis.")
            safety_runtime.safety.effect(lambda: os.startfile(uri))
        except Exception as exc:
            self._audit("open_settings", name, True, False, type(exc).__name__)
            raise
        self._audit("open_settings", name, True, True, "Windows accepted settings request")
        return True

    @running_tool
    def open_app(self, name: str, approved: bool = False) -> int | None:
        try:
            executable = ALLOWED_APPS.get(name)
            if executable is None:
                raise PermissionError("That app is not on the allowlist.")
            path = check_path(executable)
            if not path.is_file() or path.suffix.lower() != ".exe":
                raise PermissionError("The allowlisted executable is unavailable.")
            if name == "Chrome":
                # Delegate to Windows without arguments, subprocess ownership,
                # profile flags, or any later close/termination responsibility.
                require_browser_launch_context()
                safety_runtime.safety.effect(lambda: os.startfile(str(path)))
                self._audit("open_app", name, approved, True, "Windows accepted browser launch request")
                return None
            process = safety_runtime.safety.spawn_owned(
                lambda: subprocess.Popen([str(path)], cwd=path.parent, shell=False), "app " + name)
            self._launched[name] = process
        except Exception as exc:
            self._audit("open_app", name, approved, False, type(exc).__name__)
            raise

        self._audit("open_app", name, True, True, "Launch confirmed")
        return process.pid

    @staticmethod
    def _request_window_close(pid: int) -> int:
        if os.name != "nt":
            raise OSError("Graceful app close is available only on Windows.")
        user32 = ctypes.windll.user32
        windows = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def collect(hwnd, _):
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value == pid and user32.IsWindowVisible(hwnd):
                windows.append(hwnd)
            return True

        callback = callback_type(collect)
        user32.EnumWindows(callback, 0)
        return sum(bool(user32.PostMessageW(hwnd, 0x0010, 0, 0)) for hwnd in windows)

    @running_tool
    def close_app(self, name: str, approved: bool = False) -> tuple[int, int]:
        try:
            if not approved:
                raise PermissionError("Explicit approval is required to close an app.")
            process = self._launched.get(name)
            if process is None or process.poll() is not None:
                raise PermissionError("Jarvis can close only an app it launched in this session.")
            self._audit("close_app", name, approved, True, "Graceful close authorized")
            sent = safety_runtime.safety.effect(lambda: self._request_window_close(process.pid))
            if not sent:
                raise PermissionError("No visible window accepted a close request.")
        except Exception as exc:
            self._audit("close_app", name, approved, False, type(exc).__name__)
            raise

        self._audit("close_app", name, approved, True, "WM_CLOSE sent to visible window")
        return process.pid, sent

    @running_tool
    def inspect_app(self, target, approved=False):
        from capability_registry import inspectable_apps
        if not approved or target not in inspectable_apps():
            raise PermissionError('A fresh explicit approval is required for supported window inspection')
        from computer_controller import observe
        observation = observe(target)
        self._audit('inspect_app', target, True, True, 'Bounded read-only UI observation; content not logged')
        return {'observation': observation}

    @running_tool
    def window_context(self, reference, scope):
        from security import assert_not_admin
        from computer_controller import window_context
        assert_not_admin()
        result = window_context(reference, scope)
        self._audit('window_context', result['app'], True, True, 'Explicit one-message snapshot reference; content not logged')
        return result

    @running_tool
    def propose_scroll(self, context, pane, direction):
        from security import assert_not_admin
        from computer_controller import propose_scroll
        assert_not_admin()
        result = propose_scroll(context,pane,direction)
        self._audit('scroll_control',result['target'],False,False,
                    'Observed pane proposed; fresh exact approval required; no input sent')
        return result

    @running_tool
    def preview_control(self, reference, scope, identifier, approved=False):
        from security import assert_not_admin
        assert_not_admin()
        if approved is not True:
            raise PermissionError('A fresh target-preview confirmation is required')
        from computer_controller import preview
        started = __import__('time').monotonic()
        try:
            result = preview(reference, scope, identifier)
        except Exception as exc:
            self._audit('preview_control', 'scoped window', True, False, type(exc).__name__)
            raise
        self._audit('preview_control', result['app'], True, True,
                    'Explicit preview confirmation; indicator shown; no input; %.0f ms' % ((__import__('time').monotonic()-started)*1000))
        return dict(result, message='Target preview finished. No click or typing was sent.')

    @running_tool
    def scroll_control(self,reference,scope,identifier,action,approved=False):
        from security import assert_not_admin
        from computer_controller import execute_control
        assert_not_admin()
        if approved is not True: raise PermissionError('A fresh exact scrolling confirmation is required')
        if action not in {'scroll_up','scroll_down'}: raise PermissionError('Unsupported scrolling action')
        try:
            result=execute_control(reference,scope,identifier,action)
        except Exception as exc:
            self._audit('scroll_control','scoped window',True,False,type(exc).__name__)
            raise
        messages={'verified':'The selected pane scrolled '+('down.' if action=='scroll_down' else 'up.'),
                  'boundary':'The selected pane is already at that scroll boundary. Nothing changed.',
                  'unsupported':'The selected pane cannot scroll vertically. Nothing changed.',
                  'unknown':'Scrolling was attempted, but the result could not be confirmed. Inspect the pane before retrying.'}
        self._audit('scroll_control',result['app'],True,result['outcome']=='verified',
                    'Fresh exact control approval; one accessibility scroll; result='+result['outcome'])
        return dict(result,message=messages[result['outcome']])

    @running_tool
    def focus_app(self, target, approved=False):
        from capability_registry import inspectable_apps
        if not approved or target not in inspectable_apps():
            raise PermissionError('A fresh explicit approval is required to focus this window')
        from computer_controller import focus
        result = focus(target)
        self._audit('focus_app', target, True, True, 'Foreground window verified')
        return result
