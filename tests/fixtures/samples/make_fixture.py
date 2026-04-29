"""Generate a synthetic 1-second silence wav with a tiny bit of noise."""
import numpy as np
import soundfile as sf
from pathlib import Path

np.random.seed(42)
sr = 16000
audio = (np.random.randn(sr * 2) * 0.01).astype(np.float32)
out = Path(__file__).parent / "hello.wav"
sf.write(out, audio, sr, subtype="FLOAT")
print(f"wrote {out}")
