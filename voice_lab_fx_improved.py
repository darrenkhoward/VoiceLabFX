import copy
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence
import gradio as gr
import numpy as np
import soundfile as sf
import scipy.signal as sig
import os

# Audio processing constants
SR = 16000
AMB_WAV = "assets/city_trimmed.wav"
STATIC_WAV = "assets/static.wav"
RUMBLE_WAV = "assets/rumble.wav"

# Load presets
PRESETS_PATH = Path(__file__).resolve().parent / "presets.json"

def load_presets() -> Dict[str, Dict[str, Any]]:
    if PRESETS_PATH.exists():
        data = json.loads(PRESETS_PATH.read_text())
        presets = data.get("presets", [])
        return {preset["name"]: preset for preset in presets}
    else:
        # Fallback presets if file doesn't exist
        return {
            "Clean": {
                "name": "Clean",
                "chain": {
                    "device_ir": {"mix": 0.0},
                    "bandlimit_hz": [300, 8000],
                    "compand": {"in_knee": 3, "ratio": 2.0, "makeup_db": 0, "attack_ms": 10, "release_ms": 250},
                    "codec": {"telephone": False},
                    "distortion": {"softclip": 0.0},
                    "dropouts": {"rate_per_min": 0.0, "avg_ms": 100, "jitter_ms": 50, "depth_db": -40},
                    "garble_prob": 0.0,
                    "ambience": {"target_lufs": -35, "duck_on_voice_db": -15, "attack_ms": 100, "release_ms": 300}
                }
            },
            "Radio Static": {
                "name": "Radio Static", 
                "chain": {
                    "device_ir": {"mix": 0.8},
                    "bandlimit_hz": [400, 3400],
                    "compand": {"in_knee": 6, "ratio": 4.0, "makeup_db": 2, "attack_ms": 5, "release_ms": 150},
                    "codec": {"telephone": True},
                    "distortion": {"softclip": 0.2},
                    "dropouts": {"rate_per_min": 2.0, "avg_ms": 120, "jitter_ms": 80, "depth_db": -25},
                    "garble_prob": 0.1,
                    "ambience": {"target_lufs": -28, "duck_on_voice_db": -8, "attack_ms": 60, "release_ms": 250}
                }
            },
            "Helicopter": {
                "name": "Helicopter",
                "chain": {
                    "device_ir": {"mix": 1.0},
                    "bandlimit_hz": [350, 2800],
                    "compand": {"in_knee": 8, "ratio": 6.0, "makeup_db": 3, "attack_ms": 3, "release_ms": 100},
                    "codec": {"telephone": True},
                    "distortion": {"softclip": 0.15},
                    "dropouts": {"rate_per_min": 1.5, "avg_ms": 160, "jitter_ms": 120, "depth_db": -30},
                    "garble_prob": 0.05,
                    "ambience": {"target_lufs": -22, "duck_on_voice_db": -6, "attack_ms": 40, "release_ms": 200}
                }
            }
        }

PRESET_MAP = load_presets()
if not PRESET_MAP:
    raise RuntimeError("No presets found. Check presets.json or use fallback presets.")

INITIAL_PRESET = next(iter(PRESET_MAP))

# Audio processing functions
def load_wav(path, sr=SR):
    x, s = sf.read(path)
    if x.ndim > 1: 
        x = x.mean(1)
    if s != sr: 
        x = sig.resample(x, int(len(x)*sr/s))
    return x.astype(np.float32)

def save_wav(arr, sr=SR):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    sf.write(tmp.name, arr, sr)
    return tmp.name

def dropout_fx(x, rate_per_min=0.0, avg_ms=160, jitter_ms=80, depth_db=-35):
    if rate_per_min <= 0:
        return x
    
    x = x.copy()
    duration_sec = len(x) / SR
    num_dropouts = int(rate_per_min * duration_sec / 60)
    
    for _ in range(num_dropouts):
        start_idx = np.random.randint(0, len(x))
        dropout_ms = max(20, np.random.normal(avg_ms, jitter_ms))
        dropout_samples = int(dropout_ms * SR / 1000)
        end_idx = min(start_idx + dropout_samples, len(x))
        
        # Apply dropout as gain reduction, not complete silence
        dropout_gain = 10 ** (depth_db / 20)
        x[start_idx:end_idx] *= dropout_gain
    
    return x

