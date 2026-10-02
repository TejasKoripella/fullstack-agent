"""Bounded, explicitly requested Windows UIA observation. No input actions."""
import ctypes
from ctypes import wintypes as w
import os
import hashlib
import json
import time
from pathlib import Path
from security import assert_not_admin, check_path
from capability_registry import INSPECTION_POLICIES, accepts_process

SUPPORTED = {name: policy['executable'] for name, policy in INSPECTION_POLICIES.items()}
MAX_CONTROLS = 180
FOREGROUND_TRACE = None
SCROLL_TRACE = None


class ForegroundUnavailableError(RuntimeError):
    def __init__(self, accepted):
        super().__init__('Windows did not confirm the selected foreground window')
        self.diagnostic = 'foreground_request_pending_timeout' if accepted else 'foreground_request_denied'


def await_foreground(user32, hwnd, timeout=.5):
    """Observe asynchronous activation; never inject input or bypass focus locks."""
    deadline = time.monotonic() + timeout
    while True:
        if int(user32.GetForegroundWindow() or 0) == hwnd: return True
        if time.monotonic() >= deadline: return False
        time.sleep(.025)


def identity_key(*parts):
    # Comparison data only. This identifier never grants permission.
    return hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()


def context_descriptor(element):
    """Control-view identity only; never read edit values or password contents."""
    if element.CurrentIsPassword:
        raise PermissionError('Password controls are inaccessible')
    runtime=tuple(element.GetRuntimeId())
    if not runtime: raise PermissionError('Cannot identify the control context')
    return (runtime, element.CurrentControlType, safe_label(element.CurrentName))


def current_control_context(walker, element, root_runtime, window_id):
    """Re-attest the bounded parent chain, including document/dialog identity."""
    chain,seen=[],set()
    for _ in range(33):
        if not element: break
        descriptor=context_descriptor(element)
        if descriptor[0] in seen: break
        seen.add(descriptor[0]); chain.append(descriptor)
        if descriptor[0]==root_runtime:
            return identity_key(window_id, tuple(reversed(chain)))
        element=walker.GetParentElement(element)
    raise PermissionError('The control is no longer in the observed window context')


def process_birth(kernel, handle):
    created, exited, system, user = (w.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
        raise PermissionError('Cannot verify the target process lifetime')
    return (created.dwHighDateTime << 32) | created.dwLowDateTime


def normal_process_token(kernel, advapi, handle):
    """Fail closed if the target is elevated or its privilege is unknown."""
    token = w.HANDLE()
    if not advapi.OpenProcessToken(handle, 0x0008, ctypes.byref(token)) or not token:
        return False
    try:
        elevation, returned = w.DWORD(), w.DWORD()
        return bool(advapi.GetTokenInformation(token, 20, ctypes.byref(elevation),
                    ctypes.sizeof(elevation), ctypes.byref(returned))) \
            and returned.value == ctypes.sizeof(elevation) and elevation.value == 0
    finally:
        kernel.CloseHandle(token)


def safe_label(value):
    text = str(value or '')
    if 'vijay koripella' in text.casefold():
        raise PermissionError('Blocked profile content is inaccessible')
    return text[:240]


def select_window(target):
    if target not in SUPPORTED:
        raise PermissionError('Window inspection supports Spotify and Chrome only')
    assert_not_admin()
    if os.name != 'nt':
        raise OSError('Window inspection requires Windows')
    u, k = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    u.GetForegroundWindow.restype = w.HWND
    u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    u.IsWindowVisible.argtypes = [w.HWND]
    u.GetWindowTextLengthW.argtypes = [w.HWND]
    u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; k.OpenProcess.restype = w.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    k.CloseHandle.argtypes = [w.HANDLE]
    k.GetPackageFamilyName.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD), w.LPWSTR]
    k.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    k.ProcessIdToSessionId.argtypes = [w.DWORD, ctypes.POINTER(w.DWORD)]
    own_session = w.DWORD()
    if not k.ProcessIdToSessionId(os.getpid(), ctypes.byref(own_session)):
        raise PermissionError('Cannot verify the current Windows session')
    matches = []
    callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    @callback
    def collect(hwnd, unused):
        if not u.IsWindowVisible(hwnd): return True
        pid = w.DWORD(); u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        session = w.DWORD()
        if not k.ProcessIdToSessionId(pid.value, ctypes.byref(session)) or session.value != own_session.value: return True
        handle = k.OpenProcess(0x1000, False, pid.value)  # Query rights only.
        if not handle: return True
        try:
            if not normal_process_token(k, advapi, handle): return True
            buffer, size = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
            if not k.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)): return True
            if Path(buffer.value).name.casefold() != SUPPORTED[target]: return True
            family, family_size = ctypes.create_unicode_buffer(512), w.DWORD(512)
            package_family = family.value if k.GetPackageFamilyName(handle, ctypes.byref(family_size), family) == 0 else None
            if not accepts_process(target, buffer.value, package_family): return True
            title = ctypes.create_unicode_buffer(u.GetWindowTextLengthW(hwnd) + 1)
            u.GetWindowTextW(hwnd, title, len(title))
            matches.append((int(hwnd), pid.value, safe_label(title.value), process_birth(k, handle)))
        except PermissionError:
            return True
        finally:
            k.CloseHandle(handle)
        return True
    u.EnumWindows.argtypes = [callback, w.LPARAM]
    u.EnumWindows(collect, 0)
    foreground = int(u.GetForegroundWindow() or 0)
    focused = [item for item in matches if item[0] == foreground]
    candidates = focused or matches
    if len(candidates) != 1:
        raise RuntimeError('Select one supported window first; the target is missing or ambiguous')
    return candidates[0]


