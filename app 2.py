# VoiceLab FX — Editor Build (Purple UI, Safe Presets, Legacy Hooks)

from __future__ import annotations
import os, json, importlib.util, tempfile, hashlib
from typing import Any, Dict, Optional, Tuple

import gradio as gr
import numpy as np
import soundfile as sf
import scipy.signal as sig
from scipy.signal import fftconvolve

SR = 16000
PRESETS_PATH = "presets.json"

# ----------------------------
# Optional deps
# ----------------------------
try:
    import noisereduce as nr
    HAVE_NR = True
except Exception:
    HAVE_NR = False

# ----------------------------
# Legacy import (exact old DSP)
# ----------------------------
def _import_legacy():
    for name in ["legacy_old_fx.py", "legacy_fx.py", "app-2.py"]:
        if os.path.exists(name):
            spec = importlib.util.spec_from_file_location("legacy_old_fx", name)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return {
                    "garble_seg": getattr(mod, "legacy_garble_segment", None),
                    "apply_stutter": getattr(mod, "apply_stutter", None),
                    "apply_robotize": getattr(mod, "apply_robotize", None),
                    "dropouts_fx": getattr(mod, "dropouts_fx", None),
                }
    return {}
LEGACY = _import_legacy()

# ----------------------------
# Utils
# ----------------------------
def _hash_to_int(*parts: Any) -> int:
    data = "::".join(str(p) for p in parts).encode()
    return int.from_bytes(hashlib.sha1(data).digest()[:4], "big", signed=False)

def _rng_for(label: str, seed: int, index: int) -> np.random.RandomState:
    val = _hash_to_int(label, seed, index) % (2**32)
    return np.random.RandomState(val)

def _load_wav(path: str) -> Tuple[np.ndarray, int]:
    y, sr = sf.read(path, dtype="float32", always_2d=False)
    return y, sr

def _mono16k(y: np.ndarray, sr: int) -> np.ndarray:
    if y.ndim > 1: y = y.mean(axis=1)
    if sr != SR:
        y = sig.resample(y, int(len(y) * SR / sr))
    return y.astype(np.float32)

def _save_tmp(y: np.ndarray, sr: int = SR) -> str:
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    sf.write(f.name, y.astype(np.float32), sr)
    return f.name

def normalize_peak(x: np.ndarray, peak: float = 0.97) -> np.ndarray:
    m = float(np.max(np.abs(x)) or 0.0)
    if m < 1e-9: return x
    return (x / m * peak).astype(np.float32)

# ----------------------------
# Presets (safe I/O)
# ----------------------------
def _normalize_presets(p):
    if not isinstance(p, dict): return {"presets": {}}
    prs = p.get("presets")
    return {"presets": prs if isinstance(prs, dict) else {}}

def safe_load_presets():
    try:
        if not os.path.exists(PRESETS_PATH): return {"presets": {}}
        with open(PRESETS_PATH, "r") as f:
            data = json.load(f)
        return _normalize_presets(data)
    except Exception:
        return {"presets": {}}

def save_presets(presets):
    data = _normalize_presets(presets)
    with open(PRESETS_PATH, "w") as f:
        json.dump(data, f, indent=2)

# ----------------------------
# DSP blocks
# ----------------------------
def dereverb_fx(x: np.ndarray, strength: float) -> np.ndarray:
    s = float(np.clip(strength, 0.0, 1.0))
    if s <= 0: return x
    if HAVE_NR:
        return nr.reduce_noise(y=x, sr=SR, stationary=False, prop_decrease=s).astype(np.float32)
    # STFT reduction fallback
    f, t, Z = sig.stft(x, SR, nperseg=512, noverlap=384, window="hann", padded=False)
    mag = np.abs(Z)
    noise = np.percentile(mag, 10, axis=1, keepdims=True)
    alpha = 1.4 + 1.6 * s
    floor = 0.05 + 0.10 * s
    mag_hat = np.maximum(mag - alpha * noise, floor * mag)
    Z_hat = mag_hat * np.exp(1j * np.angle(Z))
    _, y = sig.istft(Z_hat, SR, nperseg=512, noverlap=384, window="hann")
    if len(y) < len(x): y = np.pad(y, (0, len(x)-len(y)))
    return y[:len(x)].astype(np.float32)