def bitcrush_fx(x, bits=16):
    if bits >= 16: 
        return x
    return np.round(x * (2**bits)) / (2**bits)

def garble_fx(x, prob=0.0):
    if prob <= 0: 
        return x
    
    x = x.copy()
    # Apply garbling to random segments
    segment_samples = int(0.1 * SR)  # 100ms segments
    for i in range(0, len(x), segment_samples):
        if np.random.random() < prob:
            end_i = min(i + segment_samples, len(x))
            noise = np.random.normal(0, 0.1 * np.std(x[i:end_i]), end_i - i)
            x[i:end_i] = np.clip(x[i:end_i] + noise, -1, 1)
    
    return x

def compand_fx(x, in_knee=6, ratio=3.0, makeup_db=0, attack_ms=10, release_ms=250):
    threshold = 10 ** (-in_knee / 20)
    makeup_gain = 10 ** (makeup_db / 20)
    
    # Simple compressor
    y = x.copy()
    mask = np.abs(y) > threshold
    y[mask] = np.sign(y[mask]) * (threshold + (np.abs(y[mask]) - threshold) / ratio)
    y *= makeup_gain
    
    return y

def bandlimit_fx(x, low_hz=300, high_hz=3400):
    if low_hz > 50:
        b, a = sig.butter(4, low_hz / (SR/2), btype='high')
        x = sig.lfilter(b, a, x)
    
    if high_hz < SR // 2:
        b, a = sig.butter(4, high_hz / (SR/2), btype='low')
        x = sig.lfilter(b, a, x)
    
    return x

def softclip_fx(x, amount=0.1):
    if amount <= 0:
        return x
    
    # Soft clipping distortion
    drive = 1 + amount * 5
    x_driven = x * drive
    x_clipped = np.tanh(x_driven) / drive
    return x_clipped

def ambience_fx(length, target_lufs=-28, amb_files=None):
    if amb_files and len(amb_files) > 0:
        # Try to load ambience file
        amb_file = np.random.choice(amb_files) if isinstance(amb_files, list) else amb_files
        if isinstance(amb_file, str) and os.path.exists(amb_file):
            try:
                amb = load_wav(amb_file, SR)
                if len(amb) < length:
                    amb = np.tile(amb, int(np.ceil(length/len(amb))))
                amb = amb[:length]
                
                # Normalize to target LUFS (simplified)
                target_rms = 10 ** (target_lufs / 20)
                current_rms = np.sqrt(np.mean(amb ** 2))
                if current_rms > 0:
                    amb = amb * (target_rms / current_rms)
                
                return amb
            except:
                pass
    
    # Fallback: generate synthetic ambience
    noise = np.random.normal(0, 0.01, length)
    # Color the noise to sound more like city ambience
    b, a = sig.butter(2, [200, 2000], btype='band', fs=SR)
    colored_noise = sig.lfilter(b, a, noise)
    
    # Normalize to target level
    target_rms = 10 ** (target_lufs / 20)
    current_rms = np.sqrt(np.mean(colored_noise ** 2))
    if current_rms > 0:
        colored_noise = colored_noise * (target_rms / current_rms)
    
    return colored_noise

def duck_ambience(ambience, voice, duck_db=-10, attack_ms=60, release_ms=250):
    if duck_db >= 0:
        return ambience
    
    # Simple ducking based on voice envelope
    env = np.abs(sig.hilbert(voice))
    env = env / (env.max() + 1e-9)
    
    # Apply attack/release (simplified)
    duck_gain = 10 ** (duck_db / 20)
    ducking_factor = 1 - env * (1 - duck_gain)
    
    return ambience * ducking_factor

