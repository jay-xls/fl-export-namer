"""Tempo estimation from audio (numpy + soundfile only).

Onset envelope (spectral flux) -> autocorrelation -> comb scoring across a
fine BPM grid -> half/double/triplet alternatives ranked with a gentle
prior towards the tempos producers actually set in a DAW.

The classic failure is octave ambiguity: a half-time trap beat set at 140
can read as 70. That's why the popup always shows the alternatives.
"""

from __future__ import annotations

import numpy as np

FPS = 100.0          # onset envelope frames per second
BPM_MIN, BPM_MAX = 55.0, 210.0
MAX_SECONDS = 150


def _load(path: str):
    import soundfile as sf
    with sf.SoundFile(path) as f:
        sr = f.samplerate
        total = f.frames if f.frames > 0 else 0
        start = int(min(total * 0.1, 20 * sr)) if total > 30 * sr else 0  # skip intros on long files
        f.seek(start)
        x = f.read(int(MAX_SECONDS * sr), dtype="float32", always_2d=True)
    return x.mean(axis=1), sr


def onset_envelope(x: np.ndarray, sr: int) -> np.ndarray:
    hop = int(round(sr / FPS))
    n_fft = 2048 if sr <= 48000 else 4096
    if len(x) < n_fft * 4:
        return np.zeros(0)
    n_frames = 1 + (len(x) - n_fft) // hop
    win = np.hanning(n_fft).astype(np.float32)
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    band = freqs <= 11000
    low = freqs[band] <= 200  # kick / 808 region, weighted up a little
    env = np.zeros(n_frames)
    prev = None
    step = 2048  # frames per batch keeps memory flat on long files
    for b0 in range(0, n_frames, step):
        idx = np.arange(b0, min(n_frames, b0 + step))
        frames = np.lib.stride_tricks.as_strided(
            x[idx[0] * hop:], shape=(len(idx), n_fft), strides=(x.strides[0] * hop, x.strides[0]))
        mag = np.abs(np.fft.rfft(frames * win, axis=1))[:, band]
        logm = np.log1p(100 * mag)
        if prev is None:
            prev = logm[:1]
        d = np.diff(np.vstack([prev, logm]), axis=0)
        prev = logm[-1:]
        d = np.maximum(d, 0)
        env[idx] = d.sum(axis=1) + 1.5 * d[:, low].sum(axis=1)
    # remove slow trend, keep the transients
    k = int(FPS)
    trend = np.convolve(env, np.ones(k) / k, mode="same")
    env = np.maximum(env - trend, 0)
    s = env.std()
    return env / s if s > 0 else env


def _autocorr(env: np.ndarray) -> np.ndarray:
    n = len(env)
    e = env - env.mean()
    f = np.fft.rfft(e, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    return ac / ac[0] if ac[0] > 0 else ac


def _interp(ac, lag):
    i = int(lag)
    if i + 1 >= len(ac):
        return 0.0
    fr = lag - i
    return (1 - fr) * ac[i] + fr * ac[i + 1]


def _comb(ac, bpm):
    lag = 60.0 * FPS / bpm
    # beat, 2 beats, bar, 2 bars - plus the half-beat (8ths) lightly
    return (_interp(ac, lag) + 0.5 * _interp(ac, 2 * lag) + 0.5 * _interp(ac, 4 * lag)
            + 0.25 * _interp(ac, 8 * lag) + 0.25 * _interp(ac, lag / 2))


def _prior(bpm):
    # Gentle preference for typical DAW-set tempos (centred ~120, very wide).
    return float(np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.9) ** 2))


def _tidy(bpm):
    r = round(bpm)
    return float(r) if abs(bpm - r) <= 0.35 else round(bpm * 2) / 2


def estimate_bpm(path: str, top: int = 3):
    """Return [(bpm, confidence_0_to_1), ...] best first, or [] if no clear pulse."""
    x, sr = _load(path)
    env = onset_envelope(x, sr)
    if len(env) < FPS * 6 or env.max() == 0:
        return []
    ac = _autocorr(env)
    grid = np.arange(BPM_MIN, BPM_MAX + 0.01, 0.1)
    scores = np.array([_comb(ac, b) for b in grid])
    if scores.max() <= 0:
        return []

    # local maxima of the comb score
    peaks = [i for i in range(1, len(grid) - 1) if scores[i] >= scores[i - 1] and scores[i] >= scores[i + 1]]
    peaks.sort(key=lambda i: scores[i], reverse=True)
    best = grid[peaks[0]]

    # Candidate set: the strongest peaks plus octave/triplet relatives of the best one.
    cands = {round(grid[i], 1) for i in peaks[:6]}
    for m in (0.5, 2.0, 2 / 3, 1.5):
        if BPM_MIN <= best * m <= BPM_MAX:
            cands.add(round(best * m, 1))

    ranked = []
    for c in cands:
        # refine to the local max within +-1.5 BPM
        loc = np.abs(grid - c) <= 1.5
        sub = grid[loc][np.argmax(scores[loc])]
        val = scores[loc].max() * _prior(sub)
        ranked.append((val, _tidy(sub)))
    merged: dict = {}
    for val, b in ranked:
        merged[b] = max(val, merged.get(b, -1e9))
    out = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
    # Always offer the half/double of the winner - octave errors are the mistake that matters.
    b0 = out[0][0]
    octave = [kv for kv in out[1:] if any(abs(kv[0] - b0 * m) <= 1.5 for m in (0.5, 2.0))]
    if octave and octave[0] not in out[:top]:
        out = out[:top - 1] + [octave[0]] + [kv for kv in out[top - 1:] if kv != octave[0]]
    vals = np.array([v for _, v in out])
    conf = np.exp((vals - vals.max()) * 6)
    conf /= conf.sum()
    return [(b, float(c)) for (b, _), c in zip(out[:top], conf[:top])]


if __name__ == "__main__":
    import sys
    import time
    for p in sys.argv[1:]:
        t = time.time()
        print(p, [(b, round(c, 2)) for b, c in estimate_bpm(p)], f"{time.time() - t:.2f}s")
