"""Descriptions of existing controls, derived from the existing tool registries."""
from pathlib import Path
import os
from dataclasses import dataclass
from types import MappingProxyType
from security import check_path


@dataclass(frozen=True)
class ActionContract:
    """Trusted effect classification, never inferred from model/control labels.

    Exact target validation still belongs to the broker. This contract describes
    authorization requirements; it grants neither authority nor a capability.
    """
    consequence: str
    permission_scope: str
    persistent: bool = False


ACTION_CONTRACTS = MappingProxyType({
    'open_app': ActionContract('reversible','exact_target',True),
    'open_site': ActionContract('reversible','exact_target',True),
    'open_settings': ActionContract('reversible','exact_target',True),
    'open_documents': ActionContract('reversible','exact_target',True),
    'open_resource': ActionContract('reversible','exact_target',True),
    'spotify_playback': ActionContract('reversible','exact_action',True),
    'focus_app': ActionContract('reversible','exact_target',True),
    'inspect_app': ActionContract('private_observation','fresh_once'),
    'preview_control': ActionContract('visual_preview','fresh_once_scoped_reference'),
    'scroll_control': ActionContract('reversible','fresh_once_scoped_reference'),
})


def persistent_permission_eligible(action):
    contract = ACTION_CONTRACTS.get(action)
    # New/unknown effects are never silently classified as low risk.
    return bool(contract and contract.consequence == 'reversible' and contract.persistent
                and contract.permission_scope in {'exact_target','exact_action'})

# These are inspection policies, not permission grants or model instructions.
INSPECTION_POLICIES = {
    'Chrome': {'executable': 'chrome.exe', 'identity': 'configured_executable', 'surface': 'Chrome browser window'},
    'Spotify': {'executable': 'spotify.exe', 'identity': 'configured_package', 'surface': 'installed Spotify Windows app'},
}


def inspectable_apps():
    return set(INSPECTION_POLICIES)


def accepts_process(target, executable, package_family=None):
    from tool_broker import ALLOWED_APPS, ALLOWED_PACKAGED_APPS
    path = check_path(executable)
    policy = INSPECTION_POLICIES.get(target)
    if not policy or path.name.casefold() != policy['executable']:
        return False
    if target in ALLOWED_APPS:
        return os.path.normcase(str(path)) == os.path.normcase(str(check_path(ALLOWED_APPS[target])))
    package = ALLOWED_PACKAGED_APPS.get(target)
    return bool(package and package_family == package.split('!', 1)[0])


def application_capabilities():
    from tool_broker import ALLOWED_APPS, ALLOWED_PACKAGED_APPS, known_resources
    result = []
    for name in sorted(set(ALLOWED_APPS) | set(ALLOWED_PACKAGED_APPS)):
        capabilities = [{'name': 'open', 'tool': 'open_app', 'permission': 'exact_target',
                         'verification': 'windows_launch_receipt'}]
        if name == 'Spotify':
            capabilities.append({'name': 'play_pause', 'tool': 'spotify_playback', 'permission': 'exact_action',
                                 'verification': 'windows_media_session'})
            if any(item.get('kind') == 'playlist' for item in known_resources().values()):
                capabilities.append({'name': 'open_registered_playlist', 'tool': 'open_resource',
                                     'permission': 'exact_target',
                                     'verification': 'uri_launch_receipt_not_playback'})
                capabilities.append({'name':'play_registered_playlist','tool':'spotify_playback',
                                     'permission':'exact_target',
                                     'verification':'playlist_scoped_uia_control_and_spotify_media_session'})
        if name in INSPECTION_POLICIES:
            capabilities.append({'name': 'focus', 'tool': 'focus_app', 'permission': 'exact_target',
                                 'verification': 'exact_foreground_window'})
            capabilities.append({'name': 'inspect_window', 'tool': 'inspect_app', 'permission': 'fresh_once',
                                 'verification': 'bounded_uia_snapshot'})
            capabilities.append({'name': 'target_preview', 'tool': 'preview_control', 'permission': 'fresh_once_scoped_reference',
                                 'model_available': False,
                                 'verification': 'paint_readiness_visual_acceptance_unverified'})
            capabilities.append({'name': 'snapshot_context', 'tool': None, 'permission': 'explicit_one_message_reference',
                                 'persistent_eligible': False, 'model_available': False,
                                 'verification': 'controller_validated_snapshot_not_live_state'})
            capabilities.append({'name':'scroll_pane','tool':'scroll_control','permission':'fresh_once_scoped_reference',
                                 'model_available':True,'model_requires':'explicit_current_window_snapshot',
                                 'verification':'accessibility_scroll_percent_change'})
        for capability in capabilities:
            action = capability['tool']
            if action is not None:
                contract = ACTION_CONTRACTS[action]
                capability['persistent_eligible'] = persistent_permission_eligible(action)
                capability['permission'] = contract.permission_scope
                capability['consequence'] = contract.consequence
        result.append({'app': name, 'identifier': str(ALLOWED_APPS.get(name) or ALLOWED_PACKAGED_APPS.get(name)),
                       'capabilities': capabilities, 'generic_input_available': False})
    return result
