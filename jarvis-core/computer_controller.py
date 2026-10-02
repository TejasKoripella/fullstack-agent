"""Trusted boundary for observation, focus, visual previews and scoped context.

Permissions remain in the existing broker pipeline. Accessibility output is
untrusted data, never an authorization or an executable action.
"""
from capability_registry import inspectable_apps, INSPECTION_POLICIES
from computer_observation import MAX_CONTROLS, safe_label
from owned_workers import run_worker
import safety as safety_runtime
import re
import math
import time
import secrets
import threading
import copy

_references = {}
_reference_lock = threading.RLock()
_previews = {}


def cancel_preview(ticket, scope):
    with _reference_lock:
        active = _previews.get(ticket)
        if active is not None and active[0] == scope:
            active[1].set()
            return True
        pending = _references.get(ticket)
        if pending is not None and pending[0] == scope:
            _references.pop(ticket, None)
            return True
    return False


def issue_reference(snapshot, scope, purpose='preview'):
    """Short-lived UI capability for one preview, never a permission grant."""
    epoch = safety_runtime.safety.ensure_running()
    if purpose not in {'preview','context','control'}: raise PermissionError('Unsupported window reference purpose')
    if not isinstance(scope, str) or not 1 <= len(scope) <= 100:
        raise PermissionError('A workspace scope is required')
    clean = validate_observation(snapshot['app'], snapshot)
    if snapshot.get('capture_epoch') != epoch:
        raise safety_runtime.StoppedError('Inspect this window again')
    captured = snapshot.get('captured_at')
    if type(captured) not in (int, float) or not 0 <= time.monotonic()-captured <= 60:
        raise StaleTargetError('Inspect this window again')
    clean.update(capture_epoch=epoch, captured_at=captured)
    with _reference_lock:
        for key, (owner, old, old_purpose) in list(_references.items()):
            if old['capture_epoch'] != epoch or time.monotonic()-old['captured_at'] > (300 if old_purpose == 'context' else 60):
                _references.pop(key, None)
        while len(_references) >= 32:
            _references.pop(next(iter(_references)))
        ticket = secrets.token_hex(32)
        _references[ticket] = (scope, copy.deepcopy(clean), purpose)
    return ticket


def consume_snapshot(ticket, scope, purpose, *, consume=True):
    epoch = safety_runtime.safety.ensure_running()
    with _reference_lock:
        entry = _references.get(ticket)
        if entry is None or entry[0] != scope or entry[2] != purpose:
            raise PermissionError('This window reference is unavailable in this workspace')
        if consume: _references.pop(ticket)
    snapshot = entry[1]
    if snapshot['capture_epoch'] != epoch:
        raise safety_runtime.StoppedError('This window reference was cancelled; inspect it again')
    if not 0 <= time.monotonic()-snapshot['captured_at'] <= (300 if purpose == 'context' else 60):
        raise StaleTargetError('This window reference expired; inspect it again')
    if snapshot['app'] not in inspectable_apps(): raise PermissionError('That application is no longer supported')
    return snapshot


def consume_reference(ticket, scope, identifier):
    snapshot = consume_snapshot(ticket, scope, 'preview')
    control = resolve_control(snapshot, dict(snapshot, captured_at=time.monotonic()), identifier)
    return snapshot, control


def window_context(ticket, scope):
    """One-message historical observation, never an action capability."""
    snapshot = consume_snapshot(ticket, scope, 'context')
    lines = ['App: '+snapshot['app'], 'Registered window surface: '+INSPECTION_POLICIES[snapshot['app']]['surface'],
             'Embedded document labels do not change the registered window identity.', 'Window title: '+snapshot['window_title'],
             'Snapshot age: %d seconds. This is not a live screen.' % (time.monotonic()-snapshot['captured_at']),
             'Traversal incomplete: '+str(snapshot['partial']), 'Observed control labels (may include offscreen controls):']
    for item in snapshot['controls']:
        lines.append(item['name']+' [enabled='+str(item['enabled'])+', offscreen='+str(item['offscreen'])+']')
    text = '\n'.join(lines)
    result = {'app':snapshot['app'], 'text':text[:6000], 'truncated':len(text)>6000}
    candidates = [item for item in snapshot['controls'] if item.get('scrollable') is True
                  and item['enabled'] and not item['offscreen']
                  and item['bounds'][2]>item['bounds'][0] and item['bounds'][3]>item['bounds'][1]][:12]
    if candidates and time.monotonic()-snapshot['captured_at'] <= 60:
        frame = snapshot['controls'][0]['bounds']
        width,height = frame[2]-frame[0],frame[3]-frame[1]
        panes = {}
        for index,item in enumerate(candidates):
            left,top,right,bottom=item['bounds']
            center = ((left+right)/2-frame[0])/width if width>0 else .5
            width_fraction = min(1,(right-left)/width) if width>0 else 0
            height_fraction = min(1,(bottom-top)/height) if height>0 else 0
            panes['pane_'+str(index+1)] = {'id':item['id'],'label':item['name'] or 'Unnamed scroll pane',
                'role':{50030:'document',50026:'group',50033:'pane'}.get(item['type'],'control'),
                'region':'whole window' if width_fraction>.8 and height_fraction>.8 else
                         'left' if center<.35 else 'right' if center>.65 else 'center',
                'width_fraction':round(width_fraction,2),'height_fraction':round(height_fraction,2)}
        result['action_context'] = {'reference':issue_reference(snapshot,scope,purpose='control'),
                                   'scope':scope,'app':snapshot['app'],
                                   'panes':panes}
    return result


