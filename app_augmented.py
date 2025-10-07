# app.py — Master FX (real DSP), phone-last, intermittent artifacts
# Chain: In → Dereverb → (optional) IR → BG(+duck→BG EQ) → Tone → Phone EQ/Codec/Bitrate → Dropouts/Stutter/Robot/Warp → Mix → Normalize

import os, json, random, hashlib, tempfile, copy
from typing import Dict, Any, Optional, List, Tuple

import gradio as gr
import numpy as np
import soundfile as sf
import scipy.signal as sig
from scipy.signal import fftconvolve

# Optional dereverb (stationary spectral subtraction)
try:
    import noisereduce as nr
    HAVE_NR = True
except Exception:
    HAVE_NR = False

SR = 16000
PRESETS_FILE = "presets.json"
MAX_IR_SEC = 2.0
BG_DIR = "assets/backgrounds"
IR_DIR = "assets/irs"

# ---------------- I/O helpers ----------------
def load_wav(path: str) -> Tuple[np.ndarray, int]:
    y, sr = sf.read(path, dtype="float32", always_2d=False)
    return y, sr

def mono_16k(y: np.ndarray, sr: int) -> np.ndarray:
    if y.ndim > 1: y = y.mean(axis=1)
    if sr != SR:   y = sig.resample(y, int(len(y) * SR / sr))
    return y.astype(np.float32)

def save_tmp(y: np.ndarray) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    sf.write(tmp.name, y, SR)
    return tmp.name

def normalize(y: np.ndarray, peak=0.95) -> np.ndarray:
    m = float(np.max(np.abs(y)) or 0.0)
    return y if m < 1e-9 else (y / m * peak).astype(np.float32)

# ---------------- Blocks ----------------
def dereverb(y: np.ndarray, amt: float) -> np.ndarray:
    if amt <= 0 or not HAVE_NR: return y
    # prop_decrease ~ mix of suppression
    return nr.reduce_noise(y=y, sr=SR, stationary=False, prop_decrease=float(np.clip(amt,0,1))).astype(np.float32)

def convolve_ir(y: np.ndarray, ir_path: Optional[str], wet: float) -> np.ndarray:
    if not ir_path or not os.path.exists(ir_path) or wet <= 0: return y
    ir, sr = load_wav(ir_path); ir = mono_16k(ir, sr)
    if len(ir) > int(MAX_IR_SEC*SR): ir = ir[:int(MAX_IR_SEC*SR)]
    ir /= (np.max(np.abs(ir)) + 1e-9)
    wet_sig = fftconvolve(y, ir, mode="full")[:len(y)]
    mix = float(np.clip(wet, 0, 1))
    return ((1-mix)*y + mix*wet_sig).astype(np.float32)

def bg_pick(paths: List[str], preset: str, seed: int) -> Optional[str]:
    candidates = [p for p in paths if p and os.path.exists(p)]
    if not candidates: return None
    h = hashlib.sha1(f"{preset}:{seed}".encode()).digest()
    idx = int.from_bytes(h[:2], "big") % len(candidates)
    return candidates[idx]

def bg_random_start_loop(bg: np.ndarray, out_len: int) -> np.ndarray:
    if len(bg) == 0: return bg
    start = random.randint(0, len(bg)-1)
    seq = np.concatenate([bg[start:], bg[:start]])
    if len(seq) < out_len: seq = np.tile(seq, int(np.ceil(out_len/len(seq))))
    return seq[:out_len]

def bg_filter(y: np.ndarray, lp_hz: float, hp_hz: float) -> np.ndarray:
    out = y
    if hp_hz and hp_hz > 20:
        out = sig.sosfilt(sig.butter(2, hp_hz/(SR/2), btype="high", output="sos"), out)
    if lp_hz and lp_hz < SR/2:
        out = sig.sosfilt(sig.butter(2, lp_hz/(SR/2), btype="low", output="sos"), out)
    return out.astype(np.float32)