def band_fx(x: np.ndarray, low_hz: float = 0.0, high_hz: float = 20000.0) -> np.ndarray:
    y = x
    if low_hz and low_hz > 20:
        y = sig.sosfilt(sig.butter(4, low_hz/(SR/2), btype="high", output="sos"), y)
    if high_hz and high_hz < SR/2:
        y = sig.sosfilt(sig.butter(4, high_hz/(SR/2), btype="low", output="sos"), y)
    return y.astype(np.float32)

def convolve_ir(x: np.ndarray, ir_path: Optional[str], gain_db: float = 0.0) -> np.ndarray:
    if not ir_path or not os.path.exists(ir_path): return x
    ir, sr = _load_wav(ir_path)
    ir = _mono16k(ir, sr)
    if len(ir) < 8: return x
    wet = fftconvolve(x, ir)[:len(x)].astype(np.float32)
    g = 10 ** (gain_db / 20.0)
    return (wet * g).astype(np.float32)

def bitrate_crush_fx(x: np.ndarray, kbps: float) -> np.ndarray:
    if not kbps or kbps <= 0: return x
    eff_sr = float(np.interp(kbps, [6,12,24,48,64], [2000,4000,8000,12000,16000]))
    decim = max(1, int(round(SR / max(800.0, eff_sr))))
    down = x[::decim]
    up = sig.resample(down, len(x))
    bits = int(np.clip(np.interp(kbps, [6,12,24,48,64], [6,8,10,12,12]), 6, 12))
    q = 2**(bits-1) - 1
    return (np.round(np.clip(up, -1, 1) * q) / q).astype(np.float32)

def mu_law_fx(x: np.ndarray, intensity: float) -> np.ndarray:
    a = float(np.clip(intensity, 0.0, 1.0))
    if a <= 0: return x
    mu = 255.0
    comp = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    return ((1.0 - a) * x + a * comp).astype(np.float32)

