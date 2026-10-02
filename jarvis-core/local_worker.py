"""Fixed private speech worker. Input is data, never commands or Python code."""
import base64
import json
import sys


def main():
    kind = sys.argv[1]
    if kind not in {"speak", "transcribe", "voices", "observe", "preview"}:
        raise ValueError("Unknown local worker")
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            if kind == "preview":
                from computer_observation import preview, play_playlist
                if payload.get('mode') == 'spotify_playlist':
                    value = play_playlist(payload['target'])
                else:
                    value = preview(payload['target'], payload['window_id'], payload['control'],payload.get('action','preview'))
            elif kind == "observe":
                from computer_observation import observe, focus
                mode = payload.get('mode', 'observe')
                if mode not in {'observe', 'focus'}: raise PermissionError('Unsupported computer action')
                value = focus(payload['target']) if mode == 'focus' else observe(payload["target"])
            elif kind == "voices":
                from local_tts import installed_voices
                value = installed_voices()
            elif kind == "speak":
                from local_tts import synthesize
                value = base64.b64encode(synthesize(payload["text"], payload.get("voice", ""))).decode("ascii")
            else:
                from speech import transcribe_audio
                value = transcribe_audio(base64.b64decode(payload["audio"], validate=True))
            result = {"ok": True, "value": value}
            if kind == 'preview':
                from computer_observation import FOREGROUND_TRACE, SCROLL_TRACE
                if FOREGROUND_TRACE is not None: result['foreground_trace'] = FOREGROUND_TRACE
                if SCROLL_TRACE is not None: result['scroll_trace'] = SCROLL_TRACE
        except Exception as exc:
            result = {"ok": False, "error": "Window action unavailable; inspect one supported window again" if kind in {"observe", "preview"} else "Local speech processing failed"}
            if kind in {"observe", "preview"}:
                import traceback
                result['diagnostic'] = type(exc).__name__ + ' ' + ' '.join(frame.name + ':' + str(frame.lineno) for frame in traceback.extract_tb(exc.__traceback__))
                from computer_observation import ForegroundUnavailableError
                if isinstance(exc, ForegroundUnavailableError):
                    result['diagnostic'] += ' ' + exc.diagnostic
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
