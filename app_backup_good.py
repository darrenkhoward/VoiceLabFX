# app.py — VoiceLab FX core (drop-in)
# Fixes: SR=48000, modern tier handling, landline μ-law band path, IR double-guard, OGG BG decode
# UI and control names unchanged elsewhere; this file keeps the same public API.
import os, io, atexit, tempfile, json, random, math, time, warnings, glob, hashlib, subprocess
from typing import Optional, Dict, Any, List, Tuple
import numpy as np

from scipy.signal import butter, sosfilt, sosfiltfilt, fftconvolve, lfilter, get_window, stft, istft
from scipy.io import wavfile

try:
    import soundfile as sf
    HAVE_SF = True
except Exception:
    HAVE_SF = False

warnings.filterwarnings("ignore", category=UserWarning)

# ───────────────── constants ─────────────────
SR = 48000
TMP_DIR = tempfile.mkdtemp(prefix="voicelabfx_")
_TEMP_FILES: List[str] = []

def _tmp_path(suffix: str = ".wav") -> str:
    p = os.path.join(TMP_DIR, f"tmp_{int(time.time()*1000)}_{random.randint(0,1_000_000)}{suffix}")
    _TEMP_FILES.append(p)
    return p

def _save_wav_tmp(y: np.ndarray, sr: int = SR) -> str:
    p = _tmp_path(".wav")
    wavfile.write(p, sr, (np.clip(y, -1.0, 1.0) * 32767.0).astype(np.int16))
    return p

def _purge_temp():
    try:
        for f in list(_TEMP_FILES):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
    except Exception:
        pass
atexit.register(_purge_temp)

# ───────────────── file helpers ─────────────────
def _safe_file(x) -> Optional[str]:
    if isinstance(x, str) and x.strip() and os.path.exists(x.strip()):
        return x.strip()
    try:
        if hasattr(x, "name") and os.path.exists(x.name):
            return x.name
    except Exception:
        pass
    return None

def _coerce_paths_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for v in value:
            p = _safe_file(v) or (v if isinstance(v, str) else None)
            if p:
                out.append(p)
        return out
    if isinstance(value, str):
        parts=[line.strip() for line in value.replace(';', '\n').splitlines() if line.strip()]
        return parts
    return []

def _same_file(a: Optional[str], b: Optional[str]) -> bool:
    try:
        if not a or not b: return False
        return os.path.abspath(a) == os.path.abspath(b)
    except Exception:
        return False

