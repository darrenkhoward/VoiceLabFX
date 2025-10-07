#!/usr/bin/env bash
set -euo pipefail
python - <<'PY'
import numpy as np
from app import SR
from scipy.signal import stft, istft, get_window

def wpe_dereverb(y, iters=1, taps=12, delay=3):
    try:
        from nara_wpe import wpe
    except (ImportError, ModuleNotFoundError, AttributeError):
        return y.astype(np.float32), "WPE unavailable"
    nperseg = 512
    hop = 128
    noverlap = nperseg - hop
    win = get_window("hann", nperseg)
    _, _, Y = stft(y, fs=SR, window=win, nperseg=nperseg, noverlap=noverlap, boundary=None)
    Yc = Y[:, None, :]
    try:
        Xc = wpe.wpe(Yc, taps=int(taps), delay=int(delay), iterations=int(iters))
    except Exception:
        return y.astype(np.float32), "WPE unavailable"
    X = Xc[:, 0, :]
    _, x = istft(X, fs=SR, window=win, nperseg=nperseg, noverlap=noverlap, input_onesided=True, boundary=None)
    return x.astype(np.float32), "WPE applied"
print('WPE status diff')
x = np.random.randn(48000).astype(np.float32)
y, msg = wpe_dereverb(x)
print(msg, np.linalg.norm(y-x))
PY
