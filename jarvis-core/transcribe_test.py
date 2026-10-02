from faster_whisper import WhisperModel

print("Loading speech model...")

model = WhisperModel(
    "base.en",
    device="cpu",
    compute_type="int8"
)

segments, info = model.transcribe("mic_test.wav")

text = " ".join(segment.text.strip() for segment in segments)

print("Heard:")
print(text)
print("JARVIS HEARING ONLINE")