# Control definitions
CONTROL_DEFS: List[Dict[str, Any]] = [
    {
        "id": "device_ir_mix",
        "path": ["device_ir", "mix"],
        "kind": "slider",
        "label": "Device IR Mix",
        "info": "Blend between dry voice and IR processed voice.",
        "minimum": 0.0,
        "maximum": 1.0,
        "step": 0.01,
        "default": 1.0,
        "section": "core",
    },
    {
        "id": "bandlimit_low",
        "path": ["bandlimit_hz", 0],
        "kind": "slider",
        "label": "Bandlimit Low (Hz)",
        "info": "High-pass cutoff to emulate call bandwidth.",
        "minimum": 50,
        "maximum": 1000,
        "step": 10,
        "default": 300,
        "section": "core",
    },
    {
        "id": "bandlimit_high",
        "path": ["bandlimit_hz", 1],
        "kind": "slider",
        "label": "Bandlimit High (Hz)",
        "info": "Low-pass cutoff to emulate call bandwidth.",
        "minimum": 2000,
        "maximum": 8000,
        "step": 50,
        "default": 3400,
        "section": "core",
    },
    {
        "id": "compand_in_knee",
        "path": ["compand", "in_knee"],
        "kind": "slider",
        "label": "Compander Knee (dB)",
        "minimum": 0,
        "maximum": 18,
        "step": 0.5,
        "default": 6,
        "section": "core",
    },
    {
        "id": "compand_ratio",
        "path": ["compand", "ratio"],
        "kind": "slider",
        "label": "Compander Ratio",
        "minimum": 1.0,
        "maximum": 10.0,
        "step": 0.1,
        "default": 3.0,
        "section": "core",
    },
    {
        "id": "compand_makeup",
        "path": ["compand", "makeup_db"],
        "kind": "slider",
        "label": "Makeup Gain (dB)",
        "minimum": -6.0,
        "maximum": 6.0,
        "step": 0.1,
        "default": 0.0,
        "section": "core",
    },
    {
        "id": "compand_attack",
        "path": ["compand", "attack_ms"],
        "kind": "slider",
        "label": "Compander Attack (ms)",
        "minimum": 1,
        "maximum": 200,
        "step": 1,
        "default": 10,
        "section": "core",
    },
    {
        "id": "compand_release",
        "path": ["compand", "release_ms"],
        "kind": "slider",
        "label": "Compander Release (ms)",
        "minimum": 50,
        "maximum": 800,
        "step": 5,
        "default": 250,
        "section": "core",
    },
    {
        "id": "codec_telephone",
        "path": ["codec", "telephone"],
        "kind": "checkbox",
        "label": "Apply Telephone Codec",
        "default": True,
        "section": "core",
    },
    {
        "id": "distortion_softclip",
        "path": ["distortion", "softclip"],
        "kind": "slider",
        "label": "Soft Clip Amount",
        "minimum": 0.0,
        "maximum": 1.0,
        "step": 0.01,
        "default": 0.1,
        "section": "distortion",
    },
    {
        "id": "dropouts_rate",
        "path": ["dropouts", "rate_per_min"],
        "kind": "slider",
        "label": "Dropouts Per Minute",
        "minimum": 0.0,
        "maximum": 12.0,
        "step": 0.1,
        "default": 1.0,
        "section": "distortion",
    },
    {
        "id": "dropouts_avg",
        "path": ["dropouts", "avg_ms"],
        "kind": "slider",
        "label": "Dropout Length (ms)",
        "minimum": 40,
        "maximum": 400,
        "step": 5,
        "default": 160,
        "section": "distortion",
    },
    {
        "id": "dropouts_jitter",
        "path": ["dropouts", "jitter_ms"],
        "kind": "slider",
        "label": "Dropout Jitter (ms)",
        "minimum": 0,
        "maximum": 200,
        "step": 5,
        "default": 80,
        "section": "distortion",
    },
    {
        "id": "dropouts_depth",
        "path": ["dropouts", "depth_db"],
        "kind": "slider",
        "label": "Dropout Depth (dB)",
        "minimum": -60,
        "maximum": -5,
        "step": 1,
        "default": -35,
        "section": "distortion",
    },
    {
        "id": "garble_prob",
        "path": ["garble_prob"],
        "kind": "slider",
        "label": "Garble Probability",
        "minimum": 0.0,
        "maximum": 1.0,
        "step": 0.01,
        "default": 0.0,
        "section": "distortion",
    },
    {
        "id": "ambience_target_lufs",
        "path": ["ambience", "target_lufs"],
        "kind": "slider",
        "label": "Ambience Level (LUFS)",
        "minimum": -45,
        "maximum": -10,
        "step": 0.5,
        "default": -28,
        "section": "ambience",
    },
    {
        "id": "ambience_duck",
        "path": ["ambience", "duck_on_voice_db"],
        "kind": "slider",
        "label": "Ducking Amount (dB)",
        "minimum": -20,
        "maximum": 0,
        "step": 0.5,
        "default": -10,
        "section": "ambience",
    },
    {
        "id": "ambience_attack",
        "path": ["ambience", "attack_ms"],
        "kind": "slider",
        "label": "Ambience Duck Attack (ms)",
        "minimum": 10,
        "maximum": 400,
        "step": 5,
        "default": 60,
        "section": "ambience",
    },
    {
        "id": "ambience_release",
        "path": ["ambience", "release_ms"],
        "kind": "slider",
        "label": "Ambience Duck Release (ms)",
        "minimum": 50,
        "maximum": 1000,
        "step": 10,
        "default": 250,
        "section": "ambience",
    },
]

