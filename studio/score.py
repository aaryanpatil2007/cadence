"""Synthesize a calm, consistent score for the Cadence film (numpy -> wav).
A warm pad drone with slow swells + sparse pentatonic bells. No key change,
gentle resolve at the end. Usage: python score.py <seconds> <out.wav>
"""
import sys
import numpy as np
from scipy.io import wavfile

SR = 48000


def adsr(n, a, d, s, r, sus):
    env = np.zeros(n)
    ai, di, ri = int(a * SR), int(d * SR), int(r * SR)
    ai = min(ai, n); di = min(di, n - ai)
    env[:ai] = np.linspace(0, 1, ai)
    env[ai:ai + di] = np.linspace(1, sus, di)
    body = n - ai - di - ri
    if body > 0:
        env[ai + di:ai + di + body] = sus
    if ri > 0:
        env[-ri:] = np.linspace(sus, 0, ri)
    return env


def bell(freq, dur, amp=0.2):
    n = int(dur * SR)
    t = np.arange(n) / SR
    tone = (np.sin(2 * np.pi * freq * t)
            + 0.5 * np.sin(2 * np.pi * freq * 2 * t)
            + 0.25 * np.sin(2 * np.pi * freq * 3 * t))
    env = np.exp(-t * 3.2)
    return amp * tone * env


def pad(freqs, dur, amp=0.09):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for f in freqs:
        lfo = 1 + 0.004 * np.sin(2 * np.pi * 0.08 * t)
        out += np.sin(2 * np.pi * f * t * lfo)
        out += 0.5 * np.sin(2 * np.pi * (f * 1.003) * t)  # detune shimmer
    swell = 0.5 + 0.5 * np.sin(2 * np.pi * t / max(dur, 1) - np.pi / 2)
    return amp * out / len(freqs) * (0.6 + 0.4 * swell)


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 110.0
    out = sys.argv[2] if len(sys.argv) > 2 else "out/score.wav"
    n = int(dur * SR)
    mix = np.zeros(n)

    # warm pad in A minor-ish (A2 E3 A3 C4) — stays constant, resolves softly
    chord = [110.0, 164.81, 220.0, 261.63]
    mix += pad(chord, dur, amp=0.10)

    # sparse pentatonic bells (A C D E G) across the timeline
    penta = [440.0, 523.25, 587.33, 659.25, 783.99]
    rng = np.random.default_rng(3)
    t = 2.0
    while t < dur - 3:
        f = penta[rng.integers(0, len(penta))]
        b = bell(f, 3.0, amp=0.16)
        s = int(t * SR)
        e = min(s + len(b), n)
        mix[s:e] += b[:e - s]
        t += rng.uniform(2.6, 4.4)

    # gentle final resolve: a low root bell
    b = bell(220.0, 4.0, amp=0.2)
    s = max(0, n - len(b))
    mix[s:s + len(b)] += b[:n - s]

    # soft master: gentle limiter + normalize toward -14 LUFS-ish (approx via RMS)
    mix = np.tanh(mix * 1.1)
    rms = np.sqrt(np.mean(mix ** 2)) + 1e-9
    target = 0.12
    mix *= target / rms
    mix = np.clip(mix, -0.98, 0.98)
    # 40ms fade in/out
    f = int(0.04 * SR)
    mix[:f] *= np.linspace(0, 1, f)
    mix[-f:] *= np.linspace(1, 0, f)

    import os
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    wavfile.write(out, SR, (mix * 32767).astype(np.int16))
    print(f"score: {dur:.1f}s -> {out}")


if __name__ == "__main__":
    main()
