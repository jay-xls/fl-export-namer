"""Synthetic beat in F minor at 140 BPM: detection must get both into its top 3."""
import numpy as np
import soundfile as sf

from bpm_detect import estimate_bpm
from key_detect import detect_key

SR = 44100


def _note(midi, dur, harmonics=6, amp=0.08):
    t = np.arange(int(SR * dur)) / SR
    f = 440 * 2 ** ((midi - 69) / 12)
    y = sum(np.sin(2 * np.pi * f * k * t) / k for k in range(1, harmonics + 1))
    return amp * y * np.minimum(1, t * 50) * np.exp(-t * 1.5)


def _beat(path, bpm=140, bars=12):
    bar = 4 * 60 / bpm
    y = np.zeros(int(SR * bar * bars) + SR)
    rng = np.random.default_rng(0)
    prog = [(41, [65, 68, 72]), (37, [61, 65, 68]), (39, [63, 67, 70]), (36, [60, 63, 67])]  # Fm Db Eb Cm
    for b in range(bars):
        root, chord = prog[b % 4]
        s = int(b * bar * SR)
        seg = sum(_note(m, bar) for m in chord) + _note(root, bar, harmonics=2, amp=0.5)
        y[s:s + len(seg)] += seg
        for i in range(16):
            h = int(s + i * bar / 16 * SR)
            y[h:h + 2000] += rng.normal(0, 0.05, 2000) * np.exp(-np.arange(2000) / 300)
        for i in (0, 10):
            k = int(s + i * bar / 16 * SR)
            t = np.arange(6000) / SR
            y[k:k + 6000] += 0.6 * np.sin(2 * np.pi * (50 + 200 * np.exp(-t * 40)) * t) * np.exp(-t * 20)
        sn = int(s + 8 * bar / 16 * SR)
        y[sn:sn + 8000] += rng.normal(0, 0.2, 8000) * np.exp(-np.arange(8000) / 1500)
    sf.write(path, (y / np.abs(y).max() * 0.9).astype("float32"), SR)


def test_bpm_and_key_on_synthetic_beat(tmp_path):
    p = tmp_path / "beat.wav"
    _beat(p)
    bpms = [b for b, _ in estimate_bpm(str(p))]
    assert any(abs(b - 140) <= 1 for b in bpms), bpms
    keys = [k for k, _ in detect_key(str(p), bpm=140)]
    assert "Fm" in keys, keys