SECTION_ORDER = [
    ("core", "🔧 Core Processing"),
    ("distortion", "🔥 Distortion & Dropouts"),
    ("ambience", "🌆 Ambience & Ducking"),
]

def get_nested(source: Any, path: Sequence[Any], default: Any) -> Any:
    current = source
    for key in path:
        if isinstance(key, int):
            if isinstance(current, list) and len(current) > key:
                current = current[key]
            else:
                return default
        else:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
    return current

def set_nested(target: Any, path: Sequence[Any], value: Any) -> None:
    current = target
    for idx, key in enumerate(path):
        last = idx == len(path) - 1
        if last:
            if isinstance(key, int):
                if not isinstance(current, list):
                    raise TypeError("Indexed path expects list container")
                while len(current) <= key:
                    current.append(0)
                current[key] = value
            else:
                if not isinstance(current, dict):
                    raise TypeError("Mapping path expects dict container")
                current[key] = value
            continue

        next_key = path[idx + 1]
        if isinstance(key, int):
            if not isinstance(current, list):
                raise TypeError("Indexed path expects list container")
            while len(current) <= key:
                current.append({} if isinstance(next_key, str) else [])
            current = current[key]
        else:
            if not isinstance(current, dict):
                raise TypeError("Mapping path expects dict container")
            if key not in current or not isinstance(current[key], (dict, list)):
                current[key] = {} if isinstance(next_key, str) else []
            current = current[key]

def get_control_values(preset_name: str) -> List[Any]:
    preset = PRESET_MAP[preset_name]
    chain = preset.get("chain", {})
    values: List[Any] = []
    for control in CONTROL_DEFS:
        value = get_nested(chain, control["path"], control.get("default"))
        if control["kind"] == "checkbox":
            value = bool(value)
        values.append(value)
    return values

def build_chain(preset_name: str, values: List[Any]) -> Dict[str, Any]:
    base_chain = copy.deepcopy(PRESET_MAP[preset_name].get("chain", {}))
    chain = base_chain
    for control, value in zip(CONTROL_DEFS, values):
        set_nested(chain, control["path"], value)
    return chain

def format_preset_summary(preset_name: str) -> str:
    preset = PRESET_MAP[preset_name]
    chain = preset.get("chain", {})
    lines = [f"### Preset: {preset_name}"]
    
    # Show key parameters
    ambience = chain.get("ambience", {})
    dropouts = chain.get("dropouts", {})
    bandlimit = chain.get("bandlimit_hz", [300, 3400])
    
    if dropouts.get("rate_per_min", 0) > 0:
        lines.append(f"**Dropouts:** {dropouts.get('rate_per_min')} per min")
    
    lines.append(f"**Bandwidth:** {bandlimit[0]}-{bandlimit[1]} Hz")
    
    if ambience.get("target_lufs", -35) > -35:
        lines.append(f"**Ambience:** {ambience.get('target_lufs')} LUFS")
    
    return "\n\n".join(lines)