def automation_client():
    from comtypes.client import GetModule, CreateObject
    system_dir = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(system_dir, len(system_dir)):
        raise PermissionError('Cannot identify the Windows UI Automation library')
    types = GetModule(str(Path(system_dir.value) / 'UIAutomationCore.dll'))
    return CreateObject(types.CUIAutomation)


def focus(target):
    global FOREGROUND_TRACE
    FOREGROUND_TRACE = None
    hwnd, pid, _, birth = select_window(target)
    automation = automation_client()
    root = automation.ElementFromHandle(hwnd)
    if root.CurrentProcessId != pid:
        raise PermissionError('The selected window changed before focus')
    # Accessibility focus on the attested root only, never model-supplied input.
    root.SetFocus()
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.GetForegroundWindow.restype = w.HWND
    accepted = False
    if int(u.GetForegroundWindow() or 0) != hwnd:
        u.SetForegroundWindow.argtypes = [w.HWND]
        u.SetForegroundWindow.restype = w.BOOL
        accepted = bool(u.SetForegroundWindow(hwnd)) # Normal request; no focus-lock bypass.
    started = time.monotonic()
    confirmed = await_foreground(u, hwnd)
    FOREGROUND_TRACE = {'request_accepted': accepted, 'confirmed': confirmed,
                        'wait_ms': min(1000, round((time.monotonic()-started)*1000))}
    if not confirmed:
        raise ForegroundUnavailableError(accepted)
    final_hwnd, final_pid, _, final_birth = select_window(target)
    if (final_hwnd, final_pid, final_birth) != (hwnd, pid, birth):
        raise PermissionError('The selected application changed during focus')
    return {'app': target, 'focused': True}


def observe(target, locate=None):
    hwnd, pid, title, birth = select_window(target)
    automation = automation_client()
    root = automation.ElementFromHandle(hwnd)
    if root.CurrentProcessId != pid:
        raise PermissionError('The selected window changed before inspection')
    runtime_id = tuple(root.GetRuntimeId())
    if not runtime_id:
        raise PermissionError('Cannot identify the selected window')
    window_id = identity_key(hwnd, pid, birth, runtime_id)
    walker = automation.ControlViewWalker
    pending, controls, visited, depth_limited = [(root, 0, ())], [], 0, False
    located = []
    while pending and visited < MAX_CONTROLS:
        element, depth, ancestors = pending.pop()
        visited += 1
        # Never read or descend into a password field. Do not read edit values.
        if element.CurrentIsPassword: continue
        name = safe_label(element.CurrentName)
        element_id = tuple(element.GetRuntimeId())
        path=ancestors+((element_id,element.CurrentControlType,name),)
        scrollable = element.GetCurrentPropertyValue(30034) is True
        if name or scrollable:
            rect = element.CurrentBoundingRectangle
            control_id = identity_key(window_id, element_id) if element_id else None
            if locate is not None and control_id == locate: located.append(element)
            controls.append({'name': name, 'type': element.CurrentControlType,
                             'enabled': bool(element.CurrentIsEnabled),
                             'offscreen': bool(element.CurrentIsOffscreen),
                             'id': control_id,
                             'context_id': identity_key(window_id,path) if all(part[0] for part in path) else None,
                             'scrollable': scrollable,
                             'bounds': [rect.left, rect.top, rect.right, rect.bottom]})
        if depth < 32:
            children, child = [], walker.GetFirstChildElement(element)
            while child and len(children) < MAX_CONTROLS - visited:
                children.append((child, depth + 1, path))
                child = walker.GetNextSiblingElement(child)
            pending.extend(reversed(children))
        elif walker.GetFirstChildElement(element):
            depth_limited = True
    if root.CurrentProcessId != pid:
        raise PermissionError('The selected window changed during inspection')
    current = automation.ElementFromHandle(hwnd)
    if current.CurrentProcessId != pid or tuple(current.GetRuntimeId()) != runtime_id:
        raise PermissionError('The selected window was replaced during inspection')
    # Re-attest process lifetime and allowlist identity, not only a reused PID.
    final_hwnd, final_pid, _, final_birth = select_window(target)
    if (final_hwnd, final_pid, final_birth) != (hwnd, pid, birth):
        raise PermissionError('The selected application changed during inspection')
    result = {'app': target, 'window_title': title, 'controls': controls,
            'window_id': window_id,
            'partial': depth_limited or bool(pending) or visited >= MAX_CONTROLS,
            'read_only': True}
    if locate is not None:
        if len(located) != 1: raise PermissionError('The intended control is missing or ambiguous')
        return result, (hwnd, pid, birth, runtime_id, automation, located[0])
    return result