def mix_background(y: np.ndarray, bg: Optional[np.ndarray], gain_db: float, duck_db: float) -> np.ndarray:
    if bg is None or gain_db <= -120: return y
    bg = bg[:len(y)] if len(bg) >= len(y) else np.pad(bg, (0, len(y)-len(bg)))
    env = np.abs(sig.lfilter([1], [1, -0.995], np.abs(y)))
    env /= (np.max(env) + 1e-9)
    duck = 10 ** (float(duck_db)/20.0)  # negative dB
    bg_duck = bg * (duck + (1-duck)*(1-env))
    return (y + (10**(gain_db/20.0))*bg_duck).astype(np.float32)

def compand(y: np.ndarray, knee_db: float, ratio: float, makeup_db: float) -> np.ndarray:
    if ratio <= 1 and knee_db <= 0: return y
    thr = 10 ** (-max(knee_db,0)/20.0); mk = 10 ** (makeup_db/20.0)
    out = y.copy(); m = np.abs(out) > thr
    out[m] = np.sign(out[m]) * (thr + (np.abs(out[m])-thr)/max(1.0, ratio))
    return (out*mk).astype(np.float32)

def softclip(y: np.ndarray, amt: float) -> np.ndarray:
    if amt <= 0: return y
    drive = 1 + 3*amt
    return (np.tanh(y*drive)/drive).astype(np.float32)

def bandlimit(y: np.ndarray, lo: float, hi: float) -> np.ndarray:
    out = y
    if lo and lo>20: out = sig.sosfilt(sig.butter(4, lo/(SR/2), btype="high", output="sos"), out)
    if hi and hi<SR/2: out = sig.sosfilt(sig.butter(4, hi/(SR/2), btype="low", output="sos"), out)
    return out.astype(np.float32)

# --- Real bitrate crush: decimation (SR) + bit depth ---
def bitrate_crush(y: np.ndarray, kbps: float, depth_bits: int = 10) -> np.ndarray:
    if kbps <= 0: return y
    # map kbps→effective bandwidth; crude but audible
    eff = float(np.interp(kbps, [6,12,24,48,64], [1800,3000,5000,9000,14000]))
    dec = max(1, int(round(SR/max(800.0, eff))))
    y_ds = y[::dec]
    y_us = sig.resample(y_ds, len(y))
    bits = int(np.clip(depth_bits, 6, 12))
    q = 2**(bits-1) - 1
    return (np.round(np.clip(y_us,-1,1)*q)/q).astype(np.float32)

def codec_mu_law(y: np.ndarray, intensity: float) -> np.ndarray:
    """Intensity 0..1 crossfades dry-bandlimit vs µ-law companded inside same band."""
    intensity = float(np.clip(intensity, 0, 1))
    if intensity == 0: return y
    mu = 255.0
    comp = np.sign(y) * np.log1p(mu*np.abs(y))/np.log1p(mu)
    return ((1-intensity)*y + intensity*comp).astype(np.float32)

def dropouts(y: np.ndarray, per_min: float, avg_ms: float, jitter_ms: float, depth_db: float) -> np.ndarray:
    if per_min <= 0: return y
    out = y.copy(); n = len(y)
    count = int(max(0, per_min*(n/SR)/60.0))
    depth = 10 ** (depth_db/20.0)  # negative
    for _ in range(count):
        dur = max(15.0, np.random.normal(avg_ms, jitter_ms))
        L = int(dur*SR/1000.0)
        s = np.random.randint(0, max(1, n-L))
        out[s:s+L] *= depth
    return out

# --- REAL intermittent garble events ---
def stutter_events(y: np.ndarray, events_min: float, amt: float) -> np.ndarray:
    if events_min<=0 or amt<=0: return y
    out = y.copy(); n = len(y)
    ev = int(max(0, events_min*(n/SR)/60.0))
    for _ in range(ev):
        seg = int(np.random.uniform(30,120)*(0.6+0.8*amt)*SR/1000.0)
        if seg<8: continue
        start = np.random.randint(0, max(1,n-seg))
        reps = 1 + int(round(2*amt))  # 1..3 repeats
        tile = np.tile(out[start:start+seg], reps)
        out[start:start+len(tile)] = tile[:max(0, min(len(tile), n-start))]
    return out

