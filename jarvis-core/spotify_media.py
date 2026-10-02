"""Read and control only the Windows media session published by Spotify."""

import asyncio
import time
import safety as safety_runtime

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)


SPOTIFY_SESSION_IDS = {
    "spotify.exe",
    "spotifyab.spotifymusic_zpdnekdrzrea0!spotify",
}


async def _manager():
    return await SessionManager.request_async()


async def _spotify_session():
    manager = await _manager()
    for session in manager.get_sessions():
        if (session.source_app_user_model_id or "").casefold() in SPOTIFY_SESSION_IDS:
            return session
    return None


async def _status():
    session = await _spotify_session()
    if session is None:
        return {"available": False, "playing": False}
    state = session.get_playback_info().playback_status
    return {"available": True, "playing": state == PlaybackStatus.PLAYING}


def spotify_status() -> dict:
    return asyncio.run(_status())


async def _control(command: str) -> dict:
    safety_runtime.safety.ensure_running()
    session = await _spotify_session()
    safety_runtime.safety.ensure_running()
    if session is None:
        raise RuntimeError("Spotify has no active Windows media session. Start a track in Spotify first.")
    if command == "play":
        accepted = await session.try_play_async()
    elif command == "pause":
        accepted = await session.try_pause_async()
    else:
        raise ValueError("Only Spotify play and pause are available.")
    if not accepted:
        raise RuntimeError("Spotify did not accept the playback request.")
    deadline = time.monotonic() + .8
    while True:
        safety_runtime.safety.ensure_running()
        playing = session.get_playback_info().playback_status == PlaybackStatus.PLAYING
        if playing == (command == 'play') or time.monotonic() >= deadline:
            return {"request_accepted": True, "playing": playing}
        await asyncio.sleep(.05)


def control_spotify(command: str) -> dict:
    async def cancellable():
        with safety_runtime.safety.async_activity():
            return await _control(command)
    try:
        return asyncio.run(cancellable())
    except asyncio.CancelledError as exc:
        raise safety_runtime.StoppedError("Spotify request cancelled by Emergency Stop") from exc


def play_registered_playlist(name):
    """Use the existing controller and owned UIA worker, never generic media resume."""
    from computer_controller import play_playlist
    return play_playlist(name)