def preview(target, expected_window, control, action='preview'):
    """Owned-worker-only visual preview. Never sends click/key/text input."""
    from computer_action_policy import validate_action
    validate_action(target,control,action)
    hwnd, pid, _, birth = select_window(target)
    automation = automation_client()
    root = automation.ElementFromHandle(hwnd)
    runtime = tuple(root.GetRuntimeId())
    if root.CurrentProcessId != pid or identity_key(hwnd, pid, birth, runtime) != expected_window:
        raise PermissionError('The intended window changed')
    # The user's preview confirmation explicitly includes bringing this app forward.
    focus(target)
    snapshot, context = observe(target, locate=control['id'])
    if snapshot['window_id'] != expected_window:
        raise PermissionError('The intended window changed')
    hwnd, pid, birth, runtime, automation, element = context
    from window_glow import NativeBorder
    def bounds():
        current = automation.ElementFromHandle(hwnd)
        if current.CurrentProcessId != pid or tuple(current.GetRuntimeId()) != runtime:
            return None
        h, p, _, b = select_window(target)
        if (h, p, b) != (hwnd, pid, birth): return None
        if element.CurrentIsPassword or element.CurrentIsOffscreen or not element.CurrentIsEnabled:
            return None
        if current_control_context(automation.ControlViewWalker,element,runtime,expected_window) != control['context_id']:
            return None
        if identity_key(expected_window, tuple(element.GetRuntimeId())) != control['id'] \
                or safe_label(element.CurrentName) != control['name'] or element.CurrentControlType != control['type']:
            return None
        rect = element.CurrentBoundingRectangle
        return [rect.left, rect.top, rect.right, rect.bottom]
    if not bounds(): raise PermissionError('The intended control changed')
    global SCROLL_TRACE
    SCROLL_TRACE = None
    outcome={}
    def scroll_once():
        global SCROLL_TRACE
        # Re-attest immediately before the one effect, not just before painting.
        if not bounds(): raise PermissionError('The intended control context changed')
        try:
            from comtypes.gen.UIAutomationClient import IUIAutomationScrollPattern
            pattern=element.GetCurrentPattern(10004).QueryInterface(IUIAutomationScrollPattern)
            if not pattern.CurrentVerticallyScrollable:
                outcome.update(outcome='unsupported',action_attempted=False)
                return
            before=float(pattern.CurrentVerticalScrollPercent)
            if not 0<=before<=100: raise ValueError('Invalid scroll position')
            if (action=='scroll_up' and before==0) or (action=='scroll_down' and before==100):
                outcome.update(outcome='boundary',action_attempted=False)
                return
            outcome.update(outcome='unknown',action_attempted=True)
            SCROLL_TRACE = {'reason':'provider_call', 'before':before}
            pattern.Scroll(2,1 if action=='scroll_up' else 4)
            # Providers may complete scrolling asynchronously. Observe only, never retry input.
            deadline=time.monotonic()+.5
            while True:
                if not bounds():
                    SCROLL_TRACE['reason']='target_attestation_lost'
                    return
                after=float(pattern.CurrentVerticalScrollPercent)
                SCROLL_TRACE.update(reason='position_unchanged',after=after if 0<=after<=100 else None)
                if 0<=after<=100 and ((action=='scroll_down' and after>before) or (action=='scroll_up' and after<before)):
                    outcome.update(outcome='verified',before=before,after=after)
                    SCROLL_TRACE['reason']='verified'
                    return
                if time.monotonic()>=deadline: return
                time.sleep(.025)
        except Exception:
            if not outcome.get('action_attempted'): raise
            SCROLL_TRACE['reason']='provider_exception'
            # An effect may have occurred; never invite a blind retry or claim success.
            outcome.update(outcome='unknown',action_attempted=True)
    border = NativeBorder(SUPPORTED[target], exact_window=(hwnd, pid), control_bounds=bounds, duration=3,
                          on_ready=scroll_once if action!='preview' else None)
    border.run() # Same UIA COM apartment; never marshal provider pointers to another thread.
    if action!='preview' and outcome:
        return dict(outcome,app=target,action=action,indicator_shown=border.was_shown,
                    indicator_completed=border.completed)
    if not border.was_shown or not border.completed:
        raise RuntimeError('Target preview did not remain visible until completion')
    return {'app': target, 'preview_shown': True, 'input_sent': False}