def robot_events(y: np.ndarray, events_min: float, amt: float) -> np.ndarray:
    if events_min<=0 or amt<=0: return y
    out = y.copy(); n=len(y); t = np.arange(n)/SR
    ev = int(max(0, events_min*(n/SR)/60.0))
    for _ in range(ev):
        seg = int(np.random.uniform(80,220)*SR/1000.0)
        s = np.random.randint(0, max(1,n-seg))
        f = np.random.uniform(70,160)
        lfo = np.sin(2*np.pi*f*t[s:s+seg]).astype(np.float32)
        wet = out[s:s+seg]*(0.5+0.5*lfo)
        mix = np.clip(amt,0,1)
        out[s:s+seg]=(1-mix)*out[s:s+seg]+mix*wet
    return out

def warp_events(y: np.ndarray, events_min: float, amt: float) -> np.ndarray:
    if events_min<=0 or amt<=0: return y
    out = y.copy(); n=len(y)
    ev = int(max(0, events_min*(n/SR)/60.0))
    for _ in range(ev):
        seg = int(np.random.uniform(60,180)*SR/1000.0)
        s = np.random.randint(0, max(1,n-seg))
        factor = 1.0 + np.random.uniform(-0.25,0.25)*amt  # Increased from ±9% to ±25% for more audible warping
        src = out[s:s+seg]
        warped = sig.resample(src, max(1,int(len(src)*factor)))
        warped = sig.resample(warped, len(src))
        out[s:s+seg]=warped
    return out

