"""Central deterministic policy for currently implemented generic control actions.

Observed labels and model text never classify an action as safe or authorize it.
The action kind fixes the effect: preview or one accessibility scroll only.
Unknown click/type/keyboard/consequential proposals remain unsupported here.
"""
from capability_registry import inspectable_apps, ACTION_CONTRACTS


def validate_action(target,control,action):
    if target not in inspectable_apps() or action not in {'preview','scroll_up','scroll_down'}:
        raise PermissionError('That computer action is not implemented in the trusted controller')
    contract = ACTION_CONTRACTS['preview_control' if action=='preview' else 'scroll_control']
    if contract.permission_scope != 'fresh_once_scoped_reference' or contract.persistent \
            or contract.consequence != ('visual_preview' if action=='preview' else 'reversible'):
        raise PermissionError('This control action requires its trusted fresh scoped contract')
    if action!='preview' and control.get('scrollable') is not True:
        raise PermissionError('This observed control does not expose accessibility scrolling')


def validate_playlist_action(resource, control):
    """Narrow registered Spotify action, never an arbitrary Invoke/click capability."""
    from tool_broker import known_resources, resource_path
    if resource_path(resource)[0] != 'playlist': raise PermissionError('Only registered playlists can play')
    view = known_resources()[resource].get('view_name')
    title = view.split(' - playlist by ',1)[0] if view else None
    if not title or control.get('type') != 50000 or control.get('name') not in {'Play '+title,'Pause '+title} \
            or control.get('enabled') is not True or control.get('offscreen') is not False:
        raise PermissionError('The registered playlist playback control is unavailable')