def jitter_timewarp_fx(x: np.ndarray, amount: float, rng: np.random.RandomState) -> np.ndarray:
    a = float(np.clip(amount, 0.0, 1.0))
    if a <= 0: return x
    max_dev = 0.05 * a
    n = len(x)
    noise = rng.standard_normal(n // 160 + 2)
    ctrl = sig.sosfilt(sig.butter(2, 0.15, output="sos"), noise)
    ctrl = np.interp(np.linspace(0, len(ctrl)-1, n), np.arange(len(ctrl)), ctrl)
    rate = 1.0 + max_dev * (ctrl / (np.max(np.abs(ctrl)) + 1e-9))
    t = np.cumsum(rate); t = (t / t[-1]) * (n - 1)
    i0 = np.floor(t).astype(int); i1 = np.clip(i0 + 1, 0, n - 1)
    frac = (t - i0).astype(np.float32)
    return ((1.0 - frac) * x[i0] + frac * x[i1]).astype(np.float32)

def _fade_window(n: int, fade: int) -> np.ndarray:
    if fade <= 0 or fade * 2 >= n: return np.ones(n, dtype=np.float32)
    w = np.ones(n, dtype=np.float32); ramp = np.linspace(0.0,1.0,fade,dtype=np.float32)
    w[:fade] = ramp; w[-fade:] = ramp[::-1]; return w

def dropouts_oldfeel(x: np.ndarray, rate_per_min: float, avg_ms: float, jitter_ms: float,
                     depth_db: float, rng: np.random.RandomState) -> np.ndarray:
    if rate_per_min <= 0: return x
    y = x.copy(); n = len(x)
    events = int(max(0, rate_per_min * (n / SR) / 60.0))
    base_depth = 10 ** (depth_db / 20.0)
    for _ in range(events):
        dur_ms = max(20.0, rng.normal(avg_ms, jitter_ms))
        dur = max(8, int(dur_ms * SR / 1000.0))
        start = rng.randint(0, max(1, n - dur))
        seg = y[start:start+dur]
        fade = max(4, int(0.004 * SR))
        w = _fade_window(len(seg), fade)
        local = np.clip(base_depth * rng.uniform(0.9, 1.1), 0.0, 1.0)
        y[start:start+dur] = seg * (local + (1.0 - local) * (1.0 - w))
    return y

# Aggressive one-slider Leveler (RMS target + soft knee + lookahead brickwall)
def leveler(x: np.ndarray, amount: float) -> np.ndarray:
    a = float(np.clip(amount, 0.0, 1.0))
    if a <= 0: return x
    target_rms_db = -26.0 + 12.0 * a   # -26 .. -14 dBFS
    win = max(1, int(0.040 * SR))
    pad = np.pad(x, (win, win), mode="reflect")
    k = np.ones(win, dtype=np.float32) / win
    rms = np.sqrt(sig.convolve(pad**2, k, mode="same")[win:-win] + 1e-9)
    target_lin = 10 ** (target_rms_db / 20.0)
    static_gain = target_lin / (rms + 1e-9)
    alpha = 0.15 + 0.35 * (1.0 - a)
    smoothed = np.empty_like(static_gain); g = static_gain[0]
    for i in range(len(static_gain)):
        g = alpha * g + (1.0 - alpha) * static_gain[i]
        smoothed[i] = g
    y = x * smoothed
    knee_db = 6.0 + 6.0 * a
    thr = 10 ** ((-0.5) / 20.0); knee = 10 ** ((-0.5 - knee_db) / 20.0)
    over = np.abs(y) > knee
    if np.any(over):
        sign = np.sign(y[over]); mag = np.abs(y[over])
        mag = knee + (mag - knee) / (2.0 + 6.0 * a)  # soft knee squeeze
        y[over] = sign * np.minimum(mag, thr)
    look = max(1, int(0.003 * SR))  # 3 ms
    if look > 1: y = np.concatenate([y[look:], y[-look:]])
    return np.clip(y, -0.985, 0.985).astype(np.float32)

# ----------------------------
# Processing graph (authentic)
# Mic domain → Room IR (pre-codec) → Background mix (with LPF/HPF) → Leveler
# → Phone frame: bandlimit + bitrate + μ-law
# → Network/PLC: jitter → dropouts → garble → stutter → robot
# → Handset IR (post-codec) → normalize
# ----------------------------
def process_audio(
    wav,
    seed: int,
    preset_name: str,
    # Source
    dereverb_amt: float, src_hpf: float, src_lpf: float, leveler_amt: float,
    # Room IR (pre-codec)
    room_ir_path, room_ir_gain_db: float,
    # Background
    bg_path, bg_gain_db: float, bg_duck_db: float, bg_hpf: float, bg_lpf: float,
    # Phone frame
    nbwb_mode: str, bitrate_kbps: float, codec_intensity: float,
    # Network
    jitter_amt: float, drop_rate: float, drop_len_ms: float, drop_jitter_ms: float, drop_depth_db: float,
    garble_prob: float, garble_strength: float,
    stutter_events_min: float, stutter_amount: float,
    robot_amount_micro: float,
    # Handset IR (post-codec)
    handset_ir_path, handset_ir_gain_db: float,
    # Use legacy exact DSP?
    use_legacy: bool,
):
    if wav is None: return None, "No input."
    y, sr = _load_wav(wav); y = _mono16k(y, sr)

    presets = safe_load_presets()
    P = presets["presets"].get(preset_name, {})

    # Mic domain
    y = dereverb_fx(y, P.get("dereverb_amt", dereverb_amt))
    y = band_fx(y, P.get("src_hpf", src_hpf), P.get("src_lpf", src_lpf))

    # Room IR pre-codec
    room_path = P.get("room_ir_path", room_ir_path)
    y = convolve_ir(y, room_path, P.get("room_ir_gain_db", room_ir_gain_db))

    # Background pre-codec (muffled party-in-next-room, etc.)
    bg_sel = P.get("bg_path", bg_path)
    if bg_sel and os.path.exists(bg_sel):
        bgw, bsr = _load_wav(bg_sel)
        bg = _mono16k(bgw, bsr)
        bg = band_fx(bg, P.get("bg_hpf", bg_hpf), P.get("bg_lpf", bg_lpf))
        # sidechain ducking
        env = np.abs(sig.lfilter([1],[1,-0.995], np.abs(y))); env = env/(np.max(env)+1e-9)
        duck = 10 ** (float(P.get("bg_duck_db", bg_duck_db)) / 20.0)  # negative dB
        bg_ducked = bg * (duck + (1 - duck) * (1 - env))
        g = 10 ** (float(P.get("bg_gain_db", bg_gain_db)) / 20.0)
        y = (y + g * bg_ducked).astype(np.float32)

    # One-slider leveler
    y = leveler(y, P.get("leveler_amt", leveler_amt))

    # Phone frame
    nbwb = P.get("nbwb_mode", nbwb_mode)
    if nbwb == "Narrowband 300–3500":
        y = band_fx(y, 300.0, 3500.0)
    else:
        y = band_fx(y, 80.0, 7000.0)
    y = bitrate_crush_fx(y, P.get("bitrate_kbps", bitrate_kbps))
    y = mu_law_fx(y, P.get("codec_intensity", codec_intensity))

    # Network / PLC
    y = jitter_timewarp_fx(y, P.get("jitter_amt", jitter_amt), _rng_for("jitter", seed, 1))

    # Dropouts
    if use_legacy and LEGACY.get("dropouts_fx"):
        y = LEGACY["dropouts_fx"](
            y,
            P.get("drop_rate", drop_rate),
            P.get("drop_len_ms", drop_len_ms),
            P.get("drop_jitter_ms", drop_jitter_ms),
            P.get("drop_depth_db", drop_depth_db),
            _hash_to_int("drop", seed, 2),
        )
    else:
        y = dropouts_oldfeel(
            y,
            P.get("drop_rate", drop_rate),
            P.get("drop_len_ms", drop_len_ms),
            P.get("drop_jitter_ms", drop_jitter_ms),
            P.get("drop_depth_db", drop_depth_db),
            _rng_for("drop", seed, 2),
        )

    # Garble (exact old per-segment if available)
    if use_legacy:
        fn = LEGACY.get("garble_seg")
        if fn is None:
            return None, "Legacy garble not found. Upload legacy_old_fx.py with legacy_garble_segment()."
        seg = max(1, int(0.050 * SR))
        prob = float(P.get("garble_prob", garble_prob))
        strength = float(P.get("garble_strength", garble_strength))
        for idx, start in enumerate(range(0, len(y), seg)):
            if _rng_for("garble", seed, idx).random_sample() >= prob: continue
            end = min(start + seg, len(y))
            y[start:end] = fn(y[start:end], strength, seed, idx)

    # Stutter (legacy exact)
    if use_legacy:
        fn = LEGACY.get("apply_stutter")
        if fn is None:
            return None, "Legacy stutter not found. Upload legacy_old_fx.py with apply_stutter()."
        y = fn(
            y,
            P.get("stutter_events_min", stutter_events_min),
            P.get("stutter_amount", stutter_amount),
            _hash_to_int("stutter", seed, 3),
        )

    # Robotization (legacy exact; expect 0..0.01 range)
    if use_legacy:
        fn = LEGACY.get("apply_robotize")
        if fn is None:
            return None, "Legacy robotize not found. Upload legacy_old_fx.py with apply_robotize()."
        y = fn(y, float(P.get("robot_amount_micro", robot_amount_micro)), _hash_to_int("robot", seed, 4))

    # Handset/Speaker IR post-codec
    handset_path = P.get("handset_ir_path", handset_ir_path)
    y = convolve_ir(y, handset_path, P.get("handset_ir_gain_db", handset_ir_gain_db))

    y = normalize_peak(y, 0.97)
    return _save_tmp(y, SR), "OK"

# ----------------------------
# UI
# ----------------------------
def create_app():
    theme = gr.themes.Soft(primary_hue="purple", secondary_hue="violet")
    with gr.Blocks(title="VoiceLab FX — Editor", theme=theme) as demo:
        gr.Markdown("## VoiceLab FX — Editor (Purple UI)")

        # Top row
        with gr.Row():
            audio_in = gr.Audio(label="Input WAV", type="filepath")
            seed = gr.Slider(0, 2**31-1, value=1337, step=1, label="Seed")
            use_legacy = gr.Checkbox(value=True, label="Use EXACT legacy DSP if available")

        # Preset select / manage
        with gr.Row():
            presets_state = gr.State(safe_load_presets())
            names = sorted(presets_state.value["presets"].keys())
            preset = gr.Dropdown(choices=(names or ["Default"]),
                                 value=(names[0] if names else "Default"),
                                 label="Preset")

            new_preset_name = gr.Textbox(label="New preset name")
            btn_add = gr.Button("Add/Overwrite Preset")
            btn_reload = gr.Button("Reload presets.json")
            btn_save = gr.Button("Save presets.json")

        # Source
        with gr.Tab("Source"):
            dereverb = gr.Slider(0.0, 1.0, value=0.0, step=0.05, label="Reduce Reverb")
            src_hpf = gr.Slider(0.0, 300.0, value=0.0, step=10.0, label="Source HPF (Hz)")
            src_lpf = gr.Slider(2000.0, 20000.0, value=20000.0, step=100.0, label="Source LPF (Hz)")
            leveler_amt = gr.Slider(0.0, 1.0, value=0.6, step=0.01, label="Leveler Amount")

        # Room IR (pre-codec)
        with gr.Tab("Room IR (pre-codec)"):
            room_ir = gr.File(label="Room IR WAV", file_count="single", file_types=[".wav"])
            room_ir_gain = gr.Slider(-24.0, 24.0, value=0.0, step=0.5, label="Room IR Gain (dB)")

        # Background
        with gr.Tab("Background"):
            bg_file = gr.File(label="Background WAV (Street/Party/etc.)", file_count="single", file_types=[".wav"])
            bg_gain_db = gr.Slider(-60.0, 24.0, value=-14.0, step=0.5, label="Background Volume (dB)")
            bg_duck_db = gr.Slider(-60.0, 0.0, value=-12.0, step=1.0, label="Background Ducking (dB)")
            bg_hpf = gr.Slider(0.0, 400.0, value=0.0, step=10.0, label="Background HPF (Hz)")
            bg_lpf = gr.Slider(1000.0, 8000.0, value=1800.0, step=50.0, label="Background LPF (Hz)  (muffle for 'party next room')")

        # Phone frame
        with gr.Tab("Phone Color"):
            nbwb = gr.Radio(choices=["Narrowband 300–3500", "Wideband 80–7000"],
                            value="Narrowband 300–3500", label="Bandwidth")
            bitrate = gr.Slider(0.0, 64.0, value=24.0, step=1.0, label="Bitrate Crush (kbps)")
            codec_int = gr.Slider(0.0, 1.0, value=0.35, step=0.01, label="Codec Intensity (μ-law)")

        # Network
        with gr.Tab("Network"):
            jitter_amt = gr.Slider(0.0, 1.0, value=0.12, step=0.01, label="PLC Warble Amount")
            with gr.Row():
                drop_rate = gr.Slider(0.0, 60.0, value=6.0, step=0.5, label="Dropouts/min")
                drop_len = gr.Slider(40.0, 400.0, value=180.0, step=5.0, label="Dropout Avg (ms)")
                drop_jit = gr.Slider(0.0, 200.0, value=120.0, step=5.0, label="Dropout Jitter (ms)")
                drop_depth = gr.Slider(-60.0, 0.0, value=-24.0, step=1.0, label="Dropout Depth (dB)")
            with gr.Row():
                garble_prob = gr.Slider(0.0, 1.0, value=0.35, step=0.01, label="Garble Probability")
                garble_strength = gr.Slider(0.0, 1.0, value=0.7, step=0.01, label="Garble Strength")
            with gr.Row():
                stut_ev = gr.Slider(0.0, 60.0, value=6.0, step=0.5, label="Stutter events/min")
                stut_amt = gr.Slider(0.0, 1.0, value=0.5, step=0.05, label="Stutter Amount")
                robot_amt = gr.Slider(0.0, 0.01, value=0.0, step=0.001, label="Robotization (micro)")

        # Handset IR (post-codec)
        with gr.Tab("Handset IR (post-codec)"):
            handset_ir = gr.File(label="Handset/Speaker IR WAV", file_count="single", file_types=[".wav"])
            handset_ir_gain = gr.Slider(-24.0, 24.0, value=0.0, step=0.5, label="Handset IR Gain (dB)")

        process = gr.Button("Process", variant="primary")
        out_audio = gr.Audio(label="Processed Output", type="filepath")
        status = gr.Textbox(label="Status", interactive=False)

        # ------- Helpers for file inputs -> path -------
        def _safe_path(fileobj):
            if isinstance(fileobj, str):
                return fileobj if fileobj and os.path.exists(fileobj) else None
            if isinstance(fileobj, dict) and fileobj.get("name"):
                return fileobj["name"]
            return None

        # ------- Process wiring -------
        def do_process(wav, seed_v, preset_v, derev, hpf_v, lpf_v, lvl,
                       room_ir_v, room_gain_v, bg_v, bg_gain_v, bg_duck_v, bg_hpf_v, bg_lpf_v,
                       nbwb_v, br_v, codec_v,
                       jit_v, dr_v, dl_v, dj_v, dd_v,
                       gp_v, gs_v, sev_v, sam_v, rob_v,
                       handset_ir_v, handset_gain_v, use_legacy_v):
            room_path = _safe_path(room_ir_v)
            bg_path = _safe_path(bg_v)
            handset_path = _safe_path(handset_ir_v)
            return process_audio(
                wav, int(seed_v), preset_v,
                float(derev), float(hpf_v), float(lpf_v), float(lvl),
                room_path, float(room_gain_v),
                bg_path, float(bg_gain_v), float(bg_duck_v), float(bg_hpf_v), float(bg_lpf_v),
                nbwb_v, float(br_v), float(codec_v),
                float(jit_v), float(dr_v), float(dl_v), float(dj_v), float(dd_v),
                float(gp_v), float(gs_v), float(sev_v), float(sam_v), float(rob_v),
                handset_path, float(handset_gain_v),
                bool(use_legacy_v),
            )

        process.click(
            do_process,
            inputs=[
                audio_in, seed, preset,
                dereverb, src_hpf, src_lpf, leveler_amt,
                room_ir, room_ir_gain, bg_file, bg_gain_db, bg_duck_db, bg_hpf, bg_lpf,
                nbwb, bitrate, codec_int,
                jitter_amt, drop_rate, drop_len, drop_jit, drop_depth,
                garble_prob, garble_strength, stut_ev, stut_amt, robot_amt,
                handset_ir, handset_ir_gain, use_legacy
            ],
            outputs=[out_audio, status]
        )

        # ------- Preset editor -------
        gr.Markdown("### Preset Editor (save to presets.json)")
        with gr.Row():
            ed_room_ir = gr.Textbox(label="Room IR path", placeholder="path/to/room_ir.wav")
            ed_room_gain = gr.Number(label="Room IR Gain dB", value=0.0)
            ed_bg_path = gr.Textbox(label="Background path", placeholder="path/to/background.wav")
            ed_bg_gain = gr.Number(label="BG Gain dB", value=-14.0)
            ed_bg_duck = gr.Number(label="BG Duck dB", value=-12.0)
        with gr.Row():
            ed_bg_hpf = gr.Number(label="BG HPF Hz", value=0.0)
            ed_bg_lpf = gr.Number(label="BG LPF Hz", value=1800.0)
            ed_nbwb = gr.Dropdown(choices=["Narrowband 300–3500", "Wideband 80–7000"],
                                  value="Narrowband 300–3500", label="Bandwidth")
            ed_bitrate = gr.Number(label="Bitrate kbps", value=24.0)
            ed_codec = gr.Number(label="Codec intensity", value=0.35)
        with gr.Row():
            ed_dereverb = gr.Number(label="Dereverb", value=0.0)
            ed_src_hpf = gr.Number(label="Source HPF Hz", value=0.0)
            ed_src_lpf = gr.Number(label="Source LPF Hz", value=20000.0)
            ed_leveler = gr.Number(label="Leveler 0..1", value=0.6)
        with gr.Row():
            ed_jitter = gr.Number(label="Jitter 0..1", value=0.12)
            ed_drop_rate = gr.Number(label="Drop/min", value=6.0)
            ed_drop_len = gr.Number(label="Drop avg ms", value=180.0)
            ed_drop_jit = gr.Number(label="Drop jitter ms", value=120.0)
            ed_drop_depth = gr.Number(label="Drop depth dB", value=-24.0)
        with gr.Row():
            ed_garble_p = gr.Number(label="Garble Prob 0..1", value=0.35)
            ed_garble_s = gr.Number(label="Garble Strength 0..1", value=0.7)
            ed_stut_ev = gr.Number(label="Stutter ev/min", value=6.0)
            ed_stut_amt = gr.Number(label="Stutter amount 0..1", value=0.5)
            ed_robot = gr.Number(label="Robot micro 0..0.01", value=0.0)
            ed_handset_ir = gr.Textbox(label="Handset IR path", placeholder="path/to/handset_ir.wav")
            ed_handset_gain = gr.Number(label="Handset IR Gain dB", value=0.0)

        def add_overwrite_preset(presets, name, *vals):
            p = _normalize_presets(presets)
            name = (name or "Untitled").strip()
            cfg = {
                "room_ir_path": vals[0], "room_ir_gain_db": vals[1],
                "bg_path": vals[2], "bg_gain_db": vals[3], "bg_duck_db": vals[4],
                "bg_hpf": vals[5], "bg_lpf": vals[6],
                "nbwb_mode": vals[7], "bitrate_kbps": vals[8], "codec_intensity": vals[9],
                "dereverb_amt": vals[10], "src_hpf": vals[11], "src_lpf": vals[12], "leveler_amt": vals[13],
                "jitter_amt": vals[14], "drop_rate": vals[15], "drop_len_ms": vals[16],
                "drop_jitter_ms": vals[17], "drop_depth_db": vals[18],
                "garble_prob": vals[19], "garble_strength": vals[20],
                "stutter_events_min": vals[21], "stutter_amount": vals[22],
                "robot_amount_micro": vals[23],
                "handset_ir_path": vals[24], "handset_ir_gain_db": vals[25],
            }
            p["presets"][name] = cfg
            save_presets(p)
            names = sorted(p["presets"].keys())
            return p, gr.Dropdown(choices=names, value=name), f"Saved preset '{name}'."

        btn_add.click(
            add_overwrite_preset,
            inputs=[presets_state, new_preset_name,
                    ed_room_ir, ed_room_gain, ed_bg_path, ed_bg_gain, ed_bg_duck,
                    ed_bg_hpf, ed_bg_lpf, ed_nbwb, ed_bitrate, ed_codec,
                    ed_dereverb, ed_src_hpf, ed_src_lpf, ed_leveler,
                    ed_jitter, ed_drop_rate, ed_drop_len, ed_drop_jit, ed_drop_depth,
                    ed_garble_p, ed_garble_s, ed_stut_ev, ed_stut_amt, ed_robot,
                    ed_handset_ir, ed_handset_gain],
            outputs=[presets_state, preset, status]
        )

        def do_reload():
            p = safe_load_presets()
            names = sorted(p["presets"].keys()) or ["Default"]
            return p, gr.Dropdown(choices=names, value=names[0]), "Presets reloaded."

        btn_reload.click(do_reload, outputs=[presets_state, preset, status])

        def do_save(presets):
            save_presets(presets)
            p = safe_load_presets()
            names = sorted(p["presets"].keys()) or ["Default"]
            return gr.Dropdown(choices=names, value=names[0]), "presets.json saved."

        btn_save.click(do_save, inputs=[presets_state], outputs=[preset, status])

    return demo

# ----------------------------
# Launcher
# ----------------------------
if __name__ == "__main__":
    demo = create_app()
    demo.queue(default_concurrency_limit=4).launch(
        server_name="0.0.0.0",
        server_port=7860,
        # set True if you want a public link:
        # share=True
    )