def have_ffmpeg() -> bool:
    try:
        return subprocess.run(["ffmpeg","-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
    except Exception:
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
                    if HAVE_SF:
                        data, fs = sf.read(tmp_wav, dtype="float32", always_2d=False)
                        if isinstance(data, np.ndarray):
                            if data.ndim == 2:
                                data = data.mean(axis=1)
                            if fs != sr:
                                data = _mono_sr(data, fs, sr)
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
    if HAVE_SF:
        try:
            data, fs = sf.read(path, dtype="float32", always_2d=False)
            if isinstance(data, np.ndarray):
                if data.ndim == 2:
                    data = data.mean(axis=1)
                if fs != sr:
                    data = _mono_sr(data, fs, sr)
                return data.astype(np.float32, copy=False)
        except Exception:
            return np.zeros(0, dtype=np.float32)
    return np.zeros(0, dtype=np.float32)

# ───────────────── audio I/O ─────────────────
def _load_audio(path: str) -> Tuple[np.ndarray, int]:
    if not path or not os.path.exists(path):
        return np.zeros(1, dtype=np.float32), SR
    try:
        sr, x = wavfile.read(path)
        if x.dtype.kind == 'i':
            x = x.astype(np.float32) / 32768.0
        elif x.dtype.kind == 'f':
            x = x.astype(np.float32)
        else:
            x = x.astype(np.float32)
        return x, sr
    except Exception:
        # fallback via ffmpeg to handle mp3/ogg/etc
        y = _decode_any_to_float32(path, SR)
        return (y if y.size else np.zeros(1,dtype=np.float32)), SR

def _mono_sr(x: np.ndarray, sr: int, target_sr: int = SR) -> np.ndarray:
    if x.ndim > 1:
        x = x.mean(axis=1).astype(np.float32)
    if sr != target_sr:
        tmp_in = _save_wav_tmp(x, sr)
        tmp_out = _tmp_path(".wav")
        os.system(f'ffmpeg -y -hide_banner -loglevel error -i "{tmp_in}" -ar {target_sr} -ac 1 -f wav "{tmp_out}"')
        _, y = wavfile.read(tmp_out)
        if y.dtype.kind == 'i':
            y = y.astype(np.float32) / 32768.0
        else:
            y = y.astype(np.float32)
        return y
    return x.astype(np.float32)

# ───────────────── filters/utilities ─────────────────
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
    return np.tanh(drive * x).astype(np.float32)

def _prelimit(x: np.ndarray, threshold: float = 0.707) -> np.ndarray:
    peak = float(np.max(np.abs(x)) or 1.0)
    if peak > threshold:
        return (x * (threshold / peak)).astype(np.float32)
    return x.astype(np.float32)

def _zphf(x: np.ndarray, hpf_hz: float = 0.0, lpf_hz: float = SR/2) -> np.ndarray:
    return hpf_lpf(x, hpf_hz, lpf_hz, zero_phase=True)

def apply_mulaw_color(x: np.ndarray, amount: float, mu: float = 255.0, drive: float = 0.75) -> np.ndarray:
    if amount <= 0.0:
        return x.astype(np.float32)
    x = _prelimit(x, 0.707)
    y = np.sign(x) * np.log1p(mu * np.abs(np.clip(x * drive, -1, 1))) / np.log1p(mu)
    y = np.sign(y) * (np.expm1(np.log1p(mu) * np.abs(y)) / mu)
    out = (1.0 - amount) * x + amount * y
    return _soft_clip(out, 1.02).astype(np.float32)

def fade_window(n: int, fade: int) -> np.ndarray:
    if fade<=0 or fade*2>=n: return np.ones(n, dtype=np.float32)
    w=np.ones(n,dtype=np.float32); r=np.linspace(0,1,fade,dtype=np.float32)
    w[:fade]=r; w[-fade:]=r[::-1]; return w

def rms_db(x: np.ndarray) -> float:
    return 20.0*np.log10(float(np.sqrt(np.mean(np.square(x))+1e-12))+1e-12)

# ───────────────── dereverb / leveler ─────────────────
def dereverb_strong(y: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0: return y.astype(np.float32)
    try:
        import noisereduce as nr
        a=float(np.clip(amount,0.0,1.0))
        y1 = nr.reduce_noise(y=y, sr=SR, stationary=False, prop_decrease=0.3*a+0.2)
        y2 = nr.reduce_noise(y=y1, sr=SR, stationary=True,  prop_decrease=0.2*a+0.1)
        return y2.astype(np.float32)
    except Exception:
        return y.astype(np.float32)

def wpe_dereverb(y: np.ndarray, iters: int = 1, taps: int = 12, delay: int = 3) -> Tuple[np.ndarray, str]:
    try:
        import nara_wpe as wpe
        y2 = y.astype(np.float64)[None, None, :]
        R = wpe.wpe(y2, taps=taps, delay=delay, iterations=iters)
        out = R[0,0,:].astype(np.float32)
        return out, "WPE applied"
    except Exception:
        return y.astype(np.float32), "WPE unavailable"

def leveler(x: np.ndarray, amount: float) -> np.ndarray:
    a=float(np.clip(amount,0.0,1.0))
    if a<=0: return x
    target_rms_db = -28.0 + 12.0*a
    atk_ms = 10.0 - 6.0*a; rel_ms = 320.0 - 200.0*a
    atk=max(1,int(SR*atk_ms/1000.0)); rel=max(1,int(SR*rel_ms/1000.0))
    env=np.zeros_like(x,dtype=np.float32); g=0.0; ax=np.abs(x)+1e-9
    for i,v in enumerate(ax):
        target = 10.0**((target_rms_db/20.0)) / (v+1e-6)
        target = np.clip(target, 0.2, 5.0)
        if target > g:
            g += (target-g)/atk
        else:
            g += (target-g)/rel
        env[i]=g
    y = (x*env).astype(np.float32)
    return _soft_clip(y, 1.05)

# ───────────────── IR apply & background ─────────────────
def convolve_ir(x: np.ndarray, ir_path: Optional[str], mix_percent: float) -> np.ndarray:
    if not ir_path or not os.path.exists(ir_path) or mix_percent <= 0: return x
    mix = np.clip(mix_percent / 100.0, 0.0, 1.0)
    ir,sr=_load_audio(ir_path); ir=_mono_sr(ir,sr,SR)
    if len(ir)<8: return x
    ir=ir/(np.max(np.abs(ir))+1e-9)
    wet=fftconvolve(x, ir, mode="same").astype(np.float32)
    return (x + mix * (wet - x)).astype(np.float32)

def env_follow(x: np.ndarray, atk_ms: float = 10.0, rel_ms: float = 180.0) -> np.ndarray:
    atk=max(1,int(SR*atk_ms/1000.0)); rel=max(1,int(SR*rel_ms/1000.0))
    env=np.zeros_like(x,dtype=np.float32); g=0.0; ax=np.abs(x)+1e-9
    for i,v in enumerate(ax):
        target = v
        if target > g:
            g += (target-g)/atk
        else:
            g += (target-g)/rel
        env[i]=np.clip(g,0.0,1.0)
    return env

def stream_background(y: np.ndarray,
                      bg_path: Optional[str],
                      bg_ir_path: Optional[str],
                      bg_ir_mix_percent: float,
                      bg_gain_db: float,
                      bg_hpf: float, bg_lpf: float,
                      duck_db: float) -> np.ndarray:
    if not bg_path:
        return y
    bed = _decode_any_to_float32(bg_path, SR)
    if bed.size == 0:
        return y
    # Length match (tile or truncate)
    if len(bed) < len(y):
        reps = int(np.ceil(len(y) / len(bed)))
        bed = np.tile(bed, reps)[:len(y)]
    else:
        bed = bed[:len(y)]
    # Optional BG IR (applies to bed only)
    if bg_ir_path:
        bed = convolve_ir(bed, bg_ir_path, float(bg_ir_mix_percent))
    # Headroom + zero-phase toning
    bed *= 0.85
    bed = hpf_lpf(bed, bg_hpf, bg_lpf, zero_phase=True)
    bed = _soft_clip(bed, drive=1.0)
    # Duck vs speech env
    env = env_follow(y)
    duck_lin = 10.0**(float(duck_db)/20.0) if duck_db<0 else 1.0
    g_bg = 10.0**(float(bg_gain_db)/20.0)
    g_duck = duck_lin + (1.0 - duck_lin) * (1.0 - env)
    return (y + g_bg * bed * g_duck).astype(np.float32)

# ───────────────── network/codec artifacts (legacy-compatible) ─────────────────
def apply_dropouts_old(v: np.ndarray, drop_p: float, chunk_ms: float, depth_db: float) -> np.ndarray:
    if drop_p<=0: return v
    w = max(8, int(chunk_ms*SR/1000.0))
    y = v.copy()
    for i in range(0, len(y), w):
        if random.random() < drop_p:
            y[i:i+w] *= 10.0**(float(depth_db)/20.0)
    return y.astype(np.float32)

def apply_stutter_old(v: np.ndarray, amount: float, sr: int = SR) -> np.ndarray:
    if amount<=0: return v
    w = max(16, int(0.03*sr))
    y = v.copy()
    for i in range(0, len(y)-w, w):
        if random.random() < amount:
            y[i:i+w] = np.roll(y[i:i+w], int(w*0.5))
    return y.astype(np.float32)

def apply_jitter_buffering(v: np.ndarray, jitter_intensity: float, buffer_prob: float, sr: int = SR) -> np.ndarray:
    if jitter_intensity<=0 and buffer_prob<=0: return v
    y=v.copy(); n=len(y); i=0
    while i<n-1:
        if random.random() < buffer_prob:
            span = min(int(0.04*sr), n-i-1)
            if span>0:
                y[i:i+span] = y[i]
                i += span
        else:
            i += 1+int(jitter_intensity*5)
    return y.astype(np.float32)

def apply_packet_reordering(v: np.ndarray, reorder_prob: float, sr: int = SR) -> np.ndarray:
    if reorder_prob<=0: return v
    y=v.copy()
    w=max(32, int(0.02*sr))
    chunks=[y[i:i+w] for i in range(0,len(y),w)]
    for i in range(len(chunks)-1):
        if random.random()<reorder_prob:
            chunks[i],chunks[i+1]=chunks[i+1],chunks[i]
    return np.concatenate(chunks).astype(np.float32)

def apply_codec_artifacts(v: np.ndarray, codec_type: str, intensity: float, sr: int = SR) -> np.ndarray:
    if intensity<=0: return v
    y=v.copy()
    if codec_type=="speex":
        y = hpf_lpf(y, 0.0, 3500.0)
    elif codec_type=="gsm":
        y = hpf_lpf(y, 200.0, 3400.0)
    y = (y + np.random.normal(0, 1e-4*intensity*np.max(np.abs(y)+1e-9), y.shape)).astype(np.float32)
    return y

def apply_mic_proximity_effects(v: np.ndarray, mic_proximity: float, mic_type: str, sr: int = SR) -> np.ndarray:
    if mic_proximity<=0: return v
    amt = float(np.clip(mic_proximity, 0.0, 1.0))
    low = hpf_lpf(v, 0.0, 200.0)
    hi = v - low
    return _soft_clip(low*(1.0+0.6*amt)+hi, 1.02)

def apply_mp3_sizzle_old(v: np.ndarray, amount: float) -> np.ndarray:
    if amount<=0: return v
    lo = hpf_lpf(v, 0.0, 4000.0)
    hi = v - lo
    return _soft_clip(lo + hi*(1.0+0.8*amount), 1.02)

def apply_rf_noise_old(y: np.ndarray, amount: float) -> np.ndarray:
    if amount<=0: return y
    n = np.random.normal(0, 1e-3*float(amount)*np.max(np.abs(y)+1e-9), y.shape)
    return _soft_clip(y + n, 1.02)

# ───────────────── phone quality tiers ─────────────────
def apply_phone_quality_tier(y: np.ndarray, tier: str, custom_params: dict = None) -> tuple[np.ndarray, str]:
    tiers = {
        "good_landline": {"bandwidth": (300, 3400), "description": "Clean PSTN Landline"},
        "bad_landline":  {"bandwidth": (300, 3000), "description": "Noisy PSTN Landline"},
        "cordless":      {"bandwidth": (250, 3500), "description": "Analog Cordless Base"},
        "ultra_low":     {"bandwidth": (200, 1800), "description": "2G/3G Poor Signal"},
        "low":           {"bandwidth": (200, 4000), "description": "3G/4G Weak"},
        "standard":      {"bandwidth": (80, 7000),  "description": "Wideband Voice"},
        "high":          {"bandwidth": (20, 20000), "description": "Modern HD Voice"},
        "ultra_high":    {"bandwidth": (20, SR/2),  "description": "FaceTime/WhatsApp (Near-Source Quality)"},
    }
    if custom_params:
        params = custom_params
        desc = "Custom Quality"
    else:
        params = tiers.get(tier, tiers["standard"])
        desc = params.get("description", tier)

    low_f, high_f = params["bandwidth"]
    zero_phase = tier in ("high","ultra_high")
    y = hpf_lpf(y, float(low_f), float(high_f), zero_phase=zero_phase)

    # μ-law band-limited color only for landline family
    if tier in ("good_landline","bad_landline","cordless"):
        mu_amt = {"good_landline":0.20, "bad_landline":0.35, "cordless":0.35}[tier]
        vband = _zphf(y, 300.0, 2400.0)
        y = (y - vband) + apply_mulaw_color(vband, mu_amt, mu=255.0, drive=0.70)
    # Modern tiers: no μ-law

    return y.astype(np.float32), desc

# ───────────────── presets / defaults ─────────────────
PROCESS_AUDIO_PARAM_ORDER = [
    "dereverb_amt", "src_hpf", "src_lpf", "leveler_amt",
    "wpe_strength", "cleanup_mix",
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
    "dereverb_amt": 0.0, "src_hpf": 0.0, "src_lpf": SR/2, "leveler_amt": 0.0, "wpe_strength": 0.0, "cleanup_mix": 1.0,
    "room_ir_file": None, "room_ir_gain_db": 0.0,
    "bg_file": None, "bg_ir_file": None, "bg_ir_gain_db": 0.0, "bg_gain_db": -36.0, "bg_hpf": 40.0, "bg_lpf": 12000.0, "bg_duck_db": -24.0,
    "quality_tier": "standard", "custom_low_freq": 300.0, "custom_high_freq": 3500.0, "custom_compression": 0.0, "custom_noise": 0.0, "custom_dropout_mult": 1.0, "custom_garble_mult": 1.0,
    "bandwidth_mode": "Wideband 80–7000", "opus_bitrate_kbps": 24, "post_mu_grit": 0.0,
    "plc_ms": 40.0, "dropout_prob": 0.08, "dropout_depth_db": -24.0,
    "garble_prob": 0.04, "stutter_amt": 0.02, "jitter_intensity": 0.01, "buffer_prob": 0.01, "reorder_prob": 0.01,
    "codec_type": "speex", "codec_intensity": 0.3, "mic_proximity": 0.0, "mic_type": "dynamic", "mp3_amt": 0.0, "rf_amt": 0.0,
    "handset_ir_file": None, "handset_ir_gain_db": 0.0,
    "traffic_files": None, "traffic_ev_min": 0.0, "traffic_vol_db": -12.0,
    "baby_files": None, "baby_ev_min": 0.0, "baby_vol_db": -12.0,
    "dog_files": None, "dog_ev_min": 0.0, "dog_vol_db": -12.0,
    "normalize_output": True,
}

# ───────────────── event placement ─────────────────
def _expand_files_with_warnings(files: List[str]) -> Tuple[List[str], List[str]]:
    ok=[]; warn=[]
    for p in files or []:
        if not os.path.exists(p):
            warn.append(f"Missing: {p}")
        else:
            ok.append(p)
    return ok, warn

def _random_slice(y: np.ndarray, min_s: float, max_s: float) -> np.ndarray:
    n=len(y); min_n=int(min_s*SR); max_n=int(max_s*SR)
    if n<=min_n: return y[:min_n]
    L=np.random.randint(min_n, min(max_n, n))
    start=np.random.randint(0, max(1, n-L))
    return y[start:start+L]

def place_events(total_len: int, files: List[str], ev_min_seconds: float, vol_db: float) -> np.ndarray:
    if not files: return np.zeros(total_len, dtype=np.float32)
    out = np.zeros(total_len, dtype=np.float32)
    occ = np.zeros(total_len, dtype=np.int32)
    max_overlap = 0.25
    target_level = 10.0**(float(vol_db)/20.0)
    step = max(int(ev_min_seconds*SR), int(1.0*SR))
    for i in range(0, total_len, step):
        if random.random() < 0.8:
            fpath = random.choice(files)
            x, sr = _load_audio(fpath)
            x = _mono_sr(x, sr, SR)
            original_duration = len(x)/SR
            if original_duration > 6.0:
                span = int(2.5*SR)
                if len(x) > span:
                    start = random.randint(0, len(x)-span)
                    s = x[start:start+span]
                else:
                    s = x
            else:
                s = x
            L=len(s)
            placed=False
            for _ in range(12):
                start=np.random.randint(0,max(1,total_len-L))
                overlap=occ[start:start+L].sum()/max(1,L)
                if overlap<=max_overlap:
                    placed=True; break
            if not placed: 
                continue
            end=start+L
            fade=max(4,int(0.004*SR))
            if original_duration >= 3.0:
                fade = max(fade, int(0.15*SR))
            rms = np.sqrt(np.mean(s**2) + 1e-9)
            target_rms = 0.1
            if rms > 0:
                s = s * (target_rms / rms)
            w = fade_window(L, fade)
            s = (s*w).astype(np.float32)
            out[start:end] += target_level * s
            occ[start:end] += 1
    return out.astype(np.float32)

# ───────────────── normalization ─────────────────
def normalize_peak(y: np.ndarray, peak: float = 0.97) -> np.ndarray:
    m = float(np.max(np.abs(y)) or 1.0)
    if m>0:
        y = y * (peak/m)
    return y.astype(np.float32)

def normalize_audio_lufs(y: np.ndarray, target_lufs: float = -18.0) -> np.ndarray:
    cur = rms_db(y)
    diff = target_lufs - cur
    gain = 10.0**(diff/20.0)
    return (y*gain).astype(np.float32)

# ───────────────── main processor ─────────────────
def process_audio(
    mic_file,
    # Source
    dereverb_amt, src_hpf, src_lpf, leveler_amt,
    wpe_strength, cleanup_mix,
    # Room IR (pre)
    room_ir_file, room_ir_gain_db,
    # Background
    bg_file, bg_ir_file, bg_ir_gain_db, bg_gain_db, bg_hpf, bg_lpf, bg_duck_db,
    # Phone quality system
    quality_tier, custom_low_freq, custom_high_freq, custom_compression, custom_noise, custom_dropout_mult, custom_garble_mult,
    # Legacy knobs
    bandwidth_mode, opus_bitrate_kbps, post_mu_grit,
    # Network artifacts
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
    mic_path=_safe_file(mic_file)
    if not mic_path: return None, "No input."
    y,sr=_load_audio(mic_path); y=_mono_sr(y,sr,SR)
    if len(y)<int(0.05*SR): return None,"Input too short."
    if len(y)>30*60*SR: return None,"Input too long (>30m)."

    modern = str(quality_tier) in ("high","ultra_high")

    # Source EQ / cleanup
    y = hpf_lpf(y, float(src_hpf), float(src_lpf), zero_phase=True if modern else False)

    if float(leveler_amt)>0:
        y = leveler(y, float(leveler_amt))

    cleanup_mix = float(np.clip(cleanup_mix, 0.0, 1.0))
    y_base = y.astype(np.float32, copy=True); wpe_note=""
    if (float(wpe_strength)>0 or float(dereverb_amt)>0):
        y_proc = y_base.copy()
        if float(wpe_strength)>0:
            iters = 2 if float(wpe_strength) >= 0.66 else 1
            y_wpe, wpe_msg = wpe_dereverb(y_proc, iters, 12, 3)
            y_proc = (1.0 - float(wpe_strength)) * y_proc + float(wpe_strength) * y_wpe.astype(np.float32)
            if wpe_msg == "WPE applied":
                wpe_note = " · WPE"
        if float(dereverb_amt)>0:
            y_proc = dereverb_strong(y_proc, float(dereverb_amt))
        if modern:
            y = y_base + cleanup_mix * (y_proc - y_base)
        else:
            y = y_proc

    # Room IR with double-guard vs BG IR
    _room_ir = _safe_file(room_ir_file)
    _bg_ir = _safe_file(bg_ir_file)
    same_ir = _same_file(_room_ir, _bg_ir)
    _room_ir_apply = None if same_ir else _room_ir
    ir_guard_note = " · IR:BG only" if same_ir else ""
    y = convolve_ir(y, _room_ir_apply, float(room_ir_gain_db))
    room_ir_name = (os.path.basename(_room_ir) if _room_ir_apply else "none") if not same_ir else "none"

    # Events before phone chain
    xlen=len(y)
    traf_ok,_ = _expand_files_with_warnings(_coerce_paths_list(traffic_files))
    baby_ok,_ = _expand_files_with_warnings(_coerce_paths_list(baby_files))
    dog_ok,_  = _expand_files_with_warnings(_coerce_paths_list(dog_files))
    y += place_events(xlen, traf_ok, float(traffic_ev_min), float(traffic_vol_db))
    y += place_events(xlen, baby_ok,  float(baby_ev_min),  float(baby_vol_db))
    y += place_events(xlen, dog_ok,   float(dog_ev_min),   float(dog_vol_db))

    # Background bed (decoded; supports OGG/WAV/MP3)
    bg_candidates = _coerce_paths_list(bg_file)
    selected_bg = random.choice(bg_candidates) if bg_candidates else None
    y = stream_background(y, _safe_file(selected_bg), _bg_ir, float(bg_ir_gain_db),
                          float(bg_gain_db), float(bg_hpf), float(bg_lpf), float(bg_duck_db))
    if selected_bg and os.path.exists(selected_bg):
        bg_desc = os.path.basename(selected_bg)
    elif bg_candidates:
        bg_desc = f"random({len(bg_candidates)})"
    else:
        bg_desc = "none"

    # Pre-limit combined
    peak = float(np.max(np.abs(y)) or 1.0)
    if peak > 0.707:
        y = (y * (0.707 / peak)).astype(np.float32)

    # Phone quality system
    if str(quality_tier) != "custom":
        y, quality_description = apply_phone_quality_tier(y, str(quality_tier), None)
        codec_status = quality_description
    else:
        custom_params = {
            "bandwidth": (float(custom_low_freq), float(custom_high_freq)),
            "sample_rate_factor": 1.0,
        }
        y, quality_description = apply_phone_quality_tier(y, "custom", custom_params)
        codec_status = f"Custom Quality ({int(custom_low_freq)}-{int(custom_high_freq)}Hz)"

    # Legacy bandwidth clamp: skip for modern tiers
    if not modern:
        if bandwidth_mode=="Narrowband 300–3500":
            y=hpf_lpf(y, 300.0, 3500.0)
        elif bandwidth_mode=="Wideband 80–7000":
            y=hpf_lpf(y, 80.0, 7000.0)

    # Skip handset IR on modern tiers
    if not modern:
        y = convolve_ir(y, _safe_file(handset_ir_file), float(handset_ir_gain_db))

    # Network artifacts (skip digital for landlines)
    landline = str(quality_tier) in ["good_landline", "bad_landline", "cordless"]
    if not landline:
        mult_map = {"ultra_low": (2.0, 1.8, 0.05), "low":(1.4,1.2,0.03), "standard":(1.0,1.0,0.02),
                    "high":(0.5,0.5,0.01), "ultra_high":(0.2,0.2,0.00)}
        dropout_mult, garble_mult, tier_stutter_amt = mult_map.get(str(quality_tier), (1.0,1.0,0.02))
        if str(quality_tier)=="custom":
            dropout_mult = float(custom_dropout_mult)
            garble_mult  = float(custom_garble_mult)
            tier_stutter_amt = float(stutter_amt)
        scaled_dropout_prob = float(dropout_prob) * dropout_mult
        y = apply_dropouts_old(y, min(scaled_dropout_prob, 1.0), float(plc_ms), float(dropout_depth_db))
        final_stutter_amt = tier_stutter_amt if tier_stutter_amt > 0 else float(stutter_amt)
        y = apply_stutter_old(y, final_stutter_amt, SR)
        y = apply_jitter_buffering(y, float(jitter_intensity), float(buffer_prob), SR)
        y = apply_packet_reordering(y, float(reorder_prob), SR)
        y = apply_codec_artifacts(y, str(codec_type), float(codec_intensity), SR)
        y = apply_mic_proximity_effects(y, float(mic_proximity), str(mic_type), SR)
        y = apply_mp3_sizzle_old(y, float(mp3_amt))
        y = apply_rf_noise_old(y, float(rf_amt))
    else:
        # Light analog-like quirks (kept minimal)
        if str(quality_tier) == "bad_landline":
            y = apply_jitter_buffering(y, min(float(jitter_intensity) * 0.5, 0.01), 0.0, SR)
        elif str(quality_tier) == "cordless":
            y = apply_dropouts_old(y, min(float(dropout_prob) * 0.5, 0.15), float(plc_ms), float(dropout_depth_db))
            y = apply_stutter_old(y, min(float(stutter_amt) * 0.5, 0.04), SR)
            y = apply_rf_noise_old(y, float(rf_amt))

    # Safety & normalize
    if np.max(np.abs(y)) > 1.0:
        y = _soft_clip(y, drive=1.1)

    if bool(normalize_output):
        y = normalize_audio_lufs(y, -18.0)
        norm_note = " · Normalized"
    else:
        y = normalize_peak(y, 0.97)
        norm_note = ""

    status = f"OK · Codec: {codec_status}{wpe_note} · BG:{bg_desc} · IR:{room_ir_name}{ir_guard_note}{norm_note}"
    return _save_wav_tmp(y), status