def process_audio_local(voice_path: str, preset_name: str, seed: Any, *control_values: Any):
    if not voice_path:
        return None, "⚠️ Upload an audio file first."

    try:
        # Load audio
        voice = load_wav(voice_path, sr=SR)
        
        # Build processing chain from controls
        chain = build_chain(preset_name, list(control_values))
        
        # Apply processing in order
        processed = voice.copy()
        
        # 1. Bandlimiting
        bandlimit = chain.get("bandlimit_hz", [300, 3400])
        processed = bandlimit_fx(processed, bandlimit[0], bandlimit[1])
        
        # 2. Compander
        compand = chain.get("compand", {})
        processed = compand_fx(
            processed,
            compand.get("in_knee", 6),
            compand.get("ratio", 3.0),
            compand.get("makeup_db", 0),
            compand.get("attack_ms", 10),
            compand.get("release_ms", 250)
        )
        
        # 3. Distortion
        distortion = chain.get("distortion", {})
        processed = softclip_fx(processed, distortion.get("softclip", 0.0))
        
        # 4. Dropouts
        dropouts = chain.get("dropouts", {})
        processed = dropout_fx(
            processed,
            dropouts.get("rate_per_min", 0.0),
            dropouts.get("avg_ms", 160),
            dropouts.get("jitter_ms", 80),
            dropouts.get("depth_db", -35)
        )
        
        # 5. Garbling
        garble_prob = chain.get("garble_prob", 0.0)
        processed = garble_fx(processed, garble_prob)
        
        # 6. Add ambience
        ambience_config = chain.get("ambience", {})
        ambience_files = ambience_config.get("files", [])
        
        # Try to find ambience files
        potential_files = []
        for amb_file in [AMB_WAV, "assets/ambience/city.wav", "assets/ambience/helicopter.wav"]:
            if os.path.exists(amb_file):
                potential_files.append(amb_file)
        
        if potential_files:
            ambience_files = potential_files
        
        ambience = ambience_fx(
            len(processed), 
            ambience_config.get("target_lufs", -35),
            ambience_files if ambience_files else None
        )
        
        # Apply ducking
        ambience = duck_ambience(
            ambience, 
            processed,
            ambience_config.get("duck_on_voice_db", -10),
            ambience_config.get("attack_ms", 60),
            ambience_config.get("release_ms", 250)
        )
        
        # Mix ambience with processed voice
        mix = processed + ambience
        
        # Apply device IR mix (simulate radio/telephone response)
        device_ir_mix = chain.get("device_ir", {}).get("mix", 0.0)
        if device_ir_mix > 0:
            # Simple telephone-like filtering
            b, a = sig.butter(2, [400, 3000], btype='band', fs=SR)
            ir_processed = sig.lfilter(b, a, mix)
            mix = mix * (1 - device_ir_mix) + ir_processed * device_ir_mix
        
        # Normalize output
        if np.max(np.abs(mix)) > 0:
            mix = mix / np.max(np.abs(mix)) * 0.95
        
        output_path = save_wav(mix, SR)
        
        # Create status message
        status_parts = ["✅ Processing complete!"]
        if dropouts.get("rate_per_min", 0) > 0:
            status_parts.append(f"Applied {dropouts['rate_per_min']} dropouts/min")
        if garble_prob > 0:
            status_parts.append(f"Garble probability: {garble_prob:.1%}")
        
        return output_path, "\n".join(status_parts)
        
    except Exception as e:
        return None, f"❌ Processing error: {str(e)}"

def update_controls(preset_name: str):
    values = get_control_values(preset_name)
    summary = format_preset_summary(preset_name)
    return (*values, summary)