def propose_scroll(context, pane, direction):
    """Resolve a model proposal against user-attached data, without sending input.

    Opaque action references come from trusted context preparation, never Qwen.
    Execution consumes the reference only after a separate fresh UI approval.
    """
    from computer_action_policy import validate_action
    if not isinstance(context,dict) or direction not in {'up','down'} or pane not in context.get('panes',{}):
        raise PermissionError('Choose one pane from the explicitly attached window snapshot')
    snapshot = consume_snapshot(context['reference'],context['scope'],'control',consume=False)
    identifier = context['panes'][pane]['id']
    control = resolve_control(snapshot,dict(snapshot,captured_at=time.monotonic()),identifier)
    action = 'scroll_'+direction
    validate_action(snapshot['app'],control,action)
    return {'action_type':'scroll_control','target':snapshot['app'],'status':'approval_required',
            'persistent_eligible':False,'safety_epoch':snapshot['capture_epoch'],
            'reference':context['reference'],'workspace_scope':context['scope'],
            'control_id':control['id'],'control_label':control['name'] or 'Unnamed scroll pane',
            'action':action,'message':'Sure, I’ll scroll the selected '+snapshot['app']+' pane '+direction+'.'}


def preview(ticket, scope, identifier):
    return execute_control(ticket,scope,identifier,'preview',purpose='preview')


def execute_control(ticket,scope,identifier,action,purpose='control'):
    from computer_action_policy import validate_action
    if purpose not in {'control','preview'} or (purpose=='preview' and action!='preview'):
        raise PermissionError('Preview references cannot authorize input actions')
    with safety_runtime.safety.operation() as epoch:
        cancel = threading.Event()
        with _reference_lock:
            snapshot=consume_snapshot(ticket,scope,purpose)
            control=resolve_control(snapshot,dict(snapshot,captured_at=time.monotonic()),identifier)
            validate_action(snapshot['app'],control,action)
            _previews[ticket] = (scope, cancel)
        try:
            result = run_worker('preview', {'target': snapshot['app'], 'window_id': snapshot['window_id'],
                                'control': {key: control[key] for key in ('id', 'name', 'type', 'context_id','scrollable')},
                                **({'action':action} if action!='preview' else {})}, cancel_event=cancel)
            if cancel.is_set(): raise RuntimeError('Target preview cancelled')
        finally:
            with _reference_lock: _previews.pop(ticket, None)
        safety_runtime.safety.ensure_running(epoch)
        if action!='preview':
            return validate_action_result(snapshot['app'],action,result)
        if result != {'app': snapshot['app'], 'preview_shown': True, 'input_sent': False}:
            raise RuntimeError('The target indicator could not be confirmed')
        return result


def validate_action_result(app,action,result):
    if not isinstance(result,dict) or result.get('app')!=app or result.get('action')!=action \
            or result.get('indicator_shown') is not True or type(result.get('indicator_completed')) is not bool \
            or type(result.get('action_attempted')) is not bool \
            or result.get('outcome') not in {'verified','unknown','boundary','unsupported'}:
        raise RuntimeError('The computer action result could not be verified')
    clean={key:result[key] for key in ('app','action','indicator_shown','indicator_completed','action_attempted','outcome')}
    if result['outcome']=='verified':
        before,after=result.get('before'),result.get('after')
        if not result['action_attempted'] or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=100 for v in (before,after)) \
                or not (after>before if action=='scroll_down' else after<before):
            raise RuntimeError('The scroll movement was not verified')
        clean.update(before=before,after=after)
    elif result['outcome'] in {'boundary','unsupported'} and result['action_attempted']:
        raise RuntimeError('The scroll result is inconsistent')
    elif result['outcome']=='unknown' and not result['action_attempted']:
        raise RuntimeError('The scroll attempt was not confirmed')
    return clean


class StaleTargetError(RuntimeError):
    """A new observation is required; this does not mean Jarvis is stopped."""


def valid_identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def valid_bounds(value):
    return isinstance(value, list) and len(value) == 4 and all(
        type(number) in (int, float) and math.isfinite(number) and abs(number) <= 1000000 for number in value)


