"""Original deterministic 20-second score; no samples or external assets.

Soft additive pad plus three transition accents. This is presentation audio,
not a scientific measurement. Generated WAV may be redistributed under MIT.
"""
import math
from pathlib import Path
import struct
import wave

SR = 48000
DURATION = 20
OUT = Path(__file__).parent / 'composition/assets/score.wav'
OUT.parent.mkdir(parents=True, exist_ok=True)
frames = bytearray()
# Three slowly changing consonant voicings, deliberately low in the mix.
chords = [(146.8324, 220.0, 293.6648), (130.8128, 196.0, 261.6256), (146.8324, 220.0, 329.6276)]
for i in range(SR * DURATION):
    t = i / SR
    amp = min(t / 1.2, 1, (DURATION - t) / 2.0)
    chord = chords[0 if t < 8 else 1 if t < 15 else 2]
    bed = sum(math.sin(2 * math.pi * f * t) + .15 * math.sin(2 * math.pi * 2*f*t) for f in chord) / 3
    pulse = .86 + .14 * math.sin(2 * math.pi * .12 * t)
    left = right = .07 * bed * pulse * max(0, amp)
    for at in (4, 10, 15):
        dt = t - at
        if 0 <= dt < 1.5:
            accent = .025 * math.sin(2 * math.pi * 880 * dt) * math.exp(-dt * 5) * min(1, dt / .015)
            left += accent
            right += accent * .85
    left += .004 * math.sin(2 * math.pi * 147.03 * t) * max(0, amp)
    right += .004 * math.sin(2 * math.pi * 146.64 * t) * max(0, amp)
    frames.extend(struct.pack('<hh', int(max(-1,min(1,left))*32767), int(max(-1,min(1,right))*32767)))
with wave.open(str(OUT), 'wb') as stream:
    stream.setnchannels(2)
    stream.setsampwidth(2)
    stream.setframerate(SR)
    stream.writeframes(frames)
print(OUT)