def playlist_parent(walker, element, view_name):
    """The playlist's main section, never the library or global media controls."""
    for _ in range(32):
        element = walker.GetParentElement(element)
        if not element: return False
        if element.CurrentIsPassword: return False
        if element.CurrentControlType == 50026 and safe_label(element.CurrentName) == view_name:
            return True
    return False


def play_playlist(name):
    """Fixed Spotify capability in the existing observe/act/verify worker."""
    from tool_broker import known_resources, resource_path
    from window_glow import NativeBorder
    from spotify_media import spotify_status
    if resource_path(name)[0] != 'playlist': raise PermissionError('Only registered playlists can play')
    view_name = known_resources()[name].get('view_name')
    result = {'resource_kind':'playlist', 'playback_confirmed':False, 'action_attempted':False}
    if not view_name: return result
    title = view_name.split(' - playlist by ',1)[0]
    try:
        focus('Spotify')
        deadline = time.monotonic()+2
        selected = None
        while True:
            snapshot = observe('Spotify')
            candidates = []
            for control in snapshot['controls']:
                if control['name'] not in {'Play '+title, 'Pause '+title} or control['type'] != 50000 \
                        or not control['enabled'] or control['offscreen']: continue
                current, context = observe('Spotify', locate=control['id'])
                if current['window_id'] != snapshot['window_id']: return result
                hwnd,pid,birth,runtime,automation,element = context
                if playlist_parent(automation.ControlViewWalker, element, view_name):
                    candidates.append((control,context,snapshot['window_id']))
            if len(candidates)==1:
                selected = candidates[0]
                break
            if len(candidates)>1 or time.monotonic()>=deadline: return result
            time.sleep(.1) # Navigation may expose controls asynchronously; no input retry.
        control,context,window_id = selected
        from computer_action_policy import validate_playlist_action
        validate_playlist_action(name,control)
        hwnd,pid,birth,runtime,automation,element = context
        def bounds():
            h,p,_,b = select_window('Spotify')
            root = automation.ElementFromHandle(hwnd)
            if (h,p,b)!=(hwnd,pid,birth) or root.CurrentProcessId!=pid or tuple(root.GetRuntimeId())!=runtime:
                return None
            if element.CurrentIsPassword or element.CurrentIsOffscreen or not element.CurrentIsEnabled: return None
            if not playlist_parent(automation.ControlViewWalker,element,view_name): return None
            if current_control_context(automation.ControlViewWalker,element,runtime,window_id)!=control['context_id']: return None
            if safe_label(element.CurrentName)!=control['name'] or element.CurrentControlType!=50000: return None
            rect=element.CurrentBoundingRectangle
            return [rect.left,rect.top,rect.right,rect.bottom]
        def start_once():
            if not bounds(): return
            if control['name']=='Play '+title:
                from comtypes.gen.UIAutomationClient import IUIAutomationInvokePattern
                pattern=element.GetCurrentPattern(10000).QueryInterface(IUIAutomationInvokePattern)
                result['action_attempted']=True # An exception after this point may still have sent input.
                pattern.Invoke()
            verify_until=time.monotonic()+.8
            while True:
                # The playlist-scoped Pause control and Spotify's own media session must agree.
                h,p,_,b=select_window('Spotify')
                if (h,p,b)!=(hwnd,pid,birth): return
                if safe_label(element.CurrentName)=='Pause '+title and playlist_parent(automation.ControlViewWalker,element,view_name) \
                        and spotify_status().get('playing') is True:
                    result['playback_confirmed']=True
                    return
                if time.monotonic()>=verify_until: return
                time.sleep(.05)
        border=NativeBorder('spotify.exe',exact_window=(hwnd,pid),control_bounds=bounds,duration=1.5,on_ready=start_once)
        border.run() # Same COM apartment; trusted invocation after the target reticle is painted.
        return result
    except (RuntimeError, OSError, ValueError, AttributeError):
        return result # Honest partial result; never replay an uncertain invocation.
