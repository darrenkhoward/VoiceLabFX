# VoiceLab FX — Editor (Full, Purple UI)
# Updates: micro Robotization (max 0.01, subtle), Stronger Dereverb (2-stage spectral gate)
# Chain: Mic → (Dereverb/EQ/Leveler) → Room IR → Events → Background (+BG-IR, HPF/LPF, duck)
#        → Bandwidth → Opus → Network Artifacts (OLD garble/stutter/dropouts) → Handset IR → Normalize

from __future__ import annotations
import os, sys, json, glob, time, atexit, tempfile, hashlib, subprocess, shutil, random
from typing import List, Tuple, Optional, Any, Dict

import numpy as np
import soundfile as sf
import gradio as gr

from scipy.signal import resample_poly, butter, sosfilt, sosfiltfilt, fftconvolve, stft, istft, get_window

SR = 48000
TMP_DIR = os.environ.get("VLAB_TMPDIR", tempfile.gettempdir())
PRESETS_PATH = "presets.json"

# ───────────────── preset helpers ─────────────────
PROCESS_AUDIO_PARAM_ORDER = [
    "dereverb_amt", "src_hpf", "src_lpf", "leveler_amt",
    "wpe_strength",
    "cleanup_mix",
    "room_ir_file", "room_ir_gain_db",
    "bg_file", "bg_ir_file", "bg_ir_gain_db", "bg_gain_db", "bg_hpf", "bg_lpf", "bg_duck_db",
    "quality_tier", "custom_low_freq", "custom_high_freq", "custom_compression", "custom_noise", "custom_dropout_mult", "custom_garble_mult",
    "bandwidth_mode", "opus_bitrate_kbps", "post_mu_grit",
    "plc_ms", "dropout_prob", "dropout_depth_db",
    "garble_prob", "stutter_amt", "jitter_intensity", "buffer_prob", "reorder_prob",
    "codec_type", "codec_intensity", "mic_proximity", "mic_type", "mp3_amt", "rf_amt",
    "handset_ir_file", "handset_ir_gain_db",
    "traffic_files", "traffic_ev_min", "traffic_vol_db",
    "baby_files", "baby_ev_min", "baby_vol_db",
    "dog_files", "dog_ev_min", "dog_vol_db",
    "normalize_output"
]

BOJAN_PRESET_DEFAULTS: Dict[str, Any] = {
    "dereverb_amt": 0.0,
    "src_hpf": 0.0,
    "src_lpf": 20000.0,
    "leveler_amt": 0.0,
    "wpe_strength": 0.0,
    "cleanup_mix": 1.0,
    "room_ir_file": None,
    "room_ir_gain_db": 0.0,
    "bg_file": None,
    "bg_ir_file": None,
    "bg_ir_gain_db": 0.0,
    "bg_gain_db": -60.0,
    "bg_hpf": 0.0,
    "bg_lpf": SR / 2,
    "bg_duck_db": -12.0,
    "quality_tier": "standard",
    "custom_low_freq": 300.0,
    "custom_high_freq": 3400.0,
    "custom_compression": 0.0,
    "custom_noise": 0.0,
    "custom_dropout_mult": 1.0,
    "custom_garble_mult": 1.0,
    "bandwidth_mode": "Narrowband 300–3500",
    "opus_bitrate_kbps": 24.0,
    "post_mu_grit": 0.0,
    "plc_ms": 60.0,
    "dropout_prob": 0.0,
    "dropout_depth_db": -24.0,
    "garble_prob": 0.0,
    "stutter_amt": 0.0,
    "jitter_intensity": 0.0,
    "buffer_prob": 0.0,
    "reorder_prob": 0.0,
    "codec_type": "amr_nb",
    "codec_intensity": 0.0,
    "mic_proximity": 0.5,
    "mic_type": "handset",
    "mp3_amt": 0.0,
    "rf_amt": 0.0,
    "handset_ir_file": None,
    "handset_ir_gain_db": 0.0,
    "traffic_files": None,
    "traffic_ev_min": 0.0,
    "traffic_vol_db": -12.0,
    "baby_files": None,
    "baby_ev_min": 0.0,
    "baby_vol_db": -12.0,
    "dog_files": None,
    "dog_ev_min": 0.0,
    "dog_vol_db": -12.0,
    "normalize_output": True,
}

BOJAN_PRESET_CONFIGS: Dict[str, Dict[str, Any]] = {
    "🚦 Street Caller": {
        "dereverb_amt": 0.25,
        "src_hpf": 80.0,
        "src_lpf": 17000.0,
        "leveler_amt": 0.45,
        "quality_tier": "low",
        "bandwidth_mode": "Narrowband 300–3500",
        "bg_file": [
            "assets/backgrounds/street_A.wav",
            "assets/backgrounds/street_B_48k.ogg",
            "assets/backgrounds/Street Noise -15db 15 min 1_48k.ogg",
            "assets/backgrounds/Street Noise -15db 15 min 2_48k.ogg",
            "assets/backgrounds/Street Noise -15db 15 min 4_48k.ogg"
        ],
        "bg_gain_db": -19.0,
        "bg_hpf": 120.0,
        "bg_lpf": 1400.0,
        "bg_duck_db": -14.0,
        "dropout_prob": 0.14,
        "plc_ms": 50.0,
        "dropout_depth_db": -28.0,
        "garble_prob": 0.06,
        "stutter_amt": 0.015,
        "jitter_intensity": 0.05,
        "reorder_prob": 0.02,
        "rf_amt": 0.2,
        "handset_ir_file": "assets/irs/cellphone_dry_trimmed.wav",
        "handset_ir_gain_db": -6.0,
        "traffic_files": [
            "assets/car horns/488065__bendrain__ambience_city_horn_01.mp3",
            "assets/car horns/616589__trp__120616-traffic-horns-engines-reverse-beeps-truck-nyc.mp3",
        ],
        "traffic_ev_min": 10.0,
        "traffic_vol_db": -4.0,
        "normalize_output": True,
    },
    "📶 Spotty Service": {
        "dereverb_amt": 0.3,
        "src_hpf": 100.0,
        "src_lpf": 16000.0,
        "leveler_amt": 0.55,
        "wpe_strength": 0.1,
        "quality_tier": "ultra_low",
        "bandwidth_mode": "Narrowband 300–3500",
        "bg_file": [
            "assets/backgrounds/street_D.wav",
            "assets/backgrounds/Street Noise -15db 15 min 2_48k.ogg",
            "assets/backgrounds/Street Noise -15db 15 min 4_48k.ogg"
        ],
        "bg_gain_db": -32.0,
        "bg_hpf": 180.0,
        "bg_lpf": 2200.0,
        "bg_duck_db": -16.0,
        "dropout_prob": 0.32,
        "plc_ms": 32.0,
        "dropout_depth_db": -38.0,
        "garble_prob": 0.32,
        "stutter_amt": 0.045,
        "jitter_intensity": 0.18,
        "reorder_prob": 0.08,
        "rf_amt": 0.35,
        "handset_ir_file": "assets/irs/cellphone_dry_trimmed.wav",
        "handset_ir_gain_db": -9.0,
        "traffic_files": [
            "assets/car horns/569613__wanaki__car-horn-irritated-driver-stuck-in-traffic.mp3"
        ],
        "traffic_ev_min": 6.0,
        "traffic_vol_db": -8.0,
        "normalize_output": True,
    },
    "🛁 Bathroom Caller": {
        "quality_tier": "high",
        "bandwidth_mode": "Wideband 80–7000",
        "room_ir_file": "assets/irs/bathroom.ogg",
        "room_ir_gain_db": 60.0,
        "src_hpf": 60.0,
        "src_lpf": 20000.0,
        "leveler_amt": 0.35,
        "cleanup_mix": 0.5,
        "bg_file": [
            "assets/Party Music/techno 1_48k.ogg",
            "assets/Party Music/techno 2_48k.ogg"
        ],
        "bg_gain_db": -28.0,
        "bg_hpf": 0.0,
        "bg_lpf": 1200.0,
        "bg_duck_db": -18.0,
        "dropout_prob": 0.01,
        "dropout_depth_db": -40.0,
        "garble_prob": 0.01,
        "stutter_amt": 0.003,
        "jitter_intensity": 0.008,
        "reorder_prob": 0.004,
        "rf_amt": 0.01,
        "handset_ir_file": "assets/irs/cellphone_dry_trimmed.wav",
        "handset_ir_gain_db": -5.0,
        "traffic_files": [
            "assets/car horns/733168__locky_y__honking.mp3"
        ],
        "traffic_ev_min": 2.0,
        "traffic_vol_db": -18.0,
        "normalize_output": False,
    },
    "🎉 Bathroom Party": {
        "quality_tier": "high",
        "bandwidth_mode": "Wideband 80–7000",
        "room_ir_file": "assets/irs/bathroom.ogg",
        "room_ir_gain_db": 70.0,
        "src_hpf": 50.0,
        "src_lpf": 20000.0,
        "leveler_amt": 0.35,
        "cleanup_mix": 0.5,
        "bg_file": [
            "assets/Party Music/techno 1_48k.ogg",
            "assets/Party Music/techno 2_48k.ogg"
        ],
        "bg_gain_db": -24.0,
        "bg_hpf": 60.0,
        "bg_lpf": 850.0,
        "bg_duck_db": -20.0,
        "dropout_prob": 0.05,
        "dropout_depth_db": -24.0,
        "garble_prob": 0.05,
        "stutter_amt": 0.012,
        "jitter_intensity": 0.03,
        "reorder_prob": 0.015,
        "rf_amt": 0.05,
        "handset_ir_file": "assets/irs/cellphone_dry_trimmed.wav",
        "handset_ir_gain_db": -5.0,
        "traffic_files": [
            "assets/car horns/425848__soundholder__renault-master-f3500-dci135-foley-horn-outside-mono.mp3"
        ],
        "traffic_ev_min": 3.0,
        "traffic_vol_db": -20.0,
        "normalize_output": True,
    },
}

# ───────────────── utils ─────────────────
def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None

def _file_sig(path: str) -> str:
    try:
        st = os.stat(path); return f"{path}:{st.st_size}:{int(st.st_mtime)}"
    except Exception: return f"{path}:unknown"

def _safe_file(obj) -> Optional[str]:
    if isinstance(obj, str): return obj if obj and os.path.exists(obj) else None
    if isinstance(obj, dict):
        p = obj.get("name"); return p if p and os.path.exists(p) else None
    return None

def _coerce_paths_list(files) -> List[str]:
    out=[]
    if isinstance(files, list):
        for it in files:
            p=_safe_file(it) if not isinstance(it,str) else (it if os.path.exists(it) else None)
            if p: out.append(p)
    elif isinstance(files,str) and os.path.exists(files):
        out.append(files)
    return out

def _load_audio(path: str) -> Tuple[np.ndarray, int]:
    """Load audio file, using _decode_any_to_float32 for OGG/MP3 files"""
    if path and path.lower().endswith(('.ogg', '.mp3')):
        y = _decode_any_to_float32(path, SR)
        return y, SR
    try:
        y, sr = sf.read(path, dtype="float32", always_2d=False)
        return y, sr
    except Exception:
        # Fallback to decode function for any format
        y = _decode_any_to_float32(path, SR)
        return y, SR

def _mono_sr(y: np.ndarray, sr: int, target: int = SR) -> np.ndarray:
    if y.ndim>1: y=y.mean(axis=1)
    if sr!=target:
        g=np.gcd(int(sr), int(target)); up,down = target//g, sr//g
        y=resample_poly(y, up, down).astype(np.float32)
    return y.astype(np.float32)

def _save_wav_tmp(y: np.ndarray, sr: int = SR) -> str:
    f = tempfile.NamedTemporaryFile(prefix="vlab_", delete=False, suffix=".wav", dir=TMP_DIR)
    sf.write(f.name, y.astype(np.float32), sr); return f.name

def normalize_peak(x: np.ndarray, peak: float = 0.97) -> np.ndarray:
    m=float(np.max(np.abs(x)) or 0.0);
    return x if m<1e-9 else (x/m*peak).astype(np.float32)


def _normalize_path_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        parts=[line.strip() for line in value.replace(';', '\n').splitlines() if line.strip()]
        return parts
    return _coerce_paths_list(value)


def _resolve_file(uploaded, fallback):
    upload_path = _safe_file(uploaded)
    if upload_path:
        return upload_path
    if isinstance(fallback, (list, tuple)):
        for item in fallback:
            path = _safe_file(item)
            if path:
                return path
        return None
    return fallback if fallback else None


def _resolve_files(uploaded, fallback):
    paths = _normalize_path_list(uploaded)
    if paths:
        return paths
    paths = _normalize_path_list(fallback)
    return paths if paths else None


# Robust same-file checker to guard duplicate IR application
def _same_file(a: str | None, b: str | None) -> bool:
    import os, hashlib
    try:
        if not a or not b:
            return False
        if os.path.exists(a) and os.path.exists(b):
            try:
                if os.path.samefile(a, b):
                    return True
            except Exception:
                pass
            def _canon(p):
                return os.path.normcase(os.path.normpath(os.path.realpath(p)))
            if _canon(a) == _canon(b):
                return True
            try:
                sa, sb = os.path.getsize(a), os.path.getsize(b)
                if sa == sb and sa <= 10*1024*1024:
                    h = hashlib.sha1
                    def _h(p):
                        with open(p, 'rb') as f:
                            return h(f.read()).hexdigest()
                    if _h(a) == _h(b):
                        return True
            except Exception:
                pass
    except Exception:
        pass
    return False

