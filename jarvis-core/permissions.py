"""Deterministic, narrow permissions for named, low-risk opening actions."""

import time
from tool_responses import receipt
from window_glow import action_glow
from capability_registry import inspectable_apps, ACTION_CONTRACTS, persistent_permission_eligible
import safety as safety_runtime
from memory import MemoryStore
from security import assert_not_admin, check_path
from tool_broker import ALLOWED_APPS, ALLOWED_PACKAGED_APPS, ALLOWED_SETTINGS, ALLOWED_SITES, ToolBroker, documents_root, known_resources, resource_path

ACTION_TARGETS = {
    "open_app": lambda: set(ALLOWED_APPS) | set(ALLOWED_PACKAGED_APPS),
    "open_site": lambda: set(ALLOWED_SITES),
    "open_settings": lambda: set(ALLOWED_SETTINGS),
    "open_documents": lambda: {"Windows Documents"},
    "open_resource": lambda: set(known_resources()),
    "spotify_playback": lambda: {"Spotify Play", "Spotify Pause"} | {name for name,item in known_resources().items() if item['kind']=='playlist'},
    "inspect_app": inspectable_apps,
    "focus_app": inspectable_apps,
}

# Explicit low-risk capability classification. Future tools default to fresh confirmation.
PERSISTENT_ACTIONS = frozenset(action for action in ACTION_CONTRACTS if persistent_permission_eligible(action))


def validate(action_type: str, target: str) -> tuple[str, str]:
    """Run hard checks before any lookup, grant, or execution."""
    safety_runtime.safety.ensure_running()
    assert_not_admin()
    if action_type not in ACTION_TARGETS:
        raise PermissionError("This action cannot receive a saved permission.")
    targets = {name.casefold(): name for name in ACTION_TARGETS[action_type]()}
    canonical = targets.get(target.strip().casefold())
    if canonical is None:
        raise PermissionError("That target is not allowed.")
    if action_type == "open_app" and canonical in ALLOWED_APPS:
        path = check_path(ALLOWED_APPS[canonical])
        if not path.is_file() or path.suffix.lower() != ".exe":
            raise PermissionError("The configured app is unavailable.")
    if action_type == "open_documents":
        try:
            documents_root()
        except OSError as exc:
            raise PermissionError("The Windows Documents folder is unavailable.") from exc
    if action_type == "open_resource":
        resource_path(canonical)
    if action_type == "spotify_playback" and canonical not in {"Spotify Play", "Spotify Pause"}:
        if resource_path(canonical)[0] != 'playlist': raise PermissionError('That target is not a registered playlist')
    return action_type, canonical


def execute(broker: ToolBroker, action_type: str, target: str) -> dict:
    if action_type == "focus_app":
        return broker.focus_app(target, approved=True)
    if action_type == "inspect_app":
        return broker.inspect_app(target, approved=True)
    if action_type == "open_resource":
        return broker.open_resource(target, approved=True)
    if action_type == "open_app":
        if target in ALLOWED_APPS:
            pid = broker.open_app(target, approved=True)
            return {"pid": pid} if pid is not None else {"request_sent": True}
        broker.open_packaged_app(target, approved=True)
        return {"request_sent": True}
    if action_type == "open_site":
        broker.open_site(target, approved=True)
        return {"request_sent": True}
    if action_type == "open_documents":
        broker.open_documents(approved=True)
        return {"request_sent": True}
    if action_type == "spotify_playback":
        return broker.spotify_playback(target, approved=True)
    broker.open_settings(target)
    return {"request_sent": True}


def dispatch(store: MemoryStore, broker: ToolBroker, action_type: str, target: str,
             decision: str | None = None) -> dict:
    started = time.perf_counter()
    epoch = safety_runtime.safety.ensure_running()
    try:
        action_type, target = validate(action_type, target)
        # Validation may yield while Stop/Resume changes the safety generation.
        # A cancelled approval must not reach permission storage or lookup.
        safety_runtime.safety.ensure_running(epoch)
    except safety_runtime.StoppedError:
        store.log_action(action_type, target, False, False, "Approval cancelled by Emergency Stop",
                         write_approved=True, authorization_source="cancelled", security_result="cancelled",
                         execution_result="cancelled", latency_ms=round((time.perf_counter() - started) * 1000))
        raise
    except PermissionError as exc:
        store.log_action(action_type, target, False, False, "Hard security rejected: " + str(exc),
                         write_approved=True, authorization_source="none", security_result="rejected",
                         execution_result="not_run", latency_ms=round((time.perf_counter() - started) * 1000))
        raise
    if decision not in {None, "allow_once", "always_allow", "deny"}:
        raise ValueError("Unknown approval choice.")
    eligible = persistent_permission_eligible(action_type)
    if not eligible and decision == "always_allow":
        raise PermissionError("This action requires fresh Allow Once approval")
    if decision == "deny":
        store.log_action(action_type, target, False, False, "User denied", write_approved=True,
                         authorization_source="user_denied", security_result="passed",
                         execution_result="not_run", latency_ms=round((time.perf_counter() - started) * 1000))
        return {"message": receipt({"status":"denied","target":target,"action_type":action_type}), "status": "denied", "safety_epoch": epoch, "action_type": action_type, "target": target,
                "security_result": "passed", "latency_ms": round((time.perf_counter() - started) * 1000)}
    saved = eligible and store.has_permission(action_type, target)
    if not saved and decision is None:
        store.log_action(action_type, target, False, False, "First-time approval required", write_approved=True,
                         authorization_source="pending", security_result="passed",
                         execution_result="not_run", latency_ms=round((time.perf_counter() - started) * 1000))
        return {"message": receipt({"status":"approval_required","target":target,"action_type":action_type}), "status": "approval_required", "safety_epoch": epoch, "action_type": action_type, "target": target,
                "persistent_eligible": eligible,
                "security_result": "passed", "latency_ms": round((time.perf_counter() - started) * 1000)}
    source = "persistent" if saved and decision is None else "always_allow" if decision == "always_allow" else "allow_once"
    try:
        if decision == "always_allow":
            safety_runtime.safety.ensure_running(epoch)
            store.grant_permission(action_type, target, approved=True, safety_epoch=epoch)
        safety_runtime.safety.ensure_running(epoch)
        with action_glow(action_type,target):
            result = execute(broker, action_type, target)
        safety_runtime.safety.ensure_running(epoch)
    except Exception as exc:
        store.log_action(action_type, target, True, False, source + ": " + type(exc).__name__,
                         write_approved=True, authorization_source=source, security_result="passed",
                         execution_result="cancelled" if isinstance(exc,safety_runtime.StoppedError) else "failed",
                         latency_ms=round((time.perf_counter() - started) * 1000))
        raise
    elapsed = round((time.perf_counter() - started) * 1000)
    store.log_action(action_type, target, True, True, "Authorized via " + source, write_approved=True,
                     authorization_source=source, security_result="passed",
                     execution_result="observed" if action_type == "inspect_app" else "focused" if action_type == "focus_app" else "request_accepted", latency_ms=elapsed)
    return {"message": receipt({"status":"executed","target":target,"action_type":action_type,**result}), "status": "executed", "safety_epoch": epoch, "action_type": action_type, "target": target,
            "source": source, "security_result": "passed", "latency_ms": elapsed, **result}
