import sounddevice as sd
from scipy.io.wavfile import write

RATE = 16000
SECONDS = 5

print("Microphone is OFF.")
input("Press Enter to record for 5 seconds...")

print("Recording...")
audio = sd.rec(
    int(SECONDS * RATE),
    samplerate=RATE,
    channels=1,
    dtype="int16"
)
sd.wait()

write("mic_test.wav", RATE, audio)

print("Recording stopped.")
print("Saved mic_test.wav")
print("Microphone is OFF.")
