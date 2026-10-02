"""Offline Windows speech, invoked through a fixed System.Speech adapter.

Only text and an installed voice name are data. Neither can change the command.
Audio is produced in memory and is never written to a file.
"""

import json
import io
import os
from functools import lru_cache
from pathlib import Path
import subprocess
import threading
import wave


_POWERSHELL = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_ROOT = Path(__file__).resolve().parent
_PIPER_MODEL = _ROOT / "voices" / "en_US-ryan-medium.onnx"
_PIPER_LOCK = threading.Lock()
_PIPER_VOICE = None
_LIST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $names = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
  [Console]::Out.Write((ConvertTo-Json -InputObject $names -Compress))
} finally { $synth.Dispose() }
"""
_SPEAK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Speech
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$stream = New-Object System.IO.MemoryStream
try {
  if ($payload.voice) { $synth.SelectVoice([string]$payload.voice) }
  $synth.Rate = 0
  $synth.SetOutputToWaveStream($stream)
  $synth.Speak([string]$payload.text)
  $synth.SetOutputToNull()
  $bytes = $stream.ToArray()
  [Console]::OpenStandardOutput().Write($bytes, 0, $bytes.Length)
} finally {
  $synth.Dispose()
  $stream.Dispose()
}
"""


def _run(script: str, payload: bytes = b"", timeout: int = 15) -> bytes:
    if os.name != "nt" or not _POWERSHELL.is_file():
        raise RuntimeError("Offline Windows speech is unavailable.")
    try:
        result = subprocess.run(
            [str(_POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            shell=False,
            cwd=_ROOT,
            creationflags=_FLAGS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Offline Windows speech timed out.") from exc
    if result.returncode:
        raise RuntimeError("Offline Windows speech failed.")
    return result.stdout


@lru_cache(maxsize=1)
def installed_voices() -> list[str]:
    if _PIPER_MODEL.is_file():
        return ["Piper Ryan (offline)"]
    voices = []
    try:
        raw = _run(_LIST_SCRIPT)
        windows_voices = json.loads(raw.decode("utf-8-sig"))
        if isinstance(windows_voices, str):
            windows_voices = [windows_voices]
        for name in windows_voices:
            if not isinstance(name, str) or not name:
                continue
            probe = json.dumps({"text": "Ready.", "voice": name}).encode("utf-8")
            try:
                result = _run(_SPEAK_SCRIPT, probe)
                if result.startswith(b"RIFF") and result[8:12] == b"WAVE":
                    voices.append(name)
            except RuntimeError:
                continue
    except (RuntimeError, OSError, ValueError):
        pass
    return voices


def _piper_synthesize(text: str) -> bytes:
    global _PIPER_VOICE
    from piper import PiperVoice
    with _PIPER_LOCK:
        if _PIPER_VOICE is None:
            _PIPER_VOICE = PiperVoice.load(_PIPER_MODEL)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            _PIPER_VOICE.synthesize_wav(text, wav)
        return output.getvalue()


def synthesize(text: str, voice: str = "") -> bytes:
    text = text.strip()
    if not text or len(text) > 3000:
        raise ValueError("Speech text must be 1 to 3000 characters.")
    voices = installed_voices()
    if not voices:
        raise RuntimeError("No offline Windows voice is installed.")
    if voice and voice not in voices:
        raise ValueError("Selected voice is not installed.")
    selected = voice or voices[0]
    if selected == "Piper Ryan (offline)":
        wave_bytes = _piper_synthesize(text)
        if not wave_bytes.startswith(b"RIFF") or wave_bytes[8:12] != b"WAVE":
            raise RuntimeError("Offline speech returned invalid audio.")
        return wave_bytes
    payload = json.dumps({"text": text, "voice": selected}, ensure_ascii=False).encode("utf-8")
    wave_bytes = _run(_SPEAK_SCRIPT, payload=payload, timeout=90)
    if not wave_bytes.startswith(b"RIFF") or wave_bytes[8:12] != b"WAVE" or len(wave_bytes) > 40 * 1024 * 1024:
        raise RuntimeError("Offline speech returned invalid audio.")
    return wave_bytes