def validate_observation(target, value):
    if not isinstance(value, dict) or value.get('app') != target or value.get('read_only') is not True:
        raise RuntimeError('Window inspection returned an invalid target or mode')
    if not isinstance(value.get('partial'), bool) or not isinstance(value.get('window_title'), str):
        raise RuntimeError('Window inspection returned invalid snapshot metadata')
    if not valid_identifier(value.get('window_id')):
        raise RuntimeError('Window inspection returned no reliable window identity')
    controls = value.get('controls')
    if not isinstance(controls, list) or len(controls) > MAX_CONTROLS:
        raise RuntimeError('Window inspection exceeded its control limit')
    clean, identifiers = [], set()
    for control in controls:
        if not isinstance(control, dict) or not isinstance(control.get('name'), str) \
                or type(control.get('type')) is not int \
                or type(control.get('enabled')) is not bool \
                or type(control.get('offscreen')) is not bool:
            raise RuntimeError('Window inspection returned invalid control data')
        identifier = control.get('id')
        context_id = control.get('context_id')
        scrollable=control.get('scrollable',False)
        if type(scrollable) is not bool: raise RuntimeError('Window inspection returned invalid pattern metadata')
        if context_id is not None and not valid_identifier(context_id):
            raise RuntimeError('Window inspection returned invalid control context')
        if identifier is not None and (not valid_identifier(identifier) or identifier in identifiers):
            raise RuntimeError('Window inspection returned ambiguous control identities')
        if not valid_bounds(control.get('bounds')):
            raise RuntimeError('Window inspection returned invalid control geometry')
        if identifier is not None: identifiers.add(identifier)
        clean.append({'name': safe_label(control['name']), 'type': control['type'],
                      'enabled': control['enabled'], 'offscreen': control['offscreen'],
                      'id': identifier, 'context_id': context_id, 'scrollable':scrollable, 'bounds': control['bounds'][:]})
    # Whitelist fields. Worker/provider output cannot inject permission, action,
    # shell, process handle or overlay instructions into a broker result.
    return {'app': target, 'window_title': safe_label(value['window_title']),
            'window_id': value['window_id'],
            'controls': clean, 'partial': value['partial'], 'read_only': True}


def resolve_control(previous, fresh, identifier):
    """Reconcile an intended control against a new snapshot. Never executes input.

    Callers must obtain snapshots through approved observation; comparison
    neither authorizes an action nor makes stale geometry safe to click.
    """
    epoch = safety_runtime.safety.ensure_running()
    now = time.monotonic()
    for snapshot, maximum_age in ((previous, 60), (fresh, 5)):
        captured = snapshot.get('captured_at')
        if snapshot.get('capture_epoch') != epoch:
            raise safety_runtime.StoppedError('This control snapshot was cancelled; inspect it again')
        if type(captured) not in (int, float) \
                or not math.isfinite(captured) or not 0 <= now - captured <= maximum_age:
            raise StaleTargetError('The intended control snapshot expired; inspect it again')
    if previous['app'] != fresh['app'] or previous['window_id'] != fresh['window_id'] or not valid_identifier(identifier):
        raise PermissionError('The intended window or control changed; inspect it again')
    before = [item for item in previous['controls'] if item['id'] == identifier]
    after = [item for item in fresh['controls'] if item['id'] == identifier]
    if len(before) != 1 or len(after) != 1:
        raise PermissionError('The intended control is missing or ambiguous')
    control = after[0]
    if not valid_identifier(before[0].get('context_id')) or before[0]['context_id'] != control.get('context_id'):
        raise PermissionError('The intended control context changed; inspect it again')
    left, top, right, bottom = control['bounds']
    if (before[0]['name'], before[0]['type']) != (control['name'], control['type']) \
            or control['offscreen'] or not control['enabled'] or right <= left or bottom <= top:
        raise PermissionError('The intended control changed or is unavailable')
    return dict(control, bounds=control['bounds'][:])


def observe(target):
    if target not in inspectable_apps():
        raise PermissionError('That application cannot be inspected')
    with safety_runtime.safety.operation() as epoch:
        started = time.monotonic()
        snapshot = run_worker('observe', {'target': target})
        safety_runtime.safety.ensure_running(epoch)
        result = validate_observation(target, snapshot)
        # Only trusted controller code supplies epoch/time, never worker fields.
        result.update(capture_epoch=epoch, captured_at=started)
        return result


def focus(target):
    if target not in inspectable_apps():
        raise PermissionError('That application cannot be focused')
    with safety_runtime.safety.operation() as epoch:
        result = run_worker('observe', {'target': target, 'mode': 'focus'})
        safety_runtime.safety.ensure_running(epoch)
        if result != {'app': target, 'focused': True}:
            raise RuntimeError('The selected window was not confirmed in the foreground')
        return result


def play_playlist(name):
    from tool_broker import known_resources, resource_path
    if resource_path(name)[0] != 'playlist': raise PermissionError('Only registered playlists can play')
    item = known_resources()[name]
    if not item.get('view_name'):
        return {'resource_kind':'playlist', 'playback_confirmed':False, 'action_attempted':False}
    with safety_runtime.safety.operation() as epoch:
        result = run_worker('preview', {'mode':'spotify_playlist', 'target':name})
        safety_runtime.safety.ensure_running(epoch)
        if not isinstance(result,dict) or set(result) != {'resource_kind','playback_confirmed','action_attempted'} \
                or result['resource_kind'] != 'playlist' or any(type(result[key]) is not bool for key in ('playback_confirmed','action_attempted')):
            raise RuntimeError('Spotify returned an unverified playback result')
        return result