# ---------------- Spec / UI ----------------
def default_spec() -> Dict[str, Any]:
    return {
        "presets":[
            {
                "name":"Street Sounds",
                "chain":{
                    "mix.fx":0.8,
                    "dereverb.strength":0.0,
                    "ir.enabled":False,
                    "ir.wet":0.0,
                    "ir.path":"",
                    "bg.paths":[
                        f"{BG_DIR}/street_A.wav",
                        f"{BG_DIR}/street_B.wav",
                        f"{BG_DIR}/street_C.wav",
                        f"{BG_DIR}/street_D.wav",
                        f"{BG_DIR}/street_E.wav"
                    ],
                    "bg.random_start":True,
                    "bg.gain_db":-22.0,
                    "bg.duck_db":-10.0,
                    "bg.lpf_hz":6000.0,
                    "bg.hpf_hz":80.0,

                    "tone.knee_db":5.0,"tone.ratio":3.0,"tone.makeup_db":0.5,"tone.softclip":0.06,

                    "phone.low_hz":250.0,"phone.high_hz":3600.0,
                    "phone.bitrate_kbps":0.0,"phone.codec_intensity":0.4,

                    "drop.rate_min":10.0,"drop.avg_ms":160.0,"drop.jitter_ms":80.0,"drop.depth_db":-32.0,
                    "stutter.events_min":6.0,"stutter.amount":0.6,
                    "robot.events_min":4.0,"robot.amount":0.5,
                    "warp.events_min":8.0,"warp.amount":0.45
                }
            },
            {
                "name":"Cellphone Spotty",
                "chain":{
                    "mix.fx":0.9,
                    "dereverb.strength":0.0,
                    "ir.enabled":True,
                    "ir.wet":0.35,
                    "ir.path":f"{IR_DIR}/bathroom.wav",

                    "bg.paths":[],
                    "bg.random_start":True,
                    "bg.gain_db":-120.0,
                    "bg.duck_db":-10.0,
                    "bg.lpf_hz":8000.0,
                    "bg.hpf_hz":50.0,

                    "tone.knee_db":6.0,"tone.ratio":3.5,"tone.makeup_db":0.0,"tone.softclip":0.08,

                    "phone.low_hz":300.0,"phone.high_hz":3400.0,
                    "phone.bitrate_kbps":12.0,"phone.codec_intensity":1.0,

                    "drop.rate_min":18.0,"drop.avg_ms":200.0,"drop.jitter_ms":120.0,"drop.depth_db":-28.0,
                    "stutter.events_min":10.0,"stutter.amount":0.7,
                    "robot.events_min":6.0,"robot.amount":0.6,
                    "warp.events_min":14.0,"warp.amount":0.6
                }
            },
            {
                "name":"Dry / Bypass",
                "chain":{
                    "mix.fx":0.0,
                    "dereverb.strength":0.0,
                    "ir.enabled":False,"ir.wet":0.0,"ir.path":"",
                    "bg.paths":[],"bg.random_start":True,"bg.gain_db":-120.0,"bg.duck_db":-10.0,"bg.lpf_hz":8000.0,"bg.hpf_hz":50.0,
                    "tone.knee_db":0.0,"tone.ratio":1.0,"tone.makeup_db":0.0,"tone.softclip":0.0,
                    "phone.low_hz":50.0,"phone.high_hz":8000.0,"phone.bitrate_kbps":0.0,"phone.codec_intensity":0.0,
                    "drop.rate_min":0.0,"drop.avg_ms":160.0,"drop.jitter_ms":0.0,"drop.depth_db":-24.0,
                    "stutter.events_min":0.0,"stutter.amount":0.0,"robot.events_min":0.0,"robot.amount":0.0,"warp.events_min":0.0,"warp.amount":0.0
                }
            }
        ],
        "controls":[
            {"type":"slider","label":"Effect Mix","path":"mix.fx","min":0,"max":1,"step":0.05,"value":0.8},

            {"type":"slider","label":"Dereverb Strength","path":"dereverb.strength","min":0,"max":1,"step":0.05,"value":0.0},
            {"type":"checkbox","label":"Use IR","path":"ir.enabled","value":False},
            {"type":"slider","label":"IR Wet","path":"ir.wet","min":0,"max":1,"step":0.05,"value":0.3},

            {"type":"slider","label":"Ambience Level (dB)","path":"bg.gain_db","min":-60,"max":-10,"step":0.5,"value":-22.0,"visible_in":["Street Sounds"]},
            {"type":"slider","label":"Ducking (dB)","path":"bg.duck_db","min":-24,"max":0,"step":0.5,"value":-10.0,"visible_in":["Street Sounds"]},
            {"type":"slider","label":"BG Low-Pass (Hz)","path":"bg.lpf_hz","min":500,"max":8000,"step":50,"value":6000.0,"visible_in":["Street Sounds"]},
            {"type":"slider","label":"BG High-Pass (Hz)","path":"bg.hpf_hz","min":20,"max":500,"step":10,"value":80.0,"visible_in":["Street Sounds"]},

            {"type":"slider","label":"Compand Knee (dB)","path":"tone.knee_db","min":0,"max":18,"step":1,"value":5},
            {"type":"slider","label":"Compand Ratio","path":"tone.ratio","min":1,"max":8,"step":0.1,"value":3},
            {"type":"slider","label":"Makeup (dB)","path":"tone.makeup_db","min":0,"max":6,"step":0.1,"value":0.5},
            {"type":"slider","label":"Softclip Amount","path":"tone.softclip","min":0,"max":0.5,"step":0.01,"value":0.06},

            {"type":"slider","label":"Phone Low Hz","path":"phone.low_hz","min":50,"max":600,"step":10,"value":250},
            {"type":"slider","label":"Phone High Hz","path":"phone.high_hz","min":2500,"max":4000,"step":50,"value":3600},
            {"type":"slider","label":"Bitrate (kbps)","path":"phone.bitrate_kbps","min":0,"max":64,"step":1,"value":0},
            {"type":"slider","label":"Codec Intensity","path":"phone.codec_intensity","min":0,"max":1,"step":0.05,"value":0.4},

            {"type":"slider","label":"Dropouts / min","path":"drop.rate_min","min":0,"max":80,"step":0.1,"value":10},
            {"type":"slider","label":"Dropout Length (ms)","path":"drop.avg_ms","min":15,"max":400,"step":5,"value":160},
            {"type":"slider","label":"Dropout Jitter (±ms)","path":"drop.jitter_ms","min":0,"max":200,"step":5,"value":80},
            {"type":"slider","label":"Dropout Depth (dB)","path":"drop.depth_db","min":-60,"max":-5,"step":1,"value":-32},

            {"type":"slider","label":"Stutter events/min","path":"stutter.events_min","min":0,"max":60,"step":0.5,"value":6},
            {"type":"slider","label":"Stutter Amount","path":"stutter.amount","min":0,"max":1,"step":0.05,"value":0.6},

            {"type":"slider","label":"Robotize events/min","path":"robot.events_min","min":0,"max":60,"step":0.5,"value":4},
            {"type":"slider","label":"Robotize Amount","path":"robot.amount","min":0,"max":1,"step":0.05,"value":0.5},

            {"type":"slider","label":"Warp events/min","path":"warp.events_min","min":0,"max":60,"step":0.5,"value":8},
            {"type":"slider","label":"Warp Amount","path":"warp.amount","min":0,"max":1,"step":0.05,"value":0.45}
        ]
    }

