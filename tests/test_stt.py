from __future__ import annotations

import numpy as np

from amy.host import stt


def _reference(audio, sample_rate=16000, target_rms=0.09):
    """The original per-sample implementation."""
    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    x = x - float(np.mean(x))
    rc = 1.0 / (2.0 * np.pi * 85.0)
    dt = 1.0 / float(sample_rate)
    alpha = rc / (rc + dt)
    y = np.empty_like(x)
    px = py = 0.0
    for i, v in enumerate(x):
        py = alpha * (py + float(v) - px)
        px = float(v)
        y[i] = py
    x = y
    hop = max(80, int(sample_rate * 0.02))
    if len(x) >= hop * 4:
        frames = len(x) // hop
        en = np.array([float(np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2)) + 1e-9)
                       for i in range(frames)], dtype=np.float32)
        gate = max(0.004, float(np.percentile(en, 20)) * 1.8)
        for i in range(frames):
            if en[i] < gate:
                x[i * hop:(i + 1) * hop] *= 0.12
    peak = float(np.max(np.abs(x)) or 0.0)
    rms = float(np.sqrt(np.mean(x**2)) + 1e-9)
    if peak > 0.01 and rms > 0.004:
        gain = min(6.0, max(0.7, target_rms / rms))
        if peak * gain > 0.95:
            gain = 0.95 / peak
        x = x * gain
    return np.clip(x, -1.0, 1.0).astype(np.float32)


def test_preprocess_matches_reference():
    rng = np.random.default_rng(7)
    t = np.arange(16000 * 3) / 16000.0
    speech = 0.2 * np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 0.7 * t) > 0)
    audio = (speech + 0.01 * rng.standard_normal(len(t)) + 0.05).astype(np.float32)
    got = stt.preprocess_pcm(audio)
    want = _reference(audio)
    assert got.dtype == np.float32 and got.shape == want.shape
    assert np.max(np.abs(got - want)) < 1e-4


def test_preprocess_short_input_passthrough():
    x = np.zeros(8, dtype=np.float32)
    assert stt.preprocess_pcm(x).shape == (8,)
