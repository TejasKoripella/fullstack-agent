"""Best-effort, Jarvis-owned click-through window border. No process control."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import math
import os
from pathlib import Path
import threading
import time
import logging
from collections import deque
import safety
from security import check_path
_active=set()
_active_lock=threading.Lock()
_events=deque(maxlen=80) # Bounded lifecycle diagnostics; never window titles/content.


def lifecycle_evidence():
    with _active_lock: return list(_events)


def _record(border, phase):
    with _active_lock:
        _events.append({'app': border.executable, 'phase': phase, 'time': time.monotonic()})
    logging.getLogger('uvicorn.error').info('Window indicator: app=%s phase=%s',border.executable,phase)


@contextmanager
def physical_pixel_context(user32, required=False):
    """Keep UIA geometry and drawing in physical pixels on this thread only."""
    setter=getattr(user32,'SetThreadDpiAwarenessContext',None)
    previous=None
    if setter is not None:
        setter.argtypes=[ctypes.c_void_p]; setter.restype=ctypes.c_void_p
        previous=setter(ctypes.c_void_p(-4)) # PER_MONITOR_AWARE_V2
    if required and not previous:
        raise OSError('Cannot establish physical-pixel overlay coordinates')
    try:
        yield bool(previous)
    finally:
        if previous:
            setter(previous)


def reticle_segments(bounds, window, elapsed):
    """Window-relative marks for a freshly identified visible control."""
    if not isinstance(bounds, (list, tuple)) or len(bounds)!=4: return []
    if any(type(value) not in (int,float) or not math.isfinite(value) for value in bounds): return []
    left,top,right,bottom=bounds
    x,y,end_x,end_y=window
    if not (x<=left<right<=end_x and y<=top<bottom<=end_y): return []
    left,top,right,bottom=(int(left-x),int(top-y),int(right-x),int(bottom-y))
    size=min(12,(right-left)//3,(bottom-top)//3)
    if size<2: return []
    # Corner brackets plus a small travelling cross. No system pointer input.
    progress=max(0,min(1,elapsed/.3)); eased=1-(1-progress)**3
    cx=int((end_x-x)/2*(1-eased)+(left+right)/2*eased)
    cy=int((end_y-y)/2*(1-eased)+(top+bottom)/2*eased)
    cx=max(left+1,min(right-1,cx)); cy=max(top+1,min(bottom-1,cy))
    return [(left,top,left+size,top+1),(left,top,left+1,top+size),
            (right-size,top,right,top+1),(right-1,top,right,top+size),
            (left,bottom-1,left+size,bottom),(left,bottom-size,left+1,bottom),
            (right-size,bottom-1,right,bottom),(right-1,bottom-size,right,bottom),
            (max(left,cx-4),cy,min(right,cx+5),cy+1),
            (cx,max(top,cy-4),cx+1,min(bottom,cy+5))]


def accepts_glow_process(executable, image, package_family=None):
    """Use the same app identity policy for observation and its visible border."""
    from capability_registry import accepts_process, INSPECTION_POLICIES
    path=check_path(image)
    if path.name.casefold()!=executable.casefold(): return False
    app=next((name for name,policy in INSPECTION_POLICIES.items() if policy['executable']==executable.casefold()),None)
    if app: return accepts_process(app,path,package_family)
    from tool_broker import ALLOWED_APPS
    allowed = [check_path(item) for item in ALLOWED_APPS.values()]
    if executable.casefold() == 'code.exe':
        allowed += [check_path(Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'Programs/Microsoft VS Code/Code.exe'),
                    check_path(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Microsoft VS Code/Code.exe')]
    return any(os.path.normcase(str(path)) == os.path.normcase(str(item)) for item in allowed)


def close_all():
    with _active_lock:
        borders=list(_active)
    for border in borders:
        border.close()


class NativeBorder:
    def __init__(self, executable, exact_window=None, control_bounds=None, duration=None, on_ready=None, action_lifecycle=False):
        if exact_window is not None and (not isinstance(exact_window, tuple) or len(exact_window)!=2
                or any(type(value) is not int or value<=0 for value in exact_window)):
            raise ValueError('Overlay needs an exact native window and process identity')
        if control_bounds is not None and (not callable(control_bounds) or exact_window is None or duration is None):
            raise ValueError('Control overlays need a trusted geometry provider, exact window and bounded lifetime')
        self.executable=executable.casefold()
        self.stop_event=threading.Event()
        self.ready=threading.Event()
        self.shown=threading.Event()
        self.was_shown=False
        self.completed=False
        self.exact_window=exact_window
        self.control_bounds=control_bounds
        if on_ready is not None and (not callable(on_ready) or control_bounds is None):
            raise ValueError('An action requires a trusted control indicator')
        self.on_ready=on_ready
        self.action_attempted=False
        if duration is not None and (type(duration) not in (int,float) or not .1<=duration<=5):
            raise ValueError('Overlay duration must be bounded')
        self.duration=duration
        self.action_lifecycle=action_lifecycle
        self.action_finished=threading.Event()
        self.finished_at=None
        self.epoch=safety.safety.ensure_running() if action_lifecycle else None
        self.hwnd=None
        self.thread=threading.Thread(target=self.run,daemon=True,name='Jarvis window glow')

    def start(self):
        if self.control_bounds is not None:
            raise ValueError('Run control overlays in their owned UIA worker apartment')
        self.thread.start()

    def finish(self):
        if self.action_finished.is_set(): return
        self.finished_at=time.monotonic()
        self.action_finished.set()

    def action_lifetime_complete(self, visible_after_finish, first_visible, now=None):
        # No display timer can end the glow while its controlling action is active.
        if not self.action_finished.is_set(): return False
        now=time.monotonic() if now is None else now
        return (visible_after_finish>=1.1 or now-self.finished_at>=3.5
                or (first_visible is None and now-self.finished_at>=2))

    def close(self):
        self.stop_event.set()
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(.3)

    def run(self):
        try:
            with safety.safety.operation(self.close):
                safety.safety.ensure_running(self.epoch)
                user32=ctypes.WinDLL('user32',use_last_error=True)
                with physical_pixel_context(user32,required=self.control_bounds is not None):
                    self._run_native()
        except (OSError,ValueError,AttributeError):
            pass
        finally:
            self.shown.clear()
            self.ready.set()
            if self.action_lifecycle:
                _record(self, 'closed')
                with _active_lock: _active.discard(self)

    def _paint_frame(self, u, g, overlay, rect, marks, alpha):
        """Confirm native drawing succeeded before publishing visible readiness."""
        width,height=rect.right-rect.left,rect.bottom-rect.top
        if not u.SetWindowPos(overlay,w.HWND(-1),rect.left,rect.top,width,height,0x10|0x40):
            raise OSError('Cannot position target indicator')
        dc=u.GetDC(overlay)
        if not dc: raise OSError('Cannot acquire target indicator surface')
        black=edge=None
        try:
            black=g.CreateSolidBrush(0)
            edge=g.CreateSolidBrush(0xF5DFBC)
            if not black or not edge: raise OSError('Cannot create target indicator brushes')
            boxes=[(w.RECT(0,0,width,height),black)]
            boxes.extend((box,edge) for box in (
                w.RECT(0,0,width,2),w.RECT(0,height-2,width,height),
                w.RECT(0,0,2,height),w.RECT(width-2,0,width,height)))
            boxes.extend((w.RECT(*segment),edge) for segment in marks)
            for box,brush in boxes:
                if not u.FillRect(dc,ctypes.byref(box),brush):
                    raise OSError('Cannot draw target indicator')
            if not u.SetLayeredWindowAttributes(overlay,0,alpha,3):
                raise OSError('Cannot display target indicator')
        finally:
            if black: g.DeleteObject(black)
            if edge: g.DeleteObject(edge)
            u.ReleaseDC(overlay,dc)
        if alpha>=120:
            was_visible=self.shown.is_set()
            self.shown.set()
            if self.action_lifecycle and not was_visible: _record(self, 'restored' if self.was_shown else 'visible')
            self.was_shown=True

    def _run_native(self):
        overlay=None
        target_handle=None
        try:
            u=ctypes.WinDLL('user32',use_last_error=True)
            k=ctypes.WinDLL('kernel32',use_last_error=True)
            g=ctypes.WinDLL('gdi32',use_last_error=True)
            ptr=ctypes.c_ssize_t
            proc=ctypes.WINFUNCTYPE(ptr,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
            enumproc=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
            class WC(ctypes.Structure):
                _fields_=[('style',w.UINT),('proc',proc),('cls',ctypes.c_int),('wnd',ctypes.c_int),('instance',w.HINSTANCE),('icon',w.HICON),('cursor',w.HANDLE),('brush',w.HBRUSH),('menu',w.LPCWSTR),('name',w.LPCWSTR)]
            # Explicit pointer-width signatures are essential on 64-bit Windows.
            for name,args,ret in (
                ('DefWindowProcW',[w.HWND,w.UINT,w.WPARAM,w.LPARAM],ptr),
                ('CreateWindowExW',[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,w.LPVOID],w.HWND),
                ('DestroyWindow',[w.HWND],w.BOOL),('GetDC',[w.HWND],w.HDC),('ReleaseDC',[w.HWND,w.HDC],ctypes.c_int),
                ('GetWindowRect',[w.HWND,ctypes.POINTER(w.RECT)],w.BOOL),('GetWindowThreadProcessId',[w.HWND,ctypes.POINTER(w.DWORD)],w.DWORD),
                ('GetForegroundWindow',[],w.HWND),('IsWindow',[w.HWND],w.BOOL),('IsWindowVisible',[w.HWND],w.BOOL),('IsIconic',[w.HWND],w.BOOL),
                ('ShowWindow',[w.HWND,ctypes.c_int],w.BOOL),('SetWindowPos',[w.HWND,w.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.UINT],w.BOOL),
                ('SetLayeredWindowAttributes',[w.HWND,w.DWORD,ctypes.c_ubyte,w.DWORD],w.BOOL),
                ('RegisterClassW',[ctypes.POINTER(WC)],w.WORD),('UnregisterClassW',[w.LPCWSTR,w.HINSTANCE],w.BOOL),
                ('PeekMessageW',[ctypes.POINTER(w.MSG),w.HWND,w.UINT,w.UINT,w.UINT],w.BOOL),
                ('TranslateMessage',[ctypes.POINTER(w.MSG)],w.BOOL),('DispatchMessageW',[ctypes.POINTER(w.MSG)],ptr),
            ):
                fn=getattr(u,name); fn.argtypes=args; fn.restype=ret
            k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]; k.OpenProcess.restype=w.HANDLE
            k.CloseHandle.argtypes=[w.HANDLE]; k.CloseHandle.restype=w.BOOL
            k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]; k.QueryFullProcessImageNameW.restype=w.BOOL
            k.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]; k.GetExitCodeProcess.restype=w.BOOL
            k.GetPackageFamilyName.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD),w.LPWSTR]
            k.GetModuleHandleW.argtypes=[w.LPCWSTR]; k.GetModuleHandleW.restype=w.HMODULE
            k.ProcessIdToSessionId.argtypes=[w.DWORD,ctypes.POINTER(w.DWORD)]; k.ProcessIdToSessionId.restype=w.BOOL
            current_session=w.DWORD()
            if not k.ProcessIdToSessionId(os.getpid(),ctypes.byref(current_session)): return
            candidates=[]
            @enumproc
            def collect(hwnd,_):
                if not u.IsWindowVisible(hwnd): return True
                pid=w.DWORD(); u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                session=w.DWORD()
                if not k.ProcessIdToSessionId(pid.value,ctypes.byref(session)) or session.value!=current_session.value: return True
                handle=k.OpenProcess(0x1000,False,pid.value) # Query only; no terminate rights.
                if not handle: return True
                try:
                    length=w.DWORD(32768); buffer=ctypes.create_unicode_buffer(length.value)
                    if k.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(length)):
                        image=check_path(Path(buffer.value))
                        if image.name.casefold()==self.executable:
                            family=ctypes.create_unicode_buffer(512); family_size=w.DWORD(512)
                            package=family.value if k.GetPackageFamilyName(handle,ctypes.byref(family_size),family)==0 else None
                            if not accepts_glow_process(self.executable,image,package): return True
                            candidates.append((hwnd,pid.value))
                except (PermissionError,OSError): pass
                finally: k.CloseHandle(handle)
                return True
            u.EnumWindows.argtypes=[enumproc,w.LPARAM]; u.EnumWindows.restype=w.BOOL
            acquisition_started=time.monotonic()
            while not self.stop_event.is_set():
                candidates.clear()
                u.EnumWindows(collect,0)
                foreground=u.GetForegroundWindow()
                selected=[item for item in candidates if item[0]==foreground]
                if len(selected)==1:
                    target,pid=selected[0]
                    break
                if not self.action_lifecycle:
                    if len(candidates)!=1: return
                    target,pid=candidates[0]
                    break
                now=time.monotonic()
                if now-acquisition_started>=8 or (self.finished_at is not None and now-self.finished_at>=2):
                    _record(self, 'not_acquired')
                    return
                self.stop_event.wait(.1) # Only bounded, active asynchronous focus acquisition.
            else: return
            if self.stop_event.is_set(): return
            if self.action_lifecycle: _record(self, 'acquired')
            if self.exact_window is not None and (int(target),pid)!=self.exact_window:
                return # Never decorate a different window after selection changed.
            target_handle=k.OpenProcess(0x1000,False,pid)
            if not target_handle: return
            @proc
            def window_proc(hwnd,msg,wp,lp):
                if msg==0x84: return -1 # HTTRANSPARENT
                if msg==0x21: return 3 # MA_NOACTIVATE
                return u.DefWindowProcW(hwnd,msg,wp,lp)
            instance=k.GetModuleHandleW(None)
            name='JarvisBorder'+str(id(self))
            wc=WC(0,window_proc,0,0,instance,None,None,None,None,name)
            if not u.RegisterClassW(ctypes.byref(wc)): return
            try:
                # Layered, transparent to input, hidden from taskbar, no activation.
                overlay=u.CreateWindowExW(0x80000|0x20|0x80|0x08000000,name,'Jarvis activity',0x80000000,0,0,0,0,w.HWND(target),None,instance,None)
                if not overlay: return
                self.hwnd=overlay
                if not u.SetLayeredWindowAttributes(overlay,0,0,3):
                    return # Black colorkey + alpha must be established before showing.
                g.CreateSolidBrush.argtypes=[w.DWORD]; g.CreateSolidBrush.restype=w.HBRUSH
                g.DeleteObject.argtypes=[w.HANDLE]; g.DeleteObject.restype=w.BOOL
                u.FillRect.argtypes=[w.HDC,ctypes.POINTER(w.RECT),w.HBRUSH]; u.FillRect.restype=ctypes.c_int
                started=time.monotonic()
                first_visible=None
                post_focus_visible=0
                last_frame=time.monotonic()
                self.ready.set()
                while not self.stop_event.is_set():
                    if self.action_lifecycle and self.action_lifetime_complete(post_focus_visible,first_visible): break
                    exit_code=w.DWORD()
                    if not k.GetExitCodeProcess(target_handle,ctypes.byref(exit_code)) or exit_code.value!=259: break
                    if self.duration is not None and time.monotonic()-started>=self.duration:
                        self.completed=self.shown.is_set() and self.was_shown
                        break
                    if not u.IsWindow(target): break
                    current_pid=w.DWORD(); u.GetWindowThreadProcessId(target,ctypes.byref(current_pid))
                    if current_pid.value!=pid: break # Never follow a reused HWND.
                    rect=w.RECT()
                    if u.GetForegroundWindow()!=target or u.IsIconic(target) or not u.IsWindowVisible(target) or not u.GetWindowRect(target,ctypes.byref(rect)):
                        if self.action_lifecycle and self.shown.is_set(): _record(self, 'hidden')
                        self.shown.clear()
                        u.ShowWindow(overlay,0)
                        if self.control_bounds is not None: break
                    else:
                        width,height=rect.right-rect.left,rect.bottom-rect.top
                        if width<=0 or height<=0: break
                        elapsed=time.monotonic()-started
                        marks=[]
                        if self.control_bounds is not None:
                            marks=reticle_segments(self.control_bounds(),(rect.left,rect.top,rect.right,rect.bottom),elapsed)
                            if not marks:
                                self.shown.clear()
                                u.ShowWindow(overlay,0)
                                break # Lost/invalid geometry: never leave a stale reticle.
                        alpha=int(min(1,elapsed/.18)*(150+20*math.sin(elapsed*2)))
                        self._paint_frame(u,g,overlay,rect,marks,alpha)
                        if self.shown.is_set() and first_visible is None: first_visible=time.monotonic()
                        if self.action_lifecycle and self.action_finished.is_set() and self.shown.is_set():
                            post_focus_visible += min(.1,time.monotonic()-last_frame)
                        if self.on_ready is not None and not self.action_attempted and elapsed>=.3 and self.shown.is_set():
                            self.action_attempted=True
                            self.on_ready() # Trusted callback, same UIA apartment, one attempt only.
                    # Poll only while an action is active. No idle background loop.
                    last_frame=time.monotonic()
                    message=w.MSG()
                    while u.PeekMessageW(ctypes.byref(message),None,0,0,1):
                        u.TranslateMessage(ctypes.byref(message)); u.DispatchMessageW(ctypes.byref(message))
                    self.stop_event.wait(.05)
            finally:
                if overlay: u.DestroyWindow(overlay)
                self.hwnd=None
                u.UnregisterClassW(name,instance)
        except (OSError,ValueError,AttributeError) as exc:
            if self.action_lifecycle: _record(self, 'unavailable:' + type(exc).__name__)
        finally:
            if target_handle: k.CloseHandle(target_handle)
            self.shown.clear()
            self.ready.set()


def executable_for(action,target):
    # Fixed app-specific display mapping. Qwen cannot supply process names/HWNDs.
    if action=='spotify_playback' or target in {'Spotify','Spotify Web','Default playlist'}: return 'spotify.exe' if target!='Spotify Web' else 'chrome.exe'
    if target=='Chrome' or target=='Python documentation': return 'chrome.exe'
    if target=='Epic Games Launcher': return 'EpicGamesLauncher.exe'
    if action=='open_resource':
        from tool_broker import known_resources
        resource=known_resources().get(target,{})
        if resource.get('kind')=='project': return 'Code.exe'
        if resource.get('kind')=='playlist': return 'spotify.exe'
    return None


@contextmanager
def action_glow(action,target):
    executable=executable_for(action,target)
    if os.name!='nt' or not executable:
        yield
        return
    close_all() # One active app indicator, including rapid multi-action changes.
    border=NativeBorder(executable, action_lifecycle=True)
    with _active_lock: _active.add(border)
    try:
        try:
            border.start()
        except (OSError,RuntimeError):
            border.close()
            with _active_lock: _active.discard(border)
        safety.safety.ensure_running()
        with safety.safety.operation(border.close):
            yield
    except BaseException:
        border.close()
        raise
    else:
        # The native thread retains its Stop callback through the post-focus indication.
        border.finish()