def load_spec() -> Dict[str, Any]:
    try:
        with open(PRESETS_FILE,"r",encoding="utf-8") as f:
            spec = json.load(f)
    except Exception:
        spec = default_spec()
    return spec

# ---------------- Process (phone-last + artifacts after phone) ----------------
def process_pipeline(wav_path: str, ir_upload, bg_upload, chain: Dict[str, Any], preset_name: str, seed: int) -> str:
    random.seed(seed or None)
    np.random.seed(seed if seed else None)
    y, sr = load_wav(wav_path); y = mono_16k(y, sr)

    # 1) dereverb
    y = dereverb(y, float(chain.get("dereverb",{}).get("strength",0.0)))

    # 2) IR (upload overrides preset path)
    ir_path = ir_upload.name if ir_upload else chain.get("ir",{}).get("path","")
    if chain.get("ir",{}).get("enabled",False):
        y = convolve_ir(y, ir_path, float(chain.get("ir",{}).get("wet",0.3)))

    # 3) Background bed (deterministic pick + random start) → BG EQ → duck → mix
    bg_paths = chain.get("bg",{}).get("paths",[])
    bg_path  = bg_upload.name if bg_upload else bg_pick(bg_paths, preset_name, seed)
    bg_sig = None
    if bg_path and os.path.exists(bg_path):
        bg_raw, srb = load_wav(bg_path); bg_raw = mono_16k(bg_raw, srb)
        if chain.get("bg",{}).get("random_start",True):
            bg_raw = bg_random_start_loop(bg_raw, len(y))
        bg_sig = bg_filter(bg_raw, float(chain["bg"].get("lpf_hz",8000.0)), float(chain["bg"].get("hpf_hz",50.0)))
    y = mix_background(y, bg_sig, float(chain["bg"].get("gain_db",-120.0)), float(chain["bg"].get("duck_db",-10.0)))

    # 4) Tone
    y = compand(y, float(chain["tone"].get("knee_db",0.0)), float(chain["tone"].get("ratio",1.0)), float(chain["tone"].get("makeup_db",0.0)))
    y = softclip(y, float(chain["tone"].get("softclip",0.0)))

    # 5) PHONE coloration (last) → keep a baseline colored track
    y = bandlimit(y, float(chain["phone"].get("low_hz",300.0)), float(chain["phone"].get("high_hz",3400.0)))
    kbps = float(chain["phone"].get("bitrate_kbps",0.0))
    if kbps>0: y = bitrate_crush(y, kbps, depth_bits=10)
    y = codec_mu_law(y, float(chain["phone"].get("codec_intensity",0.0)))
    baseline = y.copy()

    # 6) Artifacts AFTER phone
    d = chain.get("drop",{})
    y = dropouts(y, float(d.get("rate_min",0.0)), float(d.get("avg_ms",160.0)), float(d.get("jitter_ms",0.0)), float(d.get("depth_db",-28.0)))
    s = chain.get("stutter",{}); y = stutter_events(y, float(s.get("events_min",0.0)), float(s.get("amount",0.0)))
    r = chain.get("robot",{});   y = robot_events(y,   float(r.get("events_min",0.0)), float(r.get("amount",0.0)))
    w = chain.get("warp",{});    y = warp_events(y,    float(w.get("events_min",0.0)), float(w.get("amount",0.0)))

    # 7) Mix artifact vs baseline (both colored identically), normalize
    mix = float(np.clip(chain.get("mix",{}).get("fx",1.0),0,1))
    out = (1.0-mix)*baseline + mix*y
    return save_tmp(normalize(out,0.95))

