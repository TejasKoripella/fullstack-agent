"""One-shot, local speech transcription. No audio is retained by this module."""

from functools import lru_cache
from io import BytesIO

import av
from faster_whisper import WhisperModel


@lru_cache(maxsize=1)
def _model():
    return WhisperModel(
        "base.en",
        device="cpu",
        compute_type="int8",
        local_files_only=True,
    )


def transcribe_audio(audio: bytes) -> str:
    # Decode once with a hard duration cap before giving audio to the model.
    with av.open(BytesIO(audio), mode="r", metadata_errors="ignore") as container:
        seconds = 0.0
        for frame in container.decode(audio=0):
            seconds += frame.samples / frame.sample_rate
            if seconds > 30:
                raise ValueError("Audio is longer than 30 seconds.")
    segments, _ = _model().transcribe(BytesIO(audio), beam_size=3, vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()