# Decode any audio (ogg/wav/mp3/...) to float32 mono via ffmpeg; fallback to soundfile
def _decode_any_to_float32(path: str, sr: int = SR) -> np.ndarray:
    import os as _os, tempfile as _tmp
    if not path or not _os.path.exists(path):
        return np.zeros(0, dtype=np.float32)
    try:
        lower = path.lower()
        if lower.endswith('.ogg') and have_ffmpeg():
            # Convert to a temp WAV (more stable than pipe for ogg), then decode
            tmp_wav = _tmp.NamedTemporaryFile(prefix='vlab_bg_', suffix='.wav', delete=False).name
            rc = _os.system(f'ffmpeg -hide_banner -loglevel error -y -i "{path}" -ac 1 -ar {sr} "{tmp_wav}"')
            if rc == 0 and _os.path.exists(tmp_wav):
                try:
                    data, fs = sf.read(tmp_wav, dtype="float32", always_2d=False)
                    if isinstance(data, np.ndarray):
                        if data.ndim == 2:
                            data = data.mean(axis=1)
                        if fs != sr:
                            from scipy.signal import resample_poly
                            gcd_val = np.gcd(sr, fs)
                            data = resample_poly(data, sr // gcd_val, fs // gcd_val).astype(np.float32)
                        return data.astype(np.float32, copy=False)
                finally:
                    try: _os.remove(tmp_wav)
                    except Exception: pass
        # Generic ffmpeg pipe for other formats
        if have_ffmpeg():
            cmd = f'ffmpeg -hide_banner -loglevel error -i "{path}" -f f32le -ac 1 -ar {sr} -'
            with _os.popen(cmd, "rb") as f:
                raw = f.read()
            x = np.frombuffer(raw, dtype=np.float32)
            if x.size > 0:
                return x.astype(np.float32, copy=False)
    except Exception:
        pass
    # Fallback: libsoundfile direct
    try:
        data, fs = sf.read(path, dtype="float32", always_2d=False)
        if isinstance(data, np.ndarray):
            if data.ndim == 2:
                data = data.mean(axis=1)
            if fs != sr:
                from scipy.signal import resample_poly
                gcd_val = np.gcd(sr, fs)
                data = resample_poly(data, sr // gcd_val, fs // gcd_val).astype(np.float32)
            return data.astype(np.float32, copy=False)
    except Exception:
        return np.zeros(0, dtype=np.float32)
    return np.zeros(0, dtype=np.float32)


BACKGROUND_POOL = [
    "assets/backgrounds/Street Noise -15db 15 min 1_48k.ogg",
    "assets/backgrounds/Street Noise -15db 15 min 2_48k.ogg",
    "assets/backgrounds/Street Noise -15db 15 min 4_48k.ogg",
    "assets/backgrounds/Street Noise -15db 15 min 5_48k.ogg",
    "assets/backgrounds/street_B_48k.ogg"
]

HORN_POOL = [
    "assets/car_horns/488065__bendrain__ambience_city_horn_01_48k.ogg",
    "assets/car_horns/569613__wanaki__car-horn_irritated-driver-stuck-in-traffic_48k.ogg",
    "assets/car_horns/393668__chripei__fire-truck-short-good-w-horn_48k.ogg",
    "assets/car_horns/425848__soundholder__renault-master-f3500-dci135-foley-horn-outside-mono_48k.ogg",
    "assets/car_horns/451671__kyles__school-bus-truck-horn-honk-100m-away_48k.ogg",
    "assets/car_horns/733168__locky_y__honking_48k.ogg",
    "assets/car_horns/188004__motion_s__police-car-siren_48k.ogg",
    "assets/car_horns/254678__hsaunier10__car-horn-beeps_48k.ogg"
]

DOG_POOL = [
    "assets/dog_barks/521829__joelcarrsound__pug-dog-whining-and-barking_48k.ogg",
    "assets/dog_barks/713586__iliasflou__dog-crying_48k.ogg"
]

BABY_POOL = [
    "assets/baby_cries/211526__the_yura__crying-newborn-baby-child-4_48k.ogg"
]

CAR_POOL = [
    "assets/car_interiors/137882__deathicated__13122011000_48k.ogg",
    "assets/car_interiors/149429__conleec__amb_int_auto_driving_001_48k.ogg",
    "assets/car_interiors/521767__gecop__over-the-bridge-highway-drive-interior_48k.ogg",
    "assets/car_interiors/591103__jaimelopes__car-sequence-part-2_48k.ogg"
]

def _purge_temp(prefix="vlab_", older_than_sec=24*3600):
    now=time.time()
    try:
        for p in os.listdir(TMP_DIR):
            if not p.startswith(prefix): continue
            f=os.path.join(TMP_DIR,p)
            if now-os.path.getmtime(f)>older_than_sec: os.remove(f)
    except Exception: pass
atexit.register(_purge_temp)

# ───────────────── filters / env ─────────────────
def hpf_lpf(x: np.ndarray, hpf_hz: float = 0.0, lpf_hz: float = SR/2, zero_phase: bool = False) -> np.ndarray:
    y = x.astype(np.float32, copy=False)
    if hpf_hz and hpf_hz >= 20:
        sos = butter(2, hpf_hz/(SR/2), btype="high", output="sos")
        y = (sosfiltfilt(sos, y) if zero_phase else sosfilt(sos, y))
    if lpf_hz and lpf_hz < (SR/2):
        sos = butter(4, lpf_hz/(SR/2), btype="low", output="sos")
        y = (sosfiltfilt(sos, y) if zero_phase else sosfilt(sos, y))
    return y.astype(np.float32)

def _soft_clip(x: np.ndarray, drive: float = 1.0) -> np.ndarray:
    # Gentle limiter for small overshoots; drive=1 is subtle
    return np.tanh(drive * x).astype(np.float32)

def _prelimit(x: np.ndarray, threshold: float = 0.707) -> np.ndarray:
    # Pre-limit to prevent codec splattering
    peak = float(np.max(np.abs(x)) or 1.0)
    if peak > threshold:
        return (x * (threshold / peak)).astype(np.float32)
    return x.astype(np.float32)

def _mulaw_color(x: np.ndarray, amount: float, mu: float = 255.0, drive: float = 0.75) -> np.ndarray:
    """Band-limited μ-law coloration for realistic phone character without harsh distortion"""
    if amount <= 0.0:
        return x.astype(np.float32)

    x = _prelimit(x, 0.707)
    # Encode pass
    y = np.sign(x) * np.log1p(mu * np.abs(np.clip(x * drive, -1, 1))) / np.log1p(mu)
    # Decode pass to make it "codec color" not harsh nonlinearity
    y = np.sign(y) * (np.expm1(np.log1p(mu) * np.abs(y)) / mu)
    # Parallel blend
    out = (1.0 - amount) * x + amount * y
    return _soft_clip(out, 1.02).astype(np.float32)

def _zphf(x: np.ndarray, hpf_hz: float = 0.0, lpf_hz: float = SR/2, sr: int = SR) -> np.ndarray:
    """Zero-phase filtering for band extraction"""
    return hpf_lpf(x, hpf_hz, lpf_hz, zero_phase=True)

def apply_mulaw_color(x: np.ndarray, amount: float, mu: float = 255.0, drive: float = 0.75) -> np.ndarray:
    """Apply μ-law coloration with encode/decode cycle for realistic codec character"""
    if amount <= 0.0:
        return x.astype(np.float32)

    x = _prelimit(x, 0.707)
    # Encode pass
    y = np.sign(x) * np.log1p(mu * np.abs(np.clip(x * drive, -1, 1))) / np.log1p(mu)
    # Decode pass to make it "codec color" not harsh nonlinearity
    y = np.sign(y) * (np.expm1(np.log1p(mu) * np.abs(y)) / mu)
    # Parallel blend
    out = (1.0 - amount) * x + amount * y
    return _soft_clip(out, 1.02).astype(np.float32)

def env_follow(x: np.ndarray, atk_ms=15.0, rel_ms=350.0) -> np.ndarray:
    atk=max(1,int(SR*atk_ms/1000.0)); rel=max(1,int(SR*rel_ms/1000.0))
    e=np.zeros_like(x,dtype=np.float32); g=0.0; ax=np.abs(x)
    for i,v in enumerate(ax):
        g = (1-1/atk)*g + (1/atk)*v if v>g else (1-1/rel)*g + (1/rel)*v
        e[i]=g
    m=float(e.max() or 1.0); return (e/m).astype(np.float32)

def fade_window(n: int, fade: int) -> np.ndarray:
    if fade<=0 or fade*2>=n: return np.ones(n, dtype=np.float32)
    w=np.ones(n,dtype=np.float32); r=np.linspace(0,1,fade,dtype=np.float32)
    w[:fade]=r; w[-fade:]=r[::-1]; return w

# ───────────────── stronger dereverb ─────────────────
# Keep original (single-pass) for easy revert if needed
def dereverb_strong_original(y: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0: return y.astype(np.float32)
    try:
        import noisereduce as nr
        out = nr.reduce_noise(y=y, sr=SR, stationary=False, prop_decrease=float(np.clip(amount, 0, 1)))
        return out.astype(np.float32)
    except ImportError:
        return y.astype(np.float32)

# Enhanced: allow >1.0 by chaining multiple passes internally
def dereverb_strong(y: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0: return y.astype(np.float32)
    try:
        import noisereduce as nr
        rem = float(amount)
        out = y.astype(np.float32)
        while rem > 0.0:
            step = float(min(rem, 1.0))
            out = nr.reduce_noise(y=out, sr=SR, stationary=False, prop_decrease=step).astype(np.float32)
            rem -= step
        return out.astype(np.float32)
    except ImportError:
        return y.astype(np.float32)

# True dereverberation (late reflections) via WPE. Falls back gracefully if unavailable.
def wpe_dereverb(y: np.ndarray, iters: int = 1, taps: int = 12, delay: int = 3) -> Tuple[np.ndarray, str]:
    try:
        from nara_wpe import wpe as wpe_module
    except (ImportError, AttributeError, ModuleNotFoundError):
        return y.astype(np.float32), "WPE unavailable"
    # Use SciPy STFT/ISTFT to avoid extra dependencies
    nperseg = 512
    hop = 128
    noverlap = nperseg - hop
    win = get_window("hann", nperseg)
    _, _, Y = stft(y, fs=SR, window=win, nperseg=nperseg, noverlap=noverlap, boundary=None)
    # Shape to (F, C, T) with C=1
    Yc = Y[:, None, :]
    try:
        Xc = wpe_module.wpe(Yc, taps=int(taps), delay=int(delay), iterations=int(iters))
    except Exception:
        return y.astype(np.float32), "WPE unavailable"
    X = Xc[:, 0, :]
    _, x = istft(X, fs=SR, window=win, nperseg=nperseg, noverlap=noverlap, input_onesided=True, boundary=None)
    return x.astype(np.float32), "WPE applied"

# ───────────────── background + BG-IR ─────────────────
def convolve_ir(x: np.ndarray, ir_path: Optional[str], mix_percent: float = 0.0) -> np.ndarray:
    """Apply IR with wet/dry crossfade mixing. mix_percent: 0=dry, 100=fully wet"""
    if not ir_path or not os.path.exists(ir_path) or mix_percent <= 0:
        return x
    mix = np.clip(mix_percent / 100.0, 0.0, 1.0)
    ir,sr=_load_audio(ir_path); ir=_mono_sr(ir,sr,SR)
    if len(ir)<8: return x

    # Normalize IR
    ir=ir/(np.max(np.abs(ir))+1e-9)

    # Convolve with mode="full" to get complete result, then trim to original length
    # This prevents the delay/separation between dry and wet
    wet_full = fftconvolve(x, ir, mode="full").astype(np.float32)

    # Trim to original length (keep the beginning where direct sound + early reflections are)
    wet = wet_full[:len(x)]

    # Crossfade: 0% = dry only, 100% = wet only
    return (x * (1.0 - mix) + wet * mix).astype(np.float32)

def _bg_random_start(bed: np.ndarray, target_len: int) -> np.ndarray:
    """Randomize background start point for uniqueness, then tile/trim to target length."""
    if len(bed) == 0:
        return bed
    # Pick random start position
    start = random.randint(0, len(bed) - 1)
    # Rotate: concatenate from start to end, then beginning to start
    rotated = np.concatenate([bed[start:], bed[:start]])
    # Tile if needed
    if len(rotated) < target_len:
        reps = int(np.ceil(target_len / len(rotated)))
        rotated = np.tile(rotated, reps)
    # Trim to exact length
    return rotated[:target_len]

def stream_background(y: np.ndarray,
                      bg_path: Optional[str],
                      bg_ir_path: Optional[str],
                      bg_ir_gain_db: float,
                      bg_gain_db: float,
                      bg_hpf: float, bg_lpf: float,
                      duck_db: float) -> np.ndarray:
    if not bg_path:
        return y
    bed = _decode_any_to_float32(bg_path, SR)
    if bed.size == 0:
        return y
    # Randomize start point, then loop/tile to length
    bed = _bg_random_start(bed, len(y))
    # Background IR on bed
    if bg_ir_path:
        bed = convolve_ir(bed, bg_ir_path, float(bg_ir_gain_db))
    # Pad headroom, zero-phase filter, soft clip
    bed *= 0.85
    bed = hpf_lpf(bed, bg_hpf, bg_lpf, zero_phase=True)
    bed = _soft_clip(bed, drive=1.0)
    # Ducking envelope
    env = env_follow(y)
    duck_lin = 10**(float(duck_db)/20.0)
    g_bg = 10**(float(bg_gain_db)/20.0)
    g_duck = duck_lin + (1.0 - duck_lin) * (1.0 - env)
    return (y + g_bg * bed * g_duck).astype(np.float32)

# ───────────────── one-knob leveler ─────────────────
def leveler(x: np.ndarray, amount: float) -> np.ndarray:
    a=float(np.clip(amount,0.0,1.0))
    if a<=0: return x
    target_rms_db = -28.0 + 12.0*a
    atk_ms = 10.0 - 6.0*a; rel_ms = 320.0 - 200.0*a
    atk=max(1,int(SR*atk_ms/1000.0)); rel=max(1,int(SR*rel_ms/1000.0))
    env=np.zeros_like(x,dtype=np.float32); g=0.0; ax=np.abs(x)+1e-9
    for i,v in enumerate(ax):
        g = (1-1/atk)*g + (1/atk)*v if v>g else (1-1/rel)*g + (1/rel)*v
        env[i]=g
    tgt=10**(target_rms_db/20.0); y=x*(tgt/(env+1e-9))
    t=0.92 - 0.25*a
    return (np.tanh(y/t)*t).astype(np.float32)

# ───────────────── Opus round-trip ─────────────────
def opus_round_trip(in_wav_path: str, bitrate_kbps: float = 12.0, samplerate: int = SR) -> Optional[str]:
    if not have_ffmpeg(): return None
    def run(bps):
        key=hashlib.sha1(f"{_file_sig(in_wav_path)}:{bps}:{samplerate}".encode()).hexdigest()
        tmp_opus=os.path.join(TMP_DIR, f"vlab_{key}.opus")
        tmp_out =os.path.join(TMP_DIR, f"vlab_{key}.wav")
        if os.path.exists(tmp_out): return tmp_out
        enc=["ffmpeg","-y","-hide_banner","-loglevel","error","-i",in_wav_path,"-c:a","libopus","-b:a",f"{int(bps)}k","-ar",str(samplerate),tmp_opus]
        dec=["ffmpeg","-y","-hide_banner","-loglevel","error","-i",tmp_opus,"-ar",str(samplerate),tmp_out]
        pe=subprocess.run(enc,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if pe.returncode!=0: raise RuntimeError(pe.stderr.decode(errors="ignore")[:400])
        pd=subprocess.run(dec,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if pd.returncode!=0: raise RuntimeError(pd.stderr.decode(errors="ignore")[:400])
        return tmp_out if os.path.exists(tmp_out) else None
    try:
        return run(bitrate_kbps)
    except Exception:
        try: return run(12.0)
        except Exception:
            return None

# ───────────────── OLD EFFECTS you liked ─────────────────
def apply_stutter_old(x: np.ndarray, amt: float, sr: int = SR) -> np.ndarray:
    if amt <= 0: return x
    window = int(sr * 0.05)  # ~50ms
    out=[]; i=0
    while i < len(x):
        chunk = x[i:i+window]
        if random.random() < amt:
            repeats = random.randint(1,3)
            for _ in range(repeats): out.append(chunk)
        else:
            out.append(chunk)
        i += window
    y = np.concatenate(out)
    return y[:len(x)]

def apply_mp3_sizzle_old(x: np.ndarray, amt: float) -> np.ndarray:
    if amt <= 0: return x
    noise = np.random.normal(0, amt*0.01, size=x.shape).astype(np.float32)
    return (x + noise).astype(np.float32)

def apply_rf_noise_old(x: np.ndarray, amt: float) -> np.ndarray:
    if amt <= 0: return x
    noise = np.random.normal(0, amt*0.02, size=x.shape).astype(np.float32)
    return (x + noise).astype(np.float32)

def normalize_audio_lufs(y: np.ndarray, target_lufs: float = -23.0) -> np.ndarray:
    """Normalize audio to target LUFS level for consistent output"""
    if len(y) == 0:
        return y.astype(np.float32)

    try:
        import pyloudnorm as pyln
        # Create loudness meter
        meter = pyln.Meter(SR)
        # Measure loudness
        loudness = meter.integrated_loudness(y)
        # Skip if measurement failed or audio is silent
        if loudness == float('-inf') or np.isnan(loudness):
            return y.astype(np.float32)
        # Normalize to target
        normalized = pyln.normalize.loudness(y, loudness, target_lufs)
        return normalized.astype(np.float32)
    except ImportError:
        # Fallback to peak normalization if pyloudnorm not available
        peak = np.max(np.abs(y))
        if peak > 0:
            # Normalize to -6dB peak (rough LUFS equivalent)
            return (y * (0.32 / peak)).astype(np.float32)  # ~-10 dBFS for safer parity
        return y.astype(np.float32)
    except Exception:
        # Any other error, return original
        return y.astype(np.float32)

# ═══════════════════ COMPREHENSIVE PHONE QUALITY SYSTEM ═══════════════════

def apply_phone_quality_tier(y: np.ndarray, tier: str, custom_params: dict = None) -> tuple[np.ndarray, str]:
    """Apply tiered phone quality processing with predefined or custom parameters"""

    # Predefined quality tiers
    tiers = {
        "good_landline": {
            "bandwidth": (300, 3400),      # Standard PSTN bandwidth
            "sample_rate_factor": 1.0,     # Disable resampling to prevent distortion
            "bitrate_sim": 64,             # G.711 64 kbps
            "mu_law_intensity": 0.0,       # Disable μ-law to prevent distortion
            "noise_level": 0.0,            # No hidden noise - use RF slider
            "dropout_boost": 1.0,          # No multiplier - slider shows true value
            "garble_boost": 1.0,           # No multiplier - slider shows true value
            "description": "Clean PSTN Landline"
        },
        "bad_landline": {
            "bandwidth": (300, 3000),      # Narrower due to poor line
            "sample_rate_factor": 1.0,     # Disable resampling to prevent distortion
            "bitrate_sim": 64,             # Still G.711
            "mu_law_intensity": 0.0,       # Disable μ-law to prevent distortion
            "noise_level": 0.0,            # No hidden noise - use RF slider
            "dropout_boost": 1.0,          # No multiplier - slider shows true value
            "garble_boost": 1.0,           # No multiplier - slider shows true value
            "description": "Poor Landline - Hiss & Crackles"
        },
        "cordless": {
            "bandwidth": (300, 2800),      # High-cut at 2.8kHz
            "sample_rate_factor": 1.0,     # Disable resampling to prevent distortion
            "bitrate_sim": 24,             # 16-24 kbps equivalent
            "mu_law_intensity": 0.0,       # Disable μ-law to prevent distortion
            "noise_level": 0.0,            # No hidden noise - use RF slider
            "dropout_boost": 1.0,          # No multiplier - slider shows true value
            "garble_boost": 1.0,           # No multiplier - slider shows true value
            "description": "Cordless Phone - RF Interference"
        },
        "ultra_low": {
            "bandwidth": (200, 1800),      # Back to original narrow range
            "sample_rate_factor": 1.0,     # Disable resampling to prevent distortion
            "bitrate_sim": 8,              # Less aggressive bitrate
            "mu_law_intensity": 0.0,       # Disable μ-law to prevent distortion
            "noise_level": 0.0,            # No hidden noise - use RF slider
            "dropout_boost": 1.0,          # No multiplier - slider shows true value
            "garble_boost": 1.0,           # No multiplier - slider shows true value
            "description": "2G/3G Poor Signal"
        },
        "low": {
            "bandwidth": (200, 4000),      # Improved from 3G era
            "sample_rate_factor": 1.0,     # Disable resampling to prevent distortion
            "bitrate_sim": 16,             # Better bitrate
            "mu_law_intensity": 0.0,       # Disable μ-law to prevent distortion
            "noise_level": 0.0,            # No hidden noise - use RF slider
            "dropout_boost": 1.0,          # No multiplier - slider shows true value
            "garble_boost": 1.0,           # No multiplier - slider shows true value
            "description": "3G/Weak 4G Signal"
        },
        "standard": {
            "bandwidth": (250, 6000),      # Modern 4G LTE quality
            "sample_rate_factor": 1.0,     # Disable resampling to prevent distortion
            "bitrate_sim": 24,             # Better bitrate
            "mu_law_intensity": 0.0,       # Disable μ-law to prevent distortion
            "noise_level": 0.0,            # No hidden noise - use RF slider
            "dropout_boost": 1.0,          # No multiplier - slider shows true value
            "garble_boost": 1.0,           # No multiplier - slider shows true value
            "description": "Standard Cellular/PSTN"
        },
        "high": {
            "bandwidth": (20, 8000),       # HD Voice - wider for modern quality
            "sample_rate_factor": 1.0,     # NO downsampling to prevent distortion
            "bitrate_sim": 32,             # Good bitrate
            "mu_law_intensity": 0.0,       # Disable μ-law to prevent distortion
            "noise_level": 0.0,            # No hidden noise - use RF slider
            "dropout_boost": 1.0,          # No multiplier - slider shows true value
            "garble_boost": 1.0,           # No multiplier - slider shows true value
            "description": "HD Voice/High-Quality VoIP"
        },
        "ultra_high": {
            "bandwidth": (20, SR/2),     # Near-source quality - full spectrum
            "sample_rate_factor": 1.0,     # Full 48kHz - no downsampling
            "bitrate_sim": 128,            # Very high bitrate
            "mu_law_intensity": 0.0,       # No compression artifacts
            "noise_level": 0.0,            # No hidden noise - use RF slider
            "dropout_boost": 1.0,          # No multiplier - slider shows true value
            "garble_boost": 1.0,           # No multiplier - slider shows true value
            "description": "FaceTime/WhatsApp (Near-Source Quality)"
        }
    }

    # Use custom parameters if provided, otherwise use tier defaults
    if custom_params:
        params = custom_params
        description = "Custom Quality"
    else:
        params = tiers.get(tier, tiers["standard"])
        description = params["description"]

    # Apply bandwidth filtering
    low_freq, high_freq = params["bandwidth"]
    y = hpf_lpf(y, float(low_freq), float(high_freq), zero_phase=(tier in ("high", "ultra_high")))

    # Apply sample rate simulation (downsample/upsample for artifacts)
    if params["sample_rate_factor"] < 1.0:
        target_sr = int(SR * params["sample_rate_factor"])
        from scipy.signal import resample
        y_down = resample(y, int(len(y) * target_sr / SR))
        y = resample(y_down, len(y))

    # Apply μ-law processing based on tier type
    if tier in ("high", "ultra_high"):
        mu_amt = 0.0  # Modern VoIP/cellular - no μ-law
    elif tier in ("good_landline", "bad_landline", "cordless"):
        # Band-limited μ-law for authentic landline character
        cfg = {
            "good_landline": (0.20, 300.0, 2400.0, 0.70),
            "bad_landline":  (0.35, 300.0, 2400.0, 0.65),
            "cordless":      (0.35, 300.0, 2400.0, 0.75),
        }[tier]
        mu_amt, lo, hi, drive = cfg
        vband = _zphf(y, hpf_hz=lo, lpf_hz=hi, sr=SR)
        rest = y - vband
        vband = apply_mulaw_color(vband, amount=mu_amt, mu=255.0, drive=drive)
        y = vband + rest
    else:
        mu_amt = 0.0  # All other cellular tiers - no μ-law

    # Apply noise
    if params["noise_level"] > 0:
        noise = np.random.normal(0, params["noise_level"] * np.max(np.abs(y)), y.shape)
        y = (y + noise).astype(np.float32)

    return y, description

def apply_dropouts_old(v: np.ndarray, drop_p: float, chunk_ms: float, depth_db: float) -> np.ndarray:
    if drop_p<=0: return v
    w = max(8, int(chunk_ms*SR/1000.0))
    y = v.copy()
    for i in range(0, len(y), w):
        if random.random() < drop_p:
            seg = y[i:i+w]
            y[i:i+w] = seg * (10**(depth_db/20.0))  # attenuate or near-zero
    return y

def apply_garble_old(v: np.ndarray, garb_prob: float, sr: int = SR) -> np.ndarray:
    """EXACT garble from old fx app.py - single resampling with length preservation"""
    if garb_prob <= 0: return v
    gwin = int(0.06 * sr)  # 60ms windows like old app
    out = []
    for i in range(0, len(v), gwin):
        seg = v[i:i + gwin]
        original_len = len(seg)
        if random.random() < garb_prob:  # Use as probability like old app
            from scipy.signal import resample
            # Apply resampling factor like old app
            factor = 1 + random.uniform(-0.2, 0.2)
            new_len = int(len(seg) / factor)
            if new_len > 0:
                seg = resample(seg, new_len)
                # Pad or truncate to maintain segment length for concatenation
                if len(seg) < original_len:
                    seg = np.pad(seg, (0, original_len - len(seg)), 'constant')
                elif len(seg) > original_len:
                    seg = seg[:original_len]
        out.append(seg)
    result = np.concatenate(out)
    # Ensure exact same length as input
    if len(result) != len(v):
        if len(result) > len(v):
            result = result[:len(v)]
        else:
            result = np.pad(result, (0, len(v) - len(result)), 'constant')
    return result.astype(np.float32)

# NEW: micro robotization (max 0.01 is subtle)
def apply_jitter_buffering(x: np.ndarray, jitter_intensity: float, buffer_probability: float, sr: int = SR) -> np.ndarray:
    """VoIP jitter and buffering artifacts - realistic network timing issues"""
    if jitter_intensity <= 0 and buffer_probability <= 0: return x

    out = x.copy()
    n = len(x)

    # 1. JITTER: Variable latency causing timing wobble
    if jitter_intensity > 0:
        # Create small timing variations (10-80ms like ChatGPT suggested)
        max_jitter_samples = int(0.08 * sr * jitter_intensity)  # Scale by intensity
        jitter_buffer = np.zeros(n + max_jitter_samples * 2, dtype=np.float32)
        overlap = np.zeros_like(jitter_buffer)

        # Process in chunks with variable delay
        chunk_size = int(0.02 * sr)  # 20ms chunks
        write_pos = max_jitter_samples

        for i in range(0, n, chunk_size):
            chunk = out[i:i + chunk_size]
            if len(chunk) == 0: break

            # Add random jitter delay
            jitter_delay = int(random.uniform(-max_jitter_samples, max_jitter_samples))
            actual_pos = write_pos + jitter_delay

            # Bounds check
            if actual_pos >= 0 and actual_pos + len(chunk) < len(jitter_buffer):
                jitter_buffer[actual_pos:actual_pos + len(chunk)] += chunk
            overlap[actual_pos:actual_pos + len(chunk)] += 1.0

            write_pos += len(chunk)

        # Extract result with original length
        overlap[overlap == 0] = 1.0
        jitter_buffer /= overlap
        out = jitter_buffer[max_jitter_samples:max_jitter_samples + n]

    # 2. BUFFERING: Occasional rebuffering smears (70-300ms like ChatGPT suggested)
    if buffer_probability > 0:
        # Random rebuffering events
        rebuffer_events = int(buffer_probability * n / sr * 2)  # ~2 events per second at prob=1.0

        for _ in range(rebuffer_events):
            if n < sr * 0.1: break  # Skip if audio too short

            # Random rebuffer location and duration
            start = random.randint(0, n - int(0.3 * sr))
            duration = int(random.uniform(0.07, 0.3) * sr)  # 70-300ms
            end = min(start + duration, n)

            # Create smear effect by crossfading with delayed version
            segment = out[start:end]
            if len(segment) > 0:
                # Smear: blend with time-stretched version
                stretch_factor = random.uniform(0.8, 1.2)
                from scipy.signal import resample
                stretched = resample(segment, int(len(segment) * stretch_factor))

                # Fit back to original length with crossfade
                if len(stretched) != len(segment):
                    if len(stretched) > len(segment):
                        stretched = stretched[:len(segment)]
                    else:
                        stretched = np.pad(stretched, (0, len(segment) - len(stretched)), 'edge')

                # Crossfade blend for smooth smear
                fade_len = min(len(segment) // 4, int(0.01 * sr))
                if fade_len > 0:
                    fade_in = np.linspace(0, 1, fade_len)
                    fade_out = np.linspace(1, 0, fade_len)
                    stretched[:fade_len] = segment[:fade_len] * fade_out + stretched[:fade_len] * fade_in
                    stretched[-fade_len:] = segment[-fade_len:] * fade_out + stretched[-fade_len:] * fade_in

                out[start:end] = stretched

    return out.astype(np.float32)

def apply_packet_reordering(x: np.ndarray, reorder_probability: float, sr: int = SR) -> np.ndarray:
    """Packet reordering artifacts - different from dropouts, packets arrive out of order"""
    if reorder_probability <= 0: return x

    # Process in packet-sized chunks (20-40ms typical)
    packet_size = int(random.uniform(0.02, 0.04) * sr)  # 20-40ms packets
    out = []
    packet_buffer = []

    for i in range(0, len(x), packet_size):
        packet = x[i:i + packet_size]

        if random.random() < reorder_probability:
            # This packet gets reordered - add to buffer
            packet_buffer.append(packet)

            # Sometimes flush buffer in random order
            if len(packet_buffer) >= 3 or random.random() < 0.3:
                # Shuffle and flush buffer
                random.shuffle(packet_buffer)
                out.extend(packet_buffer)
                packet_buffer = []
            # If not flushing, add silence for missing packet
            else:
                out.append(np.zeros_like(packet))
        else:
            # Normal packet - flush any buffered packets first
            if packet_buffer:
                random.shuffle(packet_buffer)
                out.extend(packet_buffer)
                packet_buffer = []
            out.append(packet)

    # Flush remaining buffered packets
    if packet_buffer:
        random.shuffle(packet_buffer)
        out.extend(packet_buffer)

    result = np.concatenate(out) if out else x

    # Ensure same length as input
    if len(result) != len(x):
        if len(result) > len(x):
            result = result[:len(x)]
        else:
            result = np.pad(result, (0, len(x) - len(result)), 'constant')

    return result.astype(np.float32)

def apply_codec_artifacts(x: np.ndarray, codec_type: str, intensity: float, sr: int = SR) -> np.ndarray:
    """Codec-specific artifacts: AMR, Opus, EVS emulation"""
    if intensity <= 0: return x

    if codec_type == "amr_nb":
        # AMR Narrowband (GSM) - 8kHz, spectral combing, transient softening
        # Downsample to 8kHz and back up for aliasing
        from scipy.signal import resample
        downsampled = resample(x, int(len(x) * 8000 / sr))
        upsampled = resample(downsampled, len(x))

        # Add spectral combing (formant artifacts)
        comb_freq = 200 + random.uniform(-50, 50)  # ~200Hz comb
        t = np.arange(len(x)) / sr
        comb_mod = 1 + intensity * 0.1 * np.sin(2 * np.pi * comb_freq * t)

        # Transient softening - reduce attack sharpness
        from scipy.signal import hilbert
        envelope = np.abs(hilbert(x))
        smooth_env = np.convolve(envelope, np.ones(int(0.005*sr))/int(0.005*sr), mode='same')
        transient_mask = envelope / (smooth_env + 1e-10)
        transient_reduction = 1 - intensity * 0.3 * np.clip(transient_mask - 1, 0, 1)

        result = upsampled * comb_mod * transient_reduction

    elif codec_type == "amr_wb":
        # AMR Wideband - 16kHz, less artifacts but some warble
        warble_freq = random.uniform(0.5, 2.0)  # Slow warble
        t = np.arange(len(x)) / sr
        warble_mod = 1 + intensity * 0.05 * np.sin(2 * np.pi * warble_freq * t)

        # Mild spectral smearing
        from scipy.signal import savgol_filter
        if len(x) > 21:
            smoothed = savgol_filter(x, min(21, len(x)//2*2-1), 3)
            result = x * (1 - intensity * 0.2) + smoothed * intensity * 0.2
            result *= warble_mod
        else:
            result = x * warble_mod

    elif codec_type == "opus":
        # Opus - high quality but some transient pre-echo
        # Add subtle pre-echo before transients
        from scipy.signal import hilbert
        envelope = np.abs(hilbert(x))

        # Detect transients
        env_diff = np.diff(np.pad(envelope, (1,0), 'edge'))
        transient_mask = env_diff > np.std(env_diff) * 2

        # Add pre-echo
        pre_echo = np.zeros_like(x)
        pre_echo_samples = int(0.002 * sr)  # 2ms pre-echo

        for i in range(pre_echo_samples, len(x)):
            if transient_mask[i]:
                echo_start = max(0, i - pre_echo_samples)
                echo_strength = intensity * 0.1 * envelope[i]
                pre_echo[echo_start:i] += x[i] * echo_strength * np.linspace(0, 1, i - echo_start)

        result = x + pre_echo

    else:  # Default/EVS
        # EVS/Generic - minimal artifacts, just slight warble
        warble_freq = random.uniform(0.1, 0.5)
        t = np.arange(len(x)) / sr
        warble_mod = 1 + intensity * 0.02 * np.sin(2 * np.pi * warble_freq * t)
        result = x * warble_mod

    return result.astype(np.float32)

def apply_mic_proximity_effects(x: np.ndarray, proximity: float, mic_type: str = "handset", sr: int = SR) -> np.ndarray:
    """Mic proximity effects - distance and mic type characteristics"""
    if proximity <= 0: return x

    from scipy.signal import butter, lfilter

    if mic_type == "handset":
        # Handset mic: 2-6cm distance, proximity effect on low end
        # Closer = more bass boost, more breath sounds
        if proximity > 0.5:  # Close talking
            # Bass boost (proximity effect)
            b, a = butter(2, 200 / (sr / 2), btype='high')
            highpassed = lfilter(b, a, x)
            bass_boost = x - highpassed
            result = x + bass_boost * proximity * 0.3

            # Add subtle breath emphasis
            nyquist = sr / 2
            b, a = butter(2, [80 / nyquist, 300 / nyquist], btype='band')
            breath_band = lfilter(b, a, x)
            result += breath_band * proximity * 0.1
        else:
            result = x

    elif mic_type == "headset":
        # Headset: consistent distance, less proximity effect
        # Slight presence boost
        nyquist = sr / 2
        b, a = butter(2, [2000 / nyquist, 4000 / nyquist], btype='band')
        presence = lfilter(b, a, x)
        result = x + presence * proximity * 0.15

    elif mic_type == "speakerphone":
        # Speakerphone: far-field, room reflections, less direct sound
        # Reduce high frequencies, add slight reverb-like smear
        b, a = butter(2, 6000 / (sr / 2), btype='low')
        muffled = lfilter(b, a, x)

        # Simple reverb-like delay
        delay_samples = int(0.01 * sr)  # 10ms delay
        delayed = np.pad(x, (delay_samples, 0), 'constant')[:len(x)]

        # Mix based on proximity (lower = more far-field effect)
        far_field_amount = 1 - proximity
        result = x * proximity + (muffled * 0.7 + delayed * 0.3) * far_field_amount

    elif mic_type == "car":
        # Car environment: road noise filtering, confined space
        # Boost mids, reduce extremes
        b, a = butter(2, 150 / (sr / 2), btype='high')
        highpassed = lfilter(b, a, x)
        b, a = butter(2, 5000 / (sr / 2), btype='low')
        result = lfilter(b, a, highpassed)

        # Add slight resonance (car interior)
        resonance_freq = random.uniform(200, 400)
        t = np.arange(len(x)) / sr
        resonance = np.sin(2 * np.pi * resonance_freq * t) * proximity * 0.05
        result += x * resonance

    else:  # Default/studio
        result = x

    return result.astype(np.float32)

# Warble effect removed - was not in original working "old fx app.py" and was inaudible

# ───────────────── event slicers ─────────────────
def _expand_files_with_warnings(spec) -> Tuple[List[str], List[str]]:
    exts=(".wav",".mp3",".flac",".ogg",".aiff",".aif")
    found, miss = [], []
    if isinstance(spec,list):
        for p in spec:
            if isinstance(p,dict): p=p.get("name")
            if isinstance(p,str) and p.lower().endswith(exts) and os.path.exists(p): found.append(p)
            else: miss.append(str(p))
    elif isinstance(spec,str):
        if os.path.isdir(spec):
            for p in sorted(glob.glob(os.path.join(spec,"*"))):
                if p.lower().endswith(exts): found.append(p)
        elif spec.lower().endswith(exts) and os.path.exists(spec): found.append(spec)
        else: miss.append(str(spec))
    return found, miss

def _random_slice(y: np.ndarray, min_s: float, max_s: float) -> np.ndarray:
    n=len(y); min_n=int(min_s*SR); max_n=int(max_s*SR)
    if n<=min_n: return y[:min_n]
    L=np.random.randint(min_n, min(max_n, n))
    start=np.random.randint(0, max(1, n-L))
    return y[start:start+L]

def place_events(xlen: int, files: List[str], events_per_min: float,
                 vol_db: float, min_len_s=0.8, max_len_s=2.0, max_overlap=0.5) -> np.ndarray:
    """Smart event placement with 3-second threshold: short=one-shots, long=ambient with random start"""
    out=np.zeros(xlen,dtype=np.float32)
    if events_per_min<=0 or not files: return out
    occ=np.zeros(xlen,dtype=np.uint8)
    n_events=int(events_per_min*(xlen/SR)/60.0)

    for _ in range(n_events):
        f=np.random.choice(files)
        try:
            s,sr=_load_audio(f); s=_mono_sr(s,sr,SR)
            original_duration = len(s) / SR

            # Smart handling based on 3-second threshold
            if original_duration >= 3.0:
                # LONG FILES (≥3s): Ambient scenes with random start points
                # Random start point to avoid repetition for different callers
                max_start_offset = max(0, len(s) - int(xlen * 0.8))  # Don't exceed 80% of clip length
                if max_start_offset > 0:
                    start_offset = np.random.randint(0, max_start_offset)
                    s = s[start_offset:]  # Start from random position

                # Take reasonable length for ambient background
                max_duration = min(len(s)/SR, xlen/SR * 0.6)  # Max 60% of clip length
                target_samples = int(max_duration * SR)
                s = s[:target_samples]

                # Reduce event count for long samples (they're background, not events)
                if _ > 0:  # Only place one long sample per event cycle
                    continue

            else:
                # SHORT FILES (<3s): One-shot events, play fully with random placement
                # Use existing random slicing for variety, but respect full file when possible
                if original_duration <= max_len_s:
                    # File is short enough - use it fully
                    pass  # Keep original s
                else:
                    # File is longer than max - slice it
                    s=_random_slice(s,min_len_s,max_len_s)

            L=len(s)
            if L>=xlen:
                start=0
                s = s[:xlen]  # Truncate if too long
                L = xlen
            else:
                placed=False
                for _try in range(4):
                    if original_duration >= 3.0:
                        # Long samples: prefer early placement for natural background feel
                        start = np.random.randint(0, min(xlen-L, int(xlen*0.2)))
                    else:
                        # Short samples: random placement throughout
                        start=np.random.randint(0,xlen-L)
                    overlap=occ[start:start+L].sum()/max(1,L)
                    if overlap<=max_overlap: placed=True; break
                if not placed: continue

            end=start+L
            fade=max(4,int(0.004*SR))

            # Apply fade window - longer fades for long ambient samples
            if original_duration >= 3.0:
                fade = max(fade, int(0.15*SR))  # 150ms fade for ambient samples

            # RMS normalization for consistent event levels
            rms = np.sqrt(np.mean(s**2) + 1e-9)
            target_rms = 0.1  # Consistent RMS level for all events
            if rms > 0:
                s = s * (target_rms / rms)

            out[start:end]+= s*fade_window(L,fade) * 10**(vol_db/20.0)
            occ[start:end]=np.minimum(occ[start:end]+1,3)
        except Exception:
            continue
    return out

# ───────────────── processor (correct chain) ─────────────────
def process_audio(
    mic_file,
    # Source
    dereverb_amt, src_hpf, src_lpf, leveler_amt,
    # Dereverb (WPE)
    wpe_strength, cleanup_mix,
    # Room IR (pre)
    room_ir_file, room_ir_gain_db,
    # Background
    bg_file, bg_ir_file, bg_ir_gain_db, bg_gain_db, bg_hpf, bg_lpf, bg_duck_db,
    # Phone quality system
    quality_tier, custom_low_freq, custom_high_freq, custom_compression, custom_noise, custom_dropout_mult, custom_garble_mult,
    # Phone color / codec (legacy)
    bandwidth_mode, opus_bitrate_kbps, post_mu_grit,
    # Network artifacts (enhanced realistic effects)
    plc_ms, dropout_prob, dropout_depth_db,
    garble_prob, stutter_amt, jitter_intensity, buffer_prob, reorder_prob,
    codec_type, codec_intensity, mic_proximity, mic_type, mp3_amt, rf_amt,
    # Handset IR (post)
    handset_ir_file, handset_ir_gain_db,
    # SFX events
    traffic_files, traffic_ev_min, traffic_vol_db,
    baby_files, baby_ev_min, baby_vol_db,
    dog_files, dog_ev_min, dog_vol_db,
    # Output
    normalize_output
):
    # input
    mic_path=_safe_file(mic_file)
    if not mic_path: return None, "No input."
    y,sr=_load_audio(mic_path); y=_mono_sr(y,sr,SR)
    if len(y)<int(0.05*SR): return None,"Input too short."
    if len(y)>30*60*SR: return None,"Input too long (>30m)."

    # 1) Source cleanup
    modern = quality_tier in ("high", "ultra_high")
    try:
        wpe_strength = float(wpe_strength)
    except Exception:
        wpe_strength = 0.0
    try:
        dereverb_amt = float(dereverb_amt)
    except Exception:
        dereverb_amt = 0.0
    try:
        leveler_amt = float(leveler_amt)
    except Exception:
        leveler_amt = 0.0

    try:
        cleanup_mix = float(cleanup_mix)
    except Exception:
        cleanup_mix = 1.0 if not modern else 0.0
    cleanup_mix = float(np.clip(cleanup_mix, 0.0, 1.0))
    if not modern:
        cleanup_mix = 1.0

    user_requested_cleanup = (wpe_strength > 0.0) or (dereverb_amt > 0.0)
    cleanup_allowed = (not modern) or user_requested_cleanup

    y_base = y.astype(np.float32, copy=True)
    wpe_note = ""
    if cleanup_allowed and user_requested_cleanup:
        y_proc = y_base.copy()
        if wpe_strength > 0.0:
            try:
                iters = 2 if wpe_strength >= 0.66 else 1
                y_wpe, wpe_msg = wpe_dereverb(y_proc, iters, 12, 3)
                y_proc = (1.0 - wpe_strength) * y_proc + wpe_strength * y_wpe.astype(np.float32)
                if wpe_msg == "WPE applied" and (not modern or cleanup_mix > 0.0):
                    wpe_note = " · WPE"
            except Exception:
                pass
        if dereverb_amt > 0.0:
            y_proc = dereverb_strong(y_proc, dereverb_amt)

        if not modern or cleanup_mix >= 0.999:
            y = y_proc
        elif cleanup_mix <= 0.001:
            y = y_base
        else:
            y = y_base + cleanup_mix * (y_proc - y_base)
    else:
        y = y_base

    y = hpf_lpf(y, float(src_hpf), float(src_lpf))

    if leveler_amt > 0.0:
        y = leveler(y, float(leveler_amt))

    # 2) Room IR (pre-codec) with double-guard
    _room_ir = _safe_file(room_ir_file)
    _bg_ir_for_guard = _safe_file(bg_ir_file)
    same_ir = _same_file(_room_ir, _bg_ir_for_guard)
    _room_ir_apply = None if same_ir else _room_ir
    ir_guard_note = " · IR:BG only (guard)" if same_ir else ""

    # Apply Room IR (pre-codec)
    y = convolve_ir(y, _room_ir_apply, float(room_ir_gain_db))  # room_ir_gain_db now represents mix %

    # 3) Events BEFORE phone coloration (so they get processed through phone chain too)
    xlen=len(y)
    traf_ok,_ = _expand_files_with_warnings(_coerce_paths_list(traffic_files))
    baby_ok,_ = _expand_files_with_warnings(_coerce_paths_list(baby_files))
    dog_ok,_  = _expand_files_with_warnings(_coerce_paths_list(dog_files))
    y += place_events(xlen, traf_ok, float(traffic_ev_min), float(traffic_vol_db))
    y += place_events(xlen, baby_ok,  float(baby_ev_min),  float(baby_vol_db))
    y += place_events(xlen, dog_ok,   float(dog_ev_min),   float(dog_vol_db))

    # 4) Background bed (with Background IR and its own filters + ducking)
    bg_candidates = _coerce_paths_list(bg_file)
    selected_bg = random.choice(bg_candidates) if bg_candidates else None
    if selected_bg and os.path.exists(selected_bg):
        bg_desc = os.path.basename(selected_bg)
    elif bg_candidates:
        bg_desc = f"random from {len(bg_candidates)} files"
    else:
        bg_desc = "none"
    y = stream_background(y, _safe_file(selected_bg), _safe_file(bg_ir_file),
                          float(bg_ir_gain_db), float(bg_gain_db),
                          float(bg_hpf), float(bg_lpf), float(bg_duck_db))

    # Pre-limit the combined remote mix so μ-law/codec can't splatter
    peak = float(np.max(np.abs(y)) or 1.0)
    if peak > 0.707:  # ~ -3 dBFS
        y = (y * (0.707 / peak)).astype(np.float32)

    # 5) Comprehensive Phone Quality System
    if quality_tier != "custom":
        # Use predefined quality tier
        y, quality_description = apply_phone_quality_tier(y, quality_tier)
        codec_status = quality_description
    else:
        # Use custom parameters
        custom_params = {
            "bandwidth": (float(custom_low_freq), float(custom_high_freq)),
            "sample_rate_factor": 1.0,  # Keep full rate for custom
            "bitrate_sim": 32,  # Standard for custom
            "mu_law_intensity": float(custom_compression),
            "noise_level": float(custom_noise),
            "dropout_boost": float(custom_dropout_mult),
            "garble_boost": float(custom_garble_mult)
        }
        y, quality_description = apply_phone_quality_tier(y, "custom", custom_params)
        codec_status = f"Custom Quality ({int(custom_low_freq)}-{int(custom_high_freq)}Hz)"

    # Legacy processing (only for non-modern tiers)
    modern = quality_tier in ["high", "ultra_high"]
    if not modern:
        if bandwidth_mode=="Narrowband 300–3500":
            y=hpf_lpf(y, 300.0, 3500.0)
        elif bandwidth_mode=="Wideband 80–7000":
            y=hpf_lpf(y, 80.0, 7000.0)

    # Opus processing (skip for high-quality tiers and landlines to preserve source quality)
    skip_opus = quality_tier in ["high", "ultra_high", "good_landline", "bad_landline", "cordless"]
    if not skip_opus and opus_bitrate_kbps < 32:  # Only apply Opus for lower bitrates
        tmp_in=_save_wav_tmp(y)
        opus_path=opus_round_trip(tmp_in, float(opus_bitrate_kbps), SR)
        if opus_path:
            yc,osr=_load_audio(opus_path); y=_mono_sr(yc,osr,SR)
            codec_status += f" + Opus {int(float(opus_bitrate_kbps))} kbps"

    # Additional μ-law grit (legacy control) - reduced for more realistic calls
    if post_mu_grit>0:
        a=float(np.clip(post_mu_grit,0.0,0.15)); mu=255.0  # Reduced max from 0.35 to 0.15
        comp=np.sign(y)*np.log1p(mu*np.abs(y))/np.log1p(mu)
        y=((1.0-a)*y + a*comp).astype(np.float32)

    # 6) Network artifacts with quality-aware scaling
    # Skip digital artifacts for landline tiers (they have analog-specific issues instead)
    skip_digital_artifacts = quality_tier in ["good_landline", "bad_landline", "cordless"]

    if not skip_digital_artifacts:
        # Get quality multipliers for artifacts
        if quality_tier == "custom":
            dropout_mult = float(custom_dropout_mult)
            garble_mult = float(custom_garble_mult)
        else:
            # Get multipliers from quality tier
            tier_params = {
                "good_landline": {"dropout_boost": 0.0, "garble_boost": 0.0, "stutter_amt": 0.0},
                "bad_landline": {"dropout_boost": 0.3, "garble_boost": 0.0, "stutter_amt": 0.0},
                "cordless": {"dropout_boost": 0.5, "garble_boost": 0.3, "stutter_amt": 0.001},  # Light RF stutter
                "ultra_low": {"dropout_boost": 2.0, "garble_boost": 1.8, "stutter_amt": 0.006},  # Heavy 2G/3G stutter
                "low": {"dropout_boost": 1.5, "garble_boost": 1.4, "stutter_amt": 0.004},       # Medium 3G stutter
                "standard": {"dropout_boost": 1.0, "garble_boost": 1.0, "stutter_amt": 0.002},  # Light cellular stutter
                "high": {"dropout_boost": 0.5, "garble_boost": 0.5, "stutter_amt": 0.001},      # Minimal HD stutter
                "ultra_high": {"dropout_boost": 0.2, "garble_boost": 0.2, "stutter_amt": 0.0}   # No stutter
            }.get(quality_tier, {"dropout_boost": 1.0, "garble_boost": 1.0, "stutter_amt": 0.002})
            dropout_mult = tier_params["dropout_boost"]
            garble_mult = tier_params["garble_boost"]
            tier_stutter_amt = tier_params["stutter_amt"]

        # Comprehensive artifact short-circuit: skip entire chain if all artifacts are zero
        has_artifacts = max(
            float(dropout_prob) * dropout_mult,
            float(garble_prob) * garble_mult,
            tier_stutter_amt if tier_stutter_amt > 0 else float(stutter_amt),
            float(jitter_intensity),
            float(buffer_prob),
            float(reorder_prob),
            float(codec_intensity),
            float(mp3_amt),
            float(rf_amt)
        ) > 0.0

        if has_artifacts:
            # Apply RF noise FIRST (affects radio signal before digital processing)
            # Only for cellular - landlines don't have RF
            if quality_tier not in ["good_landline", "bad_landline"]:
                y = apply_rf_noise_old(y, float(rf_amt))

            # Apply garble with quality scaling
            scaled_garble_prob = float(garble_prob) * garble_mult
            y = apply_garble_old(y, min(scaled_garble_prob, 1.0), SR)

            # Apply dropouts with quality scaling
            scaled_dropout_prob = float(dropout_prob) * dropout_mult
            y = apply_dropouts_old(y, min(scaled_dropout_prob, 1.0), float(plc_ms), float(dropout_depth_db))

            # Enhanced realistic network artifacts - use tier-specific stutter if available
            final_stutter_amt = tier_stutter_amt if tier_stutter_amt > 0 else float(stutter_amt)
            y = apply_stutter_old(y, final_stutter_amt, SR)
            y = apply_jitter_buffering(y, float(jitter_intensity), float(buffer_prob), SR)
            y = apply_packet_reordering(y, float(reorder_prob), SR)
            y = apply_codec_artifacts(y, codec_type, float(codec_intensity), SR)
            y = apply_mic_proximity_effects(y, float(mic_proximity), mic_type, SR)
            y = apply_mp3_sizzle_old(y, float(mp3_amt))
    else:
        # Landline-specific processing
        if quality_tier == "bad_landline":
            # Light jitter for analog line instability (not digital jitter)
            y = apply_jitter_buffering(y, min(float(jitter_intensity) * 0.5, 0.01), 0.0, SR)
            # analog tick/crackle → use tiny dropouts instead of packet reordering
            y = apply_dropouts_old(y, min(float(dropout_prob) * 0.2, 0.05), float(plc_ms), float(dropout_depth_db))
        elif quality_tier == "cordless":
            # Moderate dropout for range interference (not packet dropouts)
            scaled_dropout_prob = min(float(dropout_prob) * 0.5, 0.15)
            y = apply_dropouts_old(y, scaled_dropout_prob, float(plc_ms), float(dropout_depth_db))
            # Light stutter for RF interference
            y = apply_stutter_old(y, min(float(stutter_amt) * 0.5, 0.04), SR)
            # RF noise for cordless interference (only if slider > 0)
            y = apply_rf_noise_old(y, float(rf_amt))
        # good_landline gets no additional artifacts (clean line)

    # Safety before normalization to avoid nasty codec-fed hard clips
    if np.max(np.abs(y)) > 1.0:
        y = _soft_clip(y, drive=1.1)

    # 7) Handset IR (post)
    # Skip handset IR if: modern tier OR Room IR was actually applied (check _room_ir_apply, not room_ir_file)
    _handset_resolved = _safe_file(handset_ir_file)
    room_ir_was_applied = ('_room_ir_apply' in locals() and _room_ir_apply and float(room_ir_gain_db) > 0)
    apply_handset = (quality_tier not in ("high", "ultra_high")) and not room_ir_was_applied

    if apply_handset and _handset_resolved:
        y = convolve_ir(y, _handset_resolved, float(handset_ir_gain_db))
        handset_note = f" · HandsetIR:{os.path.basename(_handset_resolved)}({int(float(handset_ir_gain_db))}dB)"
    else:
        handset_note = " · HandsetIR:skipped" if not apply_handset else " · HandsetIR:none"

    # 8) Final normalization
    if normalize_output:
        y = normalize_audio_lufs(y, -18.0)
        norm_note = " · Normalized"
    else:
        y = normalize_peak(y, 0.97)
        norm_note = ""

    # Build status details
    if quality_tier != "custom":
        _tier_map = {
            "good_landline": (300, 2400, 0.20),
            "bad_landline":  (300, 2400, 0.35),
            "cordless":      (300, 2400, 0.35),
            "high":          (20, 8000, 0.00),
            "ultra_high":    (20, int(SR/2), 0.00),
            "ultra_low":     (200, 1800, 0.00),
            "low":           (200, 4000, 0.00),
            "standard":      (250, 6000, 0.00),
        }
        lo, hi, mu_amt = _tier_map.get(quality_tier, (250, 6000, 0.00))
    else:
        lo, hi = int(custom_low_freq), int(custom_high_freq)
        mu_amt = float(custom_compression)

    room_path_or_none = (os.path.abspath(_room_ir_apply) if ('_room_ir_apply' in locals() and _room_ir_apply) else "none")
    _bg_ir_resolved = _safe_file(bg_ir_file)
    bg_ir_path_or_none = (os.path.abspath(_bg_ir_resolved) if _bg_ir_resolved else "none")
    room_mix = float(room_ir_gain_db)
    bg_ir_mix = float(bg_ir_gain_db)

    status = (f"OK · Codec: {codec_status}{wpe_note} · BW {int(lo)}–{int(hi)} Hz · μ-law {mu_amt:.2f} · "
              f"RoomIR:{room_path_or_none}({int(room_mix)}%) · BGIR:{bg_ir_path_or_none}({int(bg_ir_mix)}%) · "
              f"BG:{bg_desc}{ir_guard_note}{handset_note}{norm_note}")

    return _save_wav_tmp(y), status


def process_bojan_preset(mic_file, preset_name: str, normalize_override: Optional[bool] = None):
    """Run the simplified preset flow used by the basic Bojan UI."""
    preset = BOJAN_PRESET_CONFIGS.get(preset_name)
    if not preset:
        return None, f"Unknown preset '{preset_name}'."

    cfg = dict(BOJAN_PRESET_DEFAULTS)
    cfg.update(preset)
    if normalize_override is not None:
        cfg["normalize_output"] = bool(normalize_override)

    args = [cfg[name] for name in PROCESS_AUDIO_PARAM_ORDER]
    return process_audio(
        mic_file,
        *args
    )


def process_editor_request(
    mic_file,
    dereverb_amt, src_hpf, src_lpf, leveler_amt,
    wpe_strength, cleanup_mix,
    room_ir_upload, room_ir_path, room_ir_gain,
    bg_file_upload, bg_file_path,
    bg_ir_upload, bg_ir_path,
    bg_ir_gain, bg_gain, bg_hpf, bg_lpf, bg_duck,
    quality_tier, custom_low_freq, custom_high_freq, custom_compression, custom_noise, custom_dropout_mult, custom_garble_mult,
    bandwidth_mode, opus_bitrate_kbps, post_mu_grit,
    plc_ms, dropout_prob, dropout_depth_db,
    garble_prob, stutter_amt, jitter_intensity, buffer_prob, reorder_prob,
    codec_type, codec_intensity, mic_proximity, mic_type, mp3_amt, rf_amt,
    handset_ir_upload, handset_ir_path, handset_ir_gain,
    traffic_files, traffic_ev_min, traffic_vol_db,
    baby_files, baby_ev_min, baby_vol_db,
    dog_files, dog_ev_min, dog_vol_db,
    normalize_output
):
    room_ir_final = _resolve_file(room_ir_upload, room_ir_path)
    bg_file_final = _resolve_files(bg_file_upload, bg_file_path)
    bg_ir_final = _resolve_file(bg_ir_upload, bg_ir_path)
    handset_ir_final = _resolve_file(handset_ir_upload, handset_ir_path)

    return process_audio(
        mic_file,
        dereverb_amt, src_hpf, src_lpf, leveler_amt,
        wpe_strength,
        cleanup_mix,
        room_ir_final, room_ir_gain,
        bg_file_final, bg_ir_final, bg_ir_gain, bg_gain, bg_hpf, bg_lpf, bg_duck,
        quality_tier, custom_low_freq, custom_high_freq, custom_compression, custom_noise, custom_dropout_mult, custom_garble_mult,
        bandwidth_mode, opus_bitrate_kbps, post_mu_grit,
        plc_ms, dropout_prob, dropout_depth_db,
        garble_prob, stutter_amt, jitter_intensity, buffer_prob, reorder_prob,
        codec_type, codec_intensity, mic_proximity, mic_type, mp3_amt, rf_amt,
        handset_ir_final, handset_ir_gain,
        traffic_files, traffic_ev_min, traffic_vol_db,
        baby_files, baby_ev_min, baby_vol_db,
        dog_files, dog_ev_min, dog_vol_db,
        normalize_output
    )

# ───────────────── presets I/O ─────────────────
def flatten_schema2_preset(preset: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Schema 2 (nested) preset to Schema 1 (flat) format for UI compatibility."""
    flat = {}

    # Source parameters
    source = preset.get("source", {})
    flat["dereverb"] = source.get("dereverb", 1.0)
    flat["src_hpf"] = source.get("src_hpf", 0)
    flat["src_lpf"] = source.get("src_lpf", 20000)
    flat["leveler_amt"] = source.get("leveler_amt", 0.6)
    flat["wpe_strength"] = source.get("wpe_strength", 0.0)
    flat["cleanup_mix"] = source.get("cleanup_mix", 1.0)

    # Room IR
    room_ir = preset.get("room_ir", {})
    flat["room_ir_file"] = room_ir.get("file") or ""
    flat["room_ir_gain"] = room_ir.get("mix_percent", 0)

    # Background
    background = preset.get("background", {})
    bg_files = background.get("files", [])
    flat["bg_file"] = bg_files if bg_files else []
    flat["bg_gain"] = background.get("gain_db", -14.0)
    flat["bg_hpf"] = background.get("hpf", 0)
    flat["bg_lpf"] = background.get("lpf", 1800)
    flat["bg_duck"] = background.get("duck_db", -12.0)

    # Background IR
    bg_ir = preset.get("background_ir", {})
    flat["bg_ir_file"] = bg_ir.get("file") or ""
    flat["bg_ir_gain"] = bg_ir.get("gain_db", 0.0)

    # Quality tier
    flat["quality_tier"] = preset.get("quality_tier", "standard")

    # Custom quality parameters (defaults)
    flat["custom_low_freq"] = 300.0
    flat["custom_high_freq"] = 3400.0
    flat["custom_compression"] = 0.3
    flat["custom_noise"] = 0.03
    flat["custom_dropout_mult"] = 1.0
    flat["custom_garble_mult"] = 1.0

    # Codec
    codec = preset.get("codec", {})
    flat["bandwidth"] = codec.get("bandwidth_override") or "Narrowband 300–3500"
    flat["opus_br"] = 12.0
    flat["post_mu"] = codec.get("mu_law_amt", 0.0)

    # Network artifacts
    artifacts = preset.get("network_artifacts", {})
    flat["plc_ms"] = artifacts.get("plc_ms", 60.0)
    flat["dropout_prob"] = artifacts.get("dropout_prob", 0.1)
    flat["dropout_depth"] = artifacts.get("dropout_depth_db", -24.0)
    flat["garble_p"] = artifacts.get("garble_intensity", 0.01)
    flat["stutter_a"] = artifacts.get("stutter_amt", 0.002)
    flat["jitter_a"] = artifacts.get("jitter_intensity", 0.0)
    flat["buffer_p"] = 0.0
    flat["reorder_p"] = artifacts.get("reorder_prob", 0.0)
    flat["codec_type"] = "amr_nb"
    flat["codec_intensity"] = 0.0
    flat["mic_proximity"] = 0.5
    flat["mic_type"] = "handset"
    flat["mp3_a"] = 0.0
    flat["rf_a"] = artifacts.get("rf_noise", 0.0)

    # Handset IR
    handset_ir = preset.get("handset_ir", {})
    flat["handset_ir_file"] = handset_ir.get("file") or ""
    flat["handset_ir_gain"] = handset_ir.get("gain_db", 0.0)

    # Events
    events = preset.get("events", {})
    flat["traf_ev"] = events.get("traffic_ev_min", 4.0)
    flat["traf_vol"] = events.get("traffic_vol_db", -6.0)
    flat["baby_ev"] = events.get("baby_ev_min", 3.0)
    flat["baby_vol"] = -8.0
    flat["dog_ev"] = events.get("dog_ev_min", 3.0)
    flat["dog_vol"] = -8.0

    # Output
    output = preset.get("output", {})
    flat["normalize_output"] = output.get("target_lufs") is not None

    return flat

def load_presets() -> Dict[str, Any]:
    def _blank():
        return {
            "schema": 1,
            "presets": {
                "📞 Classic Landline": {
                    "dereverb": 1.0, "src_hpf": 80, "src_lpf": 8000, "leveler_amt": 0.7, "wpe_strength": 0.3, "cleanup_mix": 1.0,
                    "room_ir_file": None, "room_ir_gain_db": 0, "quality_tier": "good_landline",
                    "bg_file": None, "bg_gain_db": -20, "bg_hpf": 100, "bg_lpf": 2000, "bg_duck_db": -12, "bg_ir_file": None, "bg_ir_gain_db": -15,
                    "rf_a": 0.0, "dropout_prob": 0.0, "plc_ms": 20, "dropout_depth_db": -40,
                    "garble_intensity": 0.0, "stutter_amt": 0.0, "jitter_intensity": 0.0, "reorder_prob": 0.0,
                    "handset_ir_file": None, "handset_ir_gain_db": -6, "target_lufs": -18
                },
                "📱 Modern Cellular": {
                    "dereverb": 1.2, "src_hpf": 50, "src_lpf": 12000, "leveler_amt": 0.6, "wpe_strength": 0.2, "cleanup_mix": 1.0,
                    "room_ir_file": None, "room_ir_gain_db": 0, "quality_tier": "high",
                    "bg_file": None, "bg_gain_db": -25, "bg_hpf": 80, "bg_lpf": 3000, "bg_duck_db": -15, "bg_ir_file": None, "bg_ir_gain_db": -18,
                    "rf_a": 0.0, "dropout_prob": 0.02, "plc_ms": 15, "dropout_depth_db": -35,
                    "garble_intensity": 0.01, "stutter_amt": 0.0, "jitter_intensity": 0.005, "reorder_prob": 0.0,
                    "handset_ir_file": None, "handset_ir_gain_db": -8, "target_lufs": -18
                },
                "🎧 Premium VoIP": {
                    "dereverb": 0.8, "src_hpf": 20, "src_lpf": 20000, "leveler_amt": 0.5, "wpe_strength": 0.1, "cleanup_mix": 1.0,
                    "room_ir_file": None, "room_ir_gain_db": 0, "quality_tier": "ultra_high",
                    "bg_file": None, "bg_gain_db": -30, "bg_hpf": 50, "bg_lpf": 4000, "bg_duck_db": -18, "bg_ir_file": None, "bg_ir_gain_db": -20,
                    "rf_a": 0.0, "dropout_prob": 0.0, "plc_ms": 10, "dropout_depth_db": -30,
                    "garble_intensity": 0.0, "stutter_amt": 0.0, "jitter_intensity": 0.0, "reorder_prob": 0.0,
                    "handset_ir_file": None, "handset_ir_gain_db": -10, "target_lufs": -18
                },
                "🚦 Street Caller": {
                    "dereverb": 0.25, "src_hpf": 80, "src_lpf": 17000, "leveler_amt": 0.45, "wpe_strength": 0.0, "cleanup_mix": 1.0,
                    "room_ir_file": None, "room_ir_gain_db": 0, "quality_tier": "low",
                    "bg_file": list(BACKGROUND_POOL), "bg_gain_db": -19, "bg_hpf": 120, "bg_lpf": 1400, "bg_duck_db": -14, "bg_ir_file": None, "bg_ir_gain_db": 0,
                    "rf_a": 0.2, "dropout_prob": 0.14, "plc_ms": 50, "dropout_depth_db": -28,
                    "garble_intensity": 0.06, "stutter_amt": 0.015, "jitter_intensity": 0.05, "reorder_prob": 0.02,
                    "handset_ir_file": "assets/irs/cellphone_dry_trimmed.wav", "handset_ir_gain_db": -6, "target_lufs": -19,
                    "traffic_files": list(HORN_POOL),
                    "traffic_ev_min": 10, "traffic_vol_db": -4,
                    "baby_files": list(BABY_POOL), "baby_ev_min": 0,
                    "dog_files": list(DOG_POOL), "dog_ev_min": 0,
                    "car_files": list(CAR_POOL)
                },
                "📶 Spotty Service": {
                    "dereverb": 0.3, "src_hpf": 100, "src_lpf": 16000, "leveler_amt": 0.55, "wpe_strength": 0.1, "cleanup_mix": 1.0,
                    "room_ir_file": None, "room_ir_gain_db": 0, "quality_tier": "ultra_low",
                    "bg_file": list(BACKGROUND_POOL), "bg_gain_db": -32, "bg_hpf": 180, "bg_lpf": 2200, "bg_duck_db": -16, "bg_ir_file": None, "bg_ir_gain_db": 0,
                    "rf_a": 0.35, "dropout_prob": 0.32, "plc_ms": 32, "dropout_depth_db": -38,
                    "garble_intensity": 0.32, "stutter_amt": 0.045, "jitter_intensity": 0.18, "reorder_prob": 0.08,
                    "handset_ir_file": "assets/irs/cellphone_dry_trimmed.wav", "handset_ir_gain_db": -9, "target_lufs": -20,
                    "traffic_files": list(HORN_POOL),
                    "traffic_ev_min": 6, "traffic_vol_db": -8,
                    "baby_files": list(BABY_POOL), "baby_ev_min": 0,
                    "dog_files": list(DOG_POOL), "dog_ev_min": 0,
                    "car_files": list(CAR_POOL)
                },
                "🛁 Bathroom Caller": {
                    "dereverb": 0.0, "src_hpf": 60, "src_lpf": 20000, "leveler_amt": 0.35, "wpe_strength": 0.0, "cleanup_mix": 0.5,
                    "room_ir_file": "assets/irs/bathroom.ogg", "room_ir_gain_db": 60, "quality_tier": "high",
                    "bg_file": [
                        "assets/Party Music/techno 1_48k.ogg",
                        "assets/Party Music/techno 2_48k.ogg"
                    ], "bg_gain_db": -28, "bg_hpf": 0, "bg_lpf": 1200, "bg_duck_db": -18, "bg_ir_file": None, "bg_ir_gain_db": 0,
                    "rf_a": 0.01, "dropout_prob": 0.01, "plc_ms": 25, "dropout_depth_db": -40,
                    "garble_intensity": 0.01, "stutter_amt": 0.003, "jitter_intensity": 0.008, "reorder_prob": 0.004,
                    "handset_ir_file": "assets/irs/cellphone_dry_trimmed.wav", "handset_ir_gain_db": -5, "target_lufs": None,
                    "traffic_files": ["assets/car horns/733168__locky_y__honking.mp3"],
                    "traffic_ev_min": 2, "traffic_vol_db": -18,
                    "baby_ev_min": 0, "dog_ev_min": 0
                },
                "🎉 Bathroom Party": {
                    "dereverb": 0.0, "src_hpf": 50, "src_lpf": 20000, "leveler_amt": 0.35, "wpe_strength": 0.0, "cleanup_mix": 0.5,
                    "room_ir_file": "assets/irs/bathroom.ogg", "room_ir_gain_db": 70, "quality_tier": "high",
                    "bg_file": [
                        "assets/Party Music/techno 1_48k.ogg",
                        "assets/Party Music/techno 2_48k.ogg"
                    ], "bg_gain_db": -24, "bg_hpf": 0, "bg_lpf": 1200, "bg_duck_db": -20, "bg_ir_file": None, "bg_ir_gain_db": 0,
                    "rf_a": 0.05, "dropout_prob": 0.05, "plc_ms": 38, "dropout_depth_db": -24,
                    "garble_intensity": 0.05, "stutter_amt": 0.012, "jitter_intensity": 0.03, "reorder_prob": 0.015,
                    "handset_ir_file": "assets/irs/cellphone_dry_trimmed.wav", "handset_ir_gain_db": -5, "target_lufs": -18,
                    "traffic_files": ["assets/car horns/425848__soundholder__renault-master-f3500-dci135-foley-horn-outside-mono.mp3"],
                    "traffic_ev_min": 3, "traffic_vol_db": -20,
                    "baby_ev_min": 0, "dog_ev_min": 0
                },
                "🎯 True Source": {
                    "dereverb": 0.0, "src_hpf": 0, "src_lpf": 20000, "leveler_amt": 0.0, "wpe_strength": 0.0,
                    "room_ir_file": None, "room_ir_gain_db": 0, "quality_tier": "ultra_high",
                    "bg_file": None, "bg_gain_db": -60, "bg_hpf": 20, "bg_lpf": 20000, "bg_duck_db": -60, "bg_ir_file": None, "bg_ir_gain_db": 0,
                    "rf_a": 0.0, "dropout_prob": 0.0, "plc_ms": 0, "dropout_depth_db": -60,
                    "garble_intensity": 0.0, "stutter_amt": 0.0, "jitter_intensity": 0.0, "reorder_prob": 0.0,
                    "handset_ir_file": None, "handset_ir_gain_db": 0, "target_lufs": -18
                }
            }
        }
    try:
        if not os.path.exists(PRESETS_PATH): return _blank()
        with open(PRESETS_PATH,"r") as f: j=json.load(f)
        if not isinstance(j,dict): return _blank()
        if "presets" not in j or not isinstance(j["presets"], dict):
            j["presets"]={}
        if "schema" not in j: j["schema"]=2

        # Hardcoded presets are hidden - only load from presets.json
        # (Hardcoded presets still exist in _blank() as backup but won't appear in dropdown)

        return j
    except Exception: return _blank()

def save_presets(obj: Dict[str, Any]):
    try:
        with open(PRESETS_PATH,"w") as f: json.dump(obj,f,indent=2)
    except Exception: pass

# ───────────────── UI ─────────────────
def create_app():
    theme = gr.themes.Soft(primary_hue="purple", secondary_hue="violet")
    with gr.Blocks(title="VoiceLab FX — Editor", theme=theme) as demo:
        gr.Markdown("## VoiceLab FX — Editor (Full)")
        gr.Markdown(f"**ffmpeg:** {'✅ Found' if have_ffmpeg() else '⚠️ Not found — μ-law fallback only'}")

        prs_state = gr.State(load_presets())

        with gr.Row():
            mic = gr.Audio(sources=["upload"], type="filepath", label="Input WAV/MP3/FLAC")
            out = gr.Audio(type="filepath", label="Processed Output")

        with gr.Row():
            preset_dd = gr.Dropdown(
                choices=sorted(prs_state.value["presets"].keys()) or ["Default"],
                value=(sorted(prs_state.value["presets"].keys())[0] if prs_state.value["presets"] else "Default"),
                label="Preset"
            )
            preset_name = gr.Textbox(label="Save as… (name)")
            btn_save = gr.Button("💾 Save/Overwrite Preset", variant="primary")
            btn_reload = gr.Button("🔄 Reload presets.json")

        with gr.Tab("Source"):
            dereverb = gr.Slider(0.0, 2.0, 1.0, step=0.01, label="Noise Reduction (Spectral Gate)")
            src_hpf = gr.Slider(0, 300, 0, step=10, label="Source HPF (Hz)")
            src_lpf = gr.Slider(2000, 20000, 20000, step=100, label="Source LPF (Hz)")
            leveler_amt = gr.Slider(0.0, 1.0, 0.6, step=0.01, label="Leveler Amount (one-knob)")
            wpe_strength = gr.Slider(0.0, 1.0, 0.0, step=0.01, label="Dereverberation (WPE)", info="0=off, 1=strong; fixed taps/delay inside")
            cleanup_mix = gr.Slider(0.0, 1.0, 1.0, step=0.05, label="Cleanup Mix", info="Blend of dereverbed voice (1) vs original tone (0)")

        with gr.Tab("Room IR (pre-codec)"):
            room_ir = gr.File(label="Room IR (WAV)")
            room_ir_path = gr.Textbox(label="Current Room IR", value="", interactive=True)
            room_ir_gain = gr.Slider(0, 25, 0, step=1, label="Room IR Mix (%)", info="0=dry, 25=max wet")

        with gr.Tab("Background"):
            bg_file = gr.File(file_count="multiple", label="Background bed (WAV/OGG/etc.)")
            bg_file_path = gr.Textbox(label="Current Background", value="", interactive=True, lines=3)
            bg_ir_file = gr.File(label="Background IR (applies to bed only)")
            bg_ir_path = gr.Textbox(label="Current Background IR", value="", interactive=True)
            bg_ir_gain = gr.Slider(-24, 24, 0, step=0.5, label="Background IR Gain (dB)")
            bg_gain = gr.Slider(-60, 24, -14, step=0.5, label="Background Volume (dB)")
            bg_duck = gr.Slider(-60, 0, -12, step=1, label="Background Ducking (dB)")
            bg_hpf = gr.Slider(0, 600, 0, step=10, label="Background HPF (Hz)")
            bg_lpf = gr.Slider(20, 8000, 1800, step=50, label="Background LPF (Hz)")

        def _display_single(file):
            return _safe_file(file) or ""

        def _display_multi(files):
            return "\n".join(_normalize_path_list(files))

        with gr.Tab("Phone Quality"):
            gr.Markdown("### Comprehensive Phone Call Quality Simulation")

            # Quality tier selector
            quality_tier = gr.Radio(
                choices=["standard", "high", "ultra_high", "custom"],
                value="high",
                label="Quality Tier",
                info="Select quality level (only tiers you use) - sliders show true values"
            )

            # Custom quality controls (shown when 'custom' is selected)
            with gr.Group(visible=False) as custom_controls:
                gr.Markdown("**Custom Quality Parameters**")
                with gr.Row():
                    custom_low_freq = gr.Slider(20, 1000, 300, step=10, label="Low Freq (Hz)")
                    custom_high_freq = gr.Slider(1000, 8000, 3400, step=50, label="High Freq (Hz)")
                with gr.Row():
                    custom_compression = gr.Slider(0.0, 1.0, 0.3, step=0.05, label="Compression Intensity")
                    custom_noise = gr.Slider(0.0, 0.2, 0.03, step=0.005, label="Noise Level")
                with gr.Row():
                    custom_dropout_mult = gr.Slider(0.1, 3.0, 1.0, step=0.1, label="Dropout Multiplier")
                    custom_garble_mult = gr.Slider(0.1, 3.0, 1.0, step=0.1, label="Garble Multiplier")

            # Legacy controls (still available for fine-tuning)
            gr.Markdown("**Legacy Fine-Tuning Controls**")
            bandwidth = gr.Radio(choices=["Narrowband 300–3500","Wideband 80–7000"], value="Narrowband 300–3500", label="Bandwidth Override", visible=False)
            opus_br = gr.Slider(6, 64, 12, step=1, label="Opus Bitrate (kbps)", visible=False)
            post_mu = gr.Slider(0.0, 0.35, 0.0, step=0.01, label="Extra μ-law Grit (post-codec)", visible=False)

            # Quality tier descriptions
            quality_info = gr.Textbox(
                value="Standard Cellular/PSTN Quality",
                label="Current Quality Description",
                interactive=False
            )

            # Network Artifacts (moved here for easier editing with tier changes)
            gr.Markdown("**Network Artifacts** *(sliders show true applied values)*")
            plc_ms = gr.Slider(20.0, 120.0, 60.0, step=5.0, label="PLC segment (ms)", info="Packet loss concealment segment length")
            dropout_prob = gr.Slider(0.0, 0.20, 0.01, step=0.001, label="Dropout probability / segment", info="Range: 0-0.20")
            dropout_depth = gr.Slider(-60.0, 0.0, -40.0, step=1.0, label="Dropout Depth (dB)")
            with gr.Row():
                garble_p  = gr.Slider(0.0, 0.08, 0.01, step=0.001, label="Garble Probability", info="Range: 0-0.08")
                stutter_a = gr.Slider(0.0, 0.03, 0.0, step=0.001, label="Stutter Amount", info="Range: 0-0.03")
            with gr.Row():
                jitter_a  = gr.Slider(0.0, 0.08, 0.0, step=0.001, label="Jitter Intensity", info="Range: 0-0.08")
                buffer_p  = gr.Slider(0.0, 0.05, 0.0, step=0.001, label="Buffer Probability", info="Range: 0-0.05")
            with gr.Row():
                reorder_p = gr.Slider(0.0, 0.03, 0.0, step=0.001, label="Packet Reorder", info="Range: 0-0.03")
                codec_type = gr.Dropdown(["amr_nb", "amr_wb", "opus", "evs"], value="amr_nb", label="Codec Type", visible=False)
                codec_intensity = gr.Slider(0.0, 0.2, 0.0, step=0.01, label="Codec Artifacts", info="Range: 0-0.2", visible=False)
            with gr.Row():
                mic_proximity = gr.Slider(0.0, 1.0, 0.5, step=0.01, label="Mic Proximity", info="Distance/proximity effects")
                mic_type = gr.Dropdown(["handset", "headset", "speakerphone", "car"], value="handset", label="Mic Type")
            with gr.Row():
                mp3_a     = gr.Slider(0.0, 0.2, 0.00, step=0.01, label="MP3 Sizzle", info="Range: 0-0.2")
                rf_a      = gr.Slider(0.0, 0.15, 0.00, step=0.001, label="RF Noise", info="Range: 0-0.15")

            # Quality tier change handler
            def update_quality_info_and_artifacts(tier):
                descriptions = {
                    "good_landline": "Clean PSTN Landline - Standard call center quality",
                    "bad_landline": "Poor Landline - Hiss, crackles, analog line noise",
                    "cordless": "Cordless Phone - RF interference, range artifacts",
                    "ultra_low": "2G/3G Heavy Compression - Almost inaudible, severe artifacts",
                    "low": "Bluetooth/Weak Signal - Problematic connection with dropouts",
                    "standard": "Standard Cellular/PSTN - Typical phone call quality",
                    "high": "HD Voice/High-Quality VoIP - Clear connection with minimal artifacts",
                    "ultra_high": "FaceTime/WhatsApp Quality - Near-CD quality audio",
                    "custom": "Custom Quality - Manual parameter control"
                }

                # Get tier parameters to show ACTUAL applied values in sliders
                tiers = {
                    "good_landline": {"dropout_boost": 0.0, "garble_boost": 0.0, "stutter_amt": 0.0, "noise_level": 0.0},
                    "bad_landline": {"dropout_boost": 0.3, "garble_boost": 0.0, "stutter_amt": 0.0, "noise_level": 0.003},
                    "cordless": {"dropout_boost": 0.5, "garble_boost": 0.3, "stutter_amt": 0.001, "noise_level": 0.002},
                    "ultra_low": {"dropout_boost": 2.0, "garble_boost": 1.8, "stutter_amt": 0.006, "noise_level": 0.005},
                    "low": {"dropout_boost": 1.5, "garble_boost": 1.4, "stutter_amt": 0.004, "noise_level": 0.002},
                    "standard": {"dropout_boost": 1.0, "garble_boost": 1.0, "stutter_amt": 0.002, "noise_level": 0.001},
                    "high": {"dropout_boost": 0.5, "garble_boost": 0.5, "stutter_amt": 0.001, "noise_level": 0.0},
                    "ultra_high": {"dropout_boost": 0.2, "garble_boost": 0.2, "stutter_amt": 0.0, "noise_level": 0.0},
                    "custom": {"dropout_boost": 1.0, "garble_boost": 1.0, "stutter_amt": 0.002, "noise_level": 0.001}
                }

                show_custom = tier == "custom"
                tier_params = tiers.get(tier, tiers["standard"])

                # Show ACTUAL final values that will be applied (not just suggestions)
                # Modern tiers should be artifact-free by default
                is_modern = tier in ("high", "ultra_high")
                base_dropout = 0.0 if is_modern else 0.10  # base dropout probability
                base_garble = 0.0 if is_modern else 0.02   # base garble probability

                # Calculate actual final values
                final_dropout = min(1.0, base_dropout * tier_params["dropout_boost"]) if tier_params["dropout_boost"] > 0 else 0.0
                final_garble = min(0.5, base_garble * tier_params["garble_boost"]) if tier_params["garble_boost"] > 0 else 0.0
                final_stutter = 0.0 if is_modern else tier_params["stutter_amt"]  # Zero for modern tiers
                final_rf = 0.0 if is_modern else tier_params["noise_level"]  # Zero for modern tiers

                return (
                    gr.update(visible=show_custom),
                    descriptions.get(tier, "Unknown"),
                    gr.update(value=final_dropout),   # dropout_prob - actual applied value
                    gr.update(value=final_garble),    # garble_p - actual applied value
                    gr.update(value=final_stutter),   # stutter_a - actual applied value
                    gr.update(value=final_rf)         # rf_a - actual applied value
                )

        with gr.Tab("Handset IR (post-codec)"):
            handset_ir = gr.File(label="Handset/Speaker IR (WAV)")
            handset_ir_path = gr.Textbox(label="Current Handset IR", value="", interactive=False)
            handset_ir_gain = gr.Slider(-24, 24, 0, step=0.5, label="Handset IR Gain (dB)")

        with gr.Tab("Output"):
            normalize_output = gr.Checkbox(False, label="Normalize Output", info="Normalize all processed audio to consistent level (-18 LUFS for radio broadcast)")

        with gr.Tab("SFX Generators"):
            traf_files = gr.File(file_count="multiple", label="Traffic (horns/sirens/streets)")
            traf_ev = gr.Slider(0, 60, 4, step=0.5, label="Traffic events/min")
            traf_vol = gr.Slider(-60, 12, -6, step=1, label="Traffic vol (dB)")
            baby_files = gr.File(file_count="multiple", label="Baby files")
            baby_ev = gr.Slider(0, 60, 3, step=0.5, label="Baby events/min")
            baby_vol = gr.Slider(-60, 12, -8, step=1, label="Baby vol (dB)")
            dog_files = gr.File(file_count="multiple", label="Dog files")
            dog_ev = gr.Slider(0, 60, 3, step=0.5, label="Dog events/min")
            dog_vol = gr.Slider(-60, 12, -8, step=1, label="Dog vol (dB)")

        status = gr.Textbox(label="Status", interactive=False)
        run = gr.Button("⚙️ Process", variant="primary")

        room_ir.change(_display_single, inputs=room_ir, outputs=room_ir_path, api_name=False)
        bg_file.change(_display_multi, inputs=bg_file, outputs=bg_file_path, api_name=False)
        bg_ir_file.change(_display_single, inputs=bg_ir_file, outputs=bg_ir_path, api_name=False)
        handset_ir.change(_display_single, inputs=handset_ir, outputs=handset_ir_path, api_name=False)

        # Connect quality tier changes to artifact slider updates
        quality_tier.change(
            update_quality_info_and_artifacts,
            inputs=[quality_tier],
            outputs=[custom_controls, quality_info, dropout_prob, garble_p, stutter_a, rf_a],
            api_name=False
        )

        run.click(
            process_editor_request,
            inputs=[
                mic,
                dereverb, src_hpf, src_lpf, leveler_amt,
                wpe_strength, cleanup_mix,
                room_ir, room_ir_path, room_ir_gain,
                bg_file, bg_file_path,
                bg_ir_file, bg_ir_path,
                bg_ir_gain, bg_gain, bg_hpf, bg_lpf, bg_duck,
                quality_tier, custom_low_freq, custom_high_freq, custom_compression, custom_noise, custom_dropout_mult, custom_garble_mult,
                bandwidth, opus_br, post_mu,
                plc_ms, dropout_prob, dropout_depth,
                garble_p, stutter_a, jitter_a, buffer_p, reorder_p, codec_type, codec_intensity, mic_proximity, mic_type, mp3_a, rf_a,
                handset_ir, handset_ir_path, handset_ir_gain,
                traf_files, traf_ev, traf_vol,
                baby_files, baby_ev, baby_vol,
                dog_files, dog_ev, dog_vol,
                normalize_output
            ],
            outputs=[out, status]
        )

        # Presets (dict schema) — dropdown, save, reload
        prs_state.value = load_presets()

        def on_save(pstate, name, *vals):
            name = (name or "Untitled").strip()
            keys = [
                "dereverb","src_hpf","src_lpf","leveler_amt",
                "wpe_strength","cleanup_mix",
                "room_ir_file","room_ir_gain",
                "bg_file","bg_ir_file","bg_ir_gain","bg_gain","bg_hpf","bg_lpf","bg_duck",
                "quality_tier","custom_low_freq","custom_high_freq","custom_compression","custom_noise","custom_dropout_mult","custom_garble_mult",
                "bandwidth","opus_br","post_mu",
                "plc_ms","dropout_prob","dropout_depth",
                "garble_p","stutter_a","jitter_a","buffer_p","reorder_p","codec_type","codec_intensity","mic_proximity","mic_type","mp3_a","rf_a",
                "handset_ir_file","handset_ir_gain",
                "traf_ev","traf_vol","baby_ev","baby_vol","dog_ev","dog_vol",
                "normalize_output"
            ]
            cfg = dict(zip(keys, vals))
            bg_list = _normalize_path_list(cfg.get("bg_file"))
            cfg["bg_file"] = bg_list if bg_list else None
            p = dict(pstate); p.setdefault("schema",1); p.setdefault("presets",{})
            p["presets"][name] = cfg
            save_presets(p)
            dd = gr.Dropdown(choices=sorted(p["presets"].keys()), value=name)
            return p, dd, f"Saved '{name}'."

        btn_save.click(
            on_save,
            inputs=[prs_state, preset_name,
                    dereverb, src_hpf, src_lpf, leveler_amt,
                    wpe_strength, cleanup_mix,
                    room_ir_path, room_ir_gain,
                    bg_file_path, bg_ir_path, bg_ir_gain, bg_gain, bg_hpf, bg_lpf, bg_duck,
                    quality_tier, custom_low_freq, custom_high_freq, custom_compression, custom_noise, custom_dropout_mult, custom_garble_mult,
                    bandwidth, opus_br, post_mu,
                    plc_ms, dropout_prob, dropout_depth,
                    garble_p, stutter_a, jitter_a, buffer_p, reorder_p, codec_type, codec_intensity, mic_proximity, mic_type, mp3_a, rf_a,
                    handset_ir_path, handset_ir_gain,
                    traf_ev, traf_vol, baby_ev, baby_vol, dog_ev, dog_vol,
                    normalize_output],
            outputs=[prs_state, preset_dd, status],
            api_name=False
        )

        def on_reload():
            p = load_presets()
            dd = gr.Dropdown(choices=sorted(p["presets"].keys()) or ["Default"],
                             value=(sorted(p["presets"].keys())[0] if p["presets"] else "Default"))
            return p, dd, "Presets reloaded."
        btn_reload.click(on_reload, outputs=[prs_state, preset_dd, status], api_name=False)

        def on_choose(pstate, name):
            preset_raw = pstate["presets"].get(name, {})
            # Detect schema: if it has "source" key, it's Schema 2 (nested)
            if "source" in preset_raw:
                cfg = flatten_schema2_preset(preset_raw)
            else:
                # Schema 1 (flat) - use as-is
                cfg = preset_raw
            def v(k,d): return cfg.get(k,d)
            return (
                gr.update(value=v("dereverb",1.0)),
                gr.update(value=v("src_hpf",0.0)),
                gr.update(value=v("src_lpf",20000.0)),
                gr.update(value=v("leveler_amt",0.6)),
                gr.update(value=v("wpe_strength",0.0)),
                gr.update(value=v("cleanup_mix",1.0)),

                gr.update(value=v("room_ir_file","")),
                gr.update(value=v("room_ir_gain",0.0)),

                gr.update(value='\n'.join(v("bg_file", [])) if isinstance(v("bg_file", None), list) else (v("bg_file", "") or "")),
                gr.update(value=v("bg_ir_file","")),
                gr.update(value=v("bg_ir_gain",0.0)),
                gr.update(value=v("bg_gain",-14.0)),
                gr.update(value=v("bg_hpf",0.0)),
                gr.update(value=v("bg_lpf",1800.0)),
                gr.update(value=v("bg_duck",-12.0)),

                gr.update(value=v("quality_tier","standard")),
                gr.update(value=v("custom_low_freq",300.0)),
                gr.update(value=v("custom_high_freq",3400.0)),
                gr.update(value=v("custom_compression",0.3)),
                gr.update(value=v("custom_noise",0.03)),
                gr.update(value=v("custom_dropout_mult",1.0)),
                gr.update(value=v("custom_garble_mult",1.0)),

                gr.update(value=v("bandwidth","Narrowband 300–3500")),
                gr.update(value=v("opus_br",12.0)),
                gr.update(value=v("post_mu",0.0)),

                gr.update(value=v("plc_ms",60.0)),
                gr.update(value=v("dropout_prob",0.1)),
                gr.update(value=v("dropout_depth",-24.0)),

                gr.update(value=v("garble_p",0.01)),
                gr.update(value=v("stutter_a",0.002)),
                gr.update(value=v("jitter_a",0.0)),
                gr.update(value=v("buffer_p",0.0)),
                gr.update(value=v("reorder_p",0.0)),
                gr.update(value=v("codec_type","amr_nb")),
                gr.update(value=v("codec_intensity",0.0)),
                gr.update(value=v("mic_proximity",0.5)),
                gr.update(value=v("mic_type","handset")),
                gr.update(value=v("mp3_a",0.0)),
                gr.update(value=v("rf_a",0.0)),

                gr.update(value=v("handset_ir_file","")),
                gr.update(value=v("handset_ir_gain",0.0)),

                gr.update(value=v("traf_ev",4.0)),
                gr.update(value=v("traf_vol",-6.0)),
                gr.update(value=v("baby_ev",3.0)),
                gr.update(value=v("baby_vol",-8.0)),
                gr.update(value=v("dog_ev",3.0)),
                gr.update(value=v("dog_vol",-8.0)),
                gr.update(value=v("normalize_output",False))
            )
        preset_dd.change(on_choose, inputs=[prs_state, preset_dd],
                         outputs=[dereverb, src_hpf, src_lpf, leveler_amt, wpe_strength, cleanup_mix,
                                  room_ir_path, room_ir_gain,
                                  bg_file_path, bg_ir_path, bg_ir_gain, bg_gain, bg_hpf, bg_lpf, bg_duck,
                                  quality_tier, custom_low_freq, custom_high_freq, custom_compression, custom_noise, custom_dropout_mult, custom_garble_mult,
                                  bandwidth, opus_br, post_mu,
                                  plc_ms, dropout_prob, dropout_depth,
                                  garble_p, stutter_a, jitter_a, buffer_p, reorder_p, codec_type, codec_intensity, mic_proximity, mic_type, mp3_a, rf_a,
                                  handset_ir_path, handset_ir_gain,
                                  traf_ev, traf_vol, baby_ev, baby_vol, dog_ev, dog_vol, normalize_output],
                         api_name=False)



    return demo

if __name__=="__main__":
    app = create_app()
    app.queue(default_concurrency_limit=4).launch(server_name="0.0.0.0", server_port=7860)