CUSTOM_CSS = """
.gradio-container { font-family: 'Inter', sans-serif; }
.main-header { 
    text-align: center; padding: 20px; border-radius: 12px; color: white;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
    margin-bottom: 20px; 
}
.control-card { 
    background: #f8f9fa; border: 1px solid #e9ecef; 
    border-radius: 12px; padding: 16px; 
}
.preset-card { 
    background: linear-gradient(135deg, #74b9ff 0%, #0984e3 100%); 
    color: white; border-radius: 12px; padding: 16px; 
}
"""

initial_values = get_control_values(INITIAL_PRESET)

with gr.Blocks(css=CUSTOM_CSS, title="Voice Lab FX Console", theme=gr.themes.Soft()) as demo:
    gr.HTML("""
    <div class='main-header'>
        <h1 style='margin: 0;'>🎙️ Voice Lab FX</h1>
        <p style='margin: 8px 0 0 0;'>Professional Voice Processing & Effects Suite</p>
    </div>
    """)

    with gr.Row():
        with gr.Column(scale=2):
            voice_input = gr.Audio(label="📂 Upload Audio", type="filepath")
            
            with gr.Group():
                gr.HTML("<h3 style='color: #2d3748;'>🎛️ Presets</h3>")
                preset_dropdown = gr.Dropdown(
                    choices=list(PRESET_MAP.keys()),
                    value=INITIAL_PRESET,
                    label="Choose Preset",
                )
                preset_summary = gr.Markdown(format_preset_summary(INITIAL_PRESET))
            
            seed_input = gr.Number(label="🎲 Random Seed (optional)", precision=0)
            
        with gr.Column(scale=3):
            control_components: Dict[str, gr.components.Component] = {}
            value_iter = iter(initial_values)
            
            with gr.Tabs():
                for section_id, section_label in SECTION_ORDER:
                    with gr.TabItem(section_label):
                        with gr.Group():
                            section_controls = [c for c in CONTROL_DEFS if c["section"] == section_id]
                            for control in section_controls:
                                default_value = next(value_iter)
                                if control["kind"] == "slider":
                                    component = gr.Slider(
                                        minimum=control["minimum"],
                                        maximum=control["maximum"],
                                        value=default_value,
                                        step=control.get("step", 1),
                                        label=control["label"],
                                        info=control.get("info"),
                                    )
                                else:
                                    component = gr.Checkbox(
                                        value=bool(default_value),
                                        label=control["label"],
                                    )
                                control_components[control["id"]] = component

    with gr.Row():
        output_audio = gr.Audio(label="🎧 Processed Output", type="filepath")
    
    status_markdown = gr.Markdown()

    with gr.Row():
        process_button = gr.Button("🚁 Process Audio", variant="primary", size="lg")
        clear_button = gr.Button("🧹 Clear", variant="secondary")

    # Usage tips
    gr.HTML("""
    <div style="margin-top: 20px; padding: 20px; background: #f8f9fa; border-radius: 8px;">
        <h3>💡 Usage Tips:</h3>
        <ul>
            <li><strong>Clean:</strong> Minimal processing for clear communication</li>
            <li><strong>Radio Static:</strong> Classic radio communication with dropouts and static</li>
            <li><strong>Helicopter:</strong> Military/aviation comms with heavy processing and ambience</li>
            <li><strong>Custom:</strong> Adjust individual parameters after selecting a preset</li>
        </ul>
    </div>
    """)

    control_list = [control_components[c["id"]] for c in CONTROL_DEFS]

    # Connect interactions
    preset_dropdown.change(
        fn=update_controls,
        inputs=preset_dropdown,
        outputs=control_list + [preset_summary],
    )

    process_button.click(
        fn=process_audio_local,
        inputs=[voice_input, preset_dropdown, seed_input, *control_list],
        outputs=[output_audio, status_markdown],
    )

    clear_button.click(
        fn=lambda: (None, None, format_preset_summary(INITIAL_PRESET)),
        outputs=[output_audio, status_markdown, preset_summary],
    )

if __name__ == "__main__":
    demo.launch(share=True)