# ---------------- UI ----------------
def build_controls(spec: Dict[str, Any]):
    comps, meta = [], []
    for c in spec.get("controls", []):
        t = c.get("type"); p = c.get("path"); lbl = c.get("label", p)
        if not p: continue
        if t=="slider":
            comp = gr.Slider(minimum=float(c.get("min",0)), maximum=float(c.get("max",1)), step=float(c.get("step",0.01)), value=float(c.get("value",0)), label=lbl)
        elif t=="checkbox":
            comp = gr.Checkbox(value=bool(c.get("value",False)), label=lbl)
        else:
            comp = gr.Number(value=float(c.get("value",0)), label=lbl)
        comps.append(comp); meta.append(c)
    return comps, meta

def visible_updates(preset_name: str, ctl_meta, ctl_comps):
    outs=[]
    for m,_ in zip(ctl_meta, ctl_comps):
        vis = m.get("visible_in")
        outs.append(gr.update(visible=True if vis is None else (preset_name in vis)))
    return outs

def create_app():
    spec = load_spec()
    preset_names = [p["name"] for p in spec["presets"]]
    default = preset_names[0]

    with gr.Blocks(title="Voice Lab FX — Master", theme=gr.themes.Soft()) as demo:
        gr.Markdown("## Voice Lab FX — Master (real garble, bitrate, codec intensity, street beds, bathroom IR)")

        with gr.Row():
            with gr.Column(scale=1):
                audio_in = gr.Audio(label="Input Audio", type="filepath")
                preset   = gr.Dropdown(choices=preset_names, value=default, label="Preset")
                with gr.Accordion("Optional Uploads", open=False):
                    ir_file = gr.File(label="Device / Reverb IR (WAV)", file_types=[".wav",".WAV"])
                    bg_file = gr.File(label="Background / Ambience (WAV)", file_types=[".wav",".WAV"])
                seed = gr.Number(label="Seed (optional)", value=0, precision=0)
                reload_btn = gr.Button("🔄 Reload presets.json")

            with gr.Column(scale=1):
                gr.Markdown("### Controls")
                ctl_comps, ctl_meta = build_controls(spec)

        out_audio = gr.Audio(label="Processed Output")
        status    = gr.Textbox(label="Status", interactive=False)
        run_btn   = gr.Button("⚙️ Process Audio", variant="primary")

        def chain_for(name: str) -> Dict[str, Any]:
            s = load_spec()
            for p in s["presets"]:
                if p["name"] == name:
                    return p["chain"].copy()  # Simple copy instead of JSON round-trip
            return default_spec()["presets"][0]["chain"]

        def apply_overrides(chain: Dict[str, Any], values: List[Any]) -> Dict[str, Any]:
            out = copy.deepcopy(chain)  # More efficient than JSON round-trip
            for spec, val in zip(ctl_meta, values):
                # set deep path
                parts = spec["path"].split(".")
                cur = out
                for k in parts[:-1]:
                    cur = cur.setdefault(k, {})
                cur[parts[-1]] = val
            return out

        def do_process(audio_path, preset_name, ir, bg, seed_val, *vals):
            if not audio_path: return None, "Upload audio first."
            try:
                rnd = int(seed_val or 0)
            except: rnd = 0
            random.seed(rnd); np.random.seed(rnd)
            chain = apply_overrides(chain_for(preset_name), list(vals))
            try:
                res = process_pipeline(audio_path, ir, bg, chain, preset_name, rnd)
            except Exception as e:
                return None, f"❌ {e}"
            return res, f"✅ {preset_name}"

        def do_reload():
            return "Presets reloaded."

        run_btn.click(do_process, inputs=[audio_in, preset, ir_file, bg_file, seed]+ctl_comps, outputs=[out_audio, status])
        preset.change(lambda n: visible_updates(n, ctl_meta, ctl_comps), inputs=[preset], outputs=ctl_comps)
        reload_btn.click(do_reload, outputs=[status])
        demo.load(lambda n: visible_updates(n, ctl_meta, ctl_comps), inputs=[preset], outputs=ctl_comps)

    return demo

if __name__ == "__main__":
    demo = create_app()
    demo.queue(default_concurrency_limit=4).launch(server_name="0.0.0.0", server_port=7860)
