"""Mic + phrase-wake diagnostic."""
from __future__ import annotations

import os
import time

os.environ.setdefault("PYHIVE_HOME", r"G:\HiveSTEAM")
os.environ.setdefault("HIVE_CONFIG", r"G:\Amy\config\hive.yaml")

import numpy as np
import sounddevice as sd

from amy.host.live_stt import configured_stt_model
from amy.host.phrase_wake import PhraseWakeDaemon


def main() -> None:
    print("=== devices ===")
    print(sd.query_devices())
    print("default", sd.default.device)
    print("stt model", configured_stt_model())

    rate = 16000
    audio = sd.rec(rate, samplerate=rate, channels=1, dtype="float32")
    sd.wait()
    mono = audio.reshape(-1)
    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(mono**2)))
    print(f"mic 1s peak={peak:.4f} rms={rms:.4f}")

    hits = []

    def on_wake(ev):
        hits.append(ev)
        print("HIT", ev)

    d = PhraseWakeDaemon(
        phrases=["hey chloe", "hi chloe", "hello", "chloe"],
        on_wake=on_wake,
        on_event=print,
        cooldown_ms=400,
    )
    print("start", d.start())
    print("Speak for 10s — try 'hey chloe' clearly...")
    time.sleep(10)
    d.stop()
    print("hits", len(hits), hits)


if __name__ == "__main__":
    main()
