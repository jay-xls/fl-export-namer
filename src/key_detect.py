"""Key detection from a rendered audio file (numpy + soundfile only).

Method: long-window STFT -> peak-emphasised spectrum (suppresses drum noise)
-> 12-bin chroma -> correlation against Krumhansl-Kessler and
Temperley major/minor key profiles. A bass-chroma bonus favours the key
whose tonic the low end (808 / bass) sits on most, which is the main
signal for telling a minor key from its relative major (Fm vs Ab).

It's a best guess, not gospel - the popup always lets you overrule it.
"""

from __future__ import annotations

import numpy as np

PITCHES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PITCHES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
PITCHES_MIXED = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
TP_MAJOR = np.array([.748, .060, .488, .082, .670, .460, .096, .715, .104, .366, .057, .400])
TP_MINOR = np.array([.712, .084, .474, .618, .049, .460, .105, .747, .404, .067, .133, .330])

MAX_SECONDS = 240  # analyse at most the first 4 minutes


def key_name(pc: int, minor: bool, style: str = "short", accidentals: str = "mixed") -> str:
    names = {"sharps": PITCHES_SHARP, "flats": PITCHES_FLAT}.get(accidentals, PITCHES_MIXED)
    root = names[pc % 12]
    if style == "minmaj":
        return root + ("min" if minor else "maj")
    if style == "long":
        return root + (" minor" if minor else " major")
    return root + ("m" if minor else "")


def _load_mono(path: str):
    """Returns (mono_signal, sample_rate, offset_seconds)."""
    import soundfile as sf
    with sf.SoundFile(path) as f:
        sr = f.samplerate
        total = f.frames if f.frames > 0 else 0
        frames = min(total, int(MAX_SECONDS * sr)) if total else int(MAX_SECONDS * sr)
        x = f.read(frames, dtype="float32", always_2d=True)
    return x.mean(axis=1), sr


_MIDS = np.arange(24, 108)  # C1..B7, one bin per semitone
_HARM = [(int(round(12 * np.log2(h))), 0.7 ** (h - 1)) for h in range(1, 7)]
_KERNEL = np.ones(25) / 25


class _Bands:
    """Maps FFT bins of a given size onto semitone bands."""
    _cache: dict = {}

    @classmethod
    def get(cls, n_fft: int, sr: int):
        key = (n_fft, sr)
        if key not in cls._cache:
            freqs = np.fft.rfftfreq(n_fft, 1 / sr)
            lo = 440 * 2 ** ((_MIDS - 0.5 - 69) / 12)
            hi = 440 * 2 ** ((_MIDS + 0.5 - 69) / 12)
            cls._cache[key] = [np.where((freqs >= a) & (freqs < b))[0] for a, b in zip(lo, hi)]
        return cls._cache[key]


def _salience(frame: np.ndarray, sr: int) -> np.ndarray | None:
    """Per-semitone pitch salience for one windowed frame, with overtones folded
    back onto their fundamentals (stops the 3rd harmonic dragging keys up a 5th)."""
    mag = np.abs(np.fft.rfft(frame))
    if mag.max() < 1e-4:
        return None
    lm = np.log1p(1000 * mag / mag.max())
    peaks = np.clip(lm - np.convolve(lm, _KERNEL, mode="same"), 0, None)  # tonal peaks, not drum noise
    spec = np.array([peaks[i].max() if len(i) else 0.0 for i in _Bands.get(len(frame), sr)])
    n = len(spec)
    sal = np.zeros(n)
    for o, w in _HARM:
        sal[: n - o] += w * spec[o:]
    out = sal.copy()
    for o, w in _HARM[1:]:
        out[o:] -= 0.5 * w * sal[: n - o]
    return np.clip(out, 0, None)


def _fold(sal: np.ndarray, lo: int, hi: int) -> np.ndarray:
    m = (_MIDS >= lo) & (_MIDS <= hi)
    v = np.bincount(_MIDS[m] % 12, weights=sal[m], minlength=12)
    s = v.sum()
    return v / s if s > 0 else v


def _analyse(x: np.ndarray, sr: int, bpm: float | None):
    n_fft = 1 << int(np.ceil(np.log2(sr * 0.74)))
    hop = n_fft // 2
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    win = np.hanning(n_fft)
    chroma, bass = np.zeros(12), np.zeros(12)
    for start in range(0, len(x) - n_fft + 1, hop):
        sal = _salience(x[start:start + n_fft] * win, sr)
        if sal is None:
            continue
        chroma += _fold(sal, 40, 107)
        bass += _fold(sal, 28, 52)

    # Bass note at the downbeat of each 4-bar phrase (renders start at bar 1).
    phrase = np.zeros(12)
    if bpm:
        bar = 4 * 60.0 / bpm
        n_short = 1 << int(np.floor(np.log2(sr * min(0.45, 60.0 / bpm))))
        w2 = np.hanning(n_short)
        t = 0.0
        while t * sr + n_short < len(x):
            s = int((t + min(0.1, 15.0 / bpm)) * sr)  # skip the kick transient
            sal = _salience(x[s:s + n_short] * w2, sr)
            if sal is not None:
                phrase += _fold(sal, 28, 52)
            t += 4 * bar
    return chroma, bass, phrase


def _corr(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d else 0.0


def detect_key(path: str, style: str = "short", accidentals: str = "mixed",
               top: int = 3, bpm: float | None = None):
    """Return [(key_name, confidence_0_to_1), ...] best first, or [] if undetectable."""
    x, sr = _load_mono(path)
    if len(x) < sr:
        return []
    chroma, bass, phrase = _analyse(x, sr, bpm)
    if chroma.sum() == 0:
        return []
    norm = lambda v: v / v.sum() if v.sum() else v
    bass, phrase = norm(bass), norm(phrase)

    scores = []
    for tonic in range(12):
        for minor in (False, True):
            p1 = np.roll(KK_MINOR if minor else KK_MAJOR, tonic)
            p2 = np.roll(TP_MINOR if minor else TP_MAJOR, tonic)
            s = 0.5 * (_corr(chroma, p1) + _corr(chroma, p2))
            s += 0.4 * bass[tonic] + 1.0 * phrase[tonic]
            scores.append((s, tonic, minor))
    scores.sort(reverse=True)
    vals = np.array([s for s, _, _ in scores])
    conf = np.exp((vals - vals.max()) * 8)
    conf = conf / conf.sum()
    return [(key_name(t, m, style, accidentals), float(c))
            for (s, t, m), c in zip(scores[:top], conf[:top])]


if __name__ == "__main__":
    import sys
    for p in [a for a in sys.argv[1:] if not a.replace('.','').isdigit()]:
        print(p, detect_key(p, bpm=float(sys.argv[-1]) if sys.argv[-1].replace('.','').isdigit() else None))
