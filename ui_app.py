import copy
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence

import gradio as gr
import requests

API_BASE_URL = Path(__file__).resolve().parent.joinpath(".env.api").read_text().strip() if Path(".env.api").exists() else "http://127.0.0.1:5001"
PRESETS_PATH = Path(__file__).resolve().parent / "presets.json"


def load_presets() -> Dict[str, Dict[str, Any]]:
    data = json.loads(PRESETS_PATH.read_text())
    presets = data.get("presets", [])
    return {preset["name"]: preset for preset in presets}


PRESET_MAP = load_presets()
if not PRESET_MAP:
    raise RuntimeError("No presets found. Check presets.json.")

INITIAL_PRESET = next(iter(PRESET_MAP))


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
    {
        "id": "ambience_random",
        "path": ["ambience", "random_start"],
        "kind": "checkbox",
        "label": "Randomize Ambience Start",
        "default": True,
        "section": "ambience",
    },
    {
        "id": "ambience_shuffle",
        "path": ["ambience", "shuffle_between_runs"],
        "kind": "checkbox",
        "label": "Shuffle Ambience Between Renders",
        "default": True,
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
    ambience = chain.get("ambience")
    if ambience:
        files = ambience.get("files", [])
        if files:
            lines.append("**Ambience Files:** \n" + "\n".join(f"- {Path(f).name}" for f in files))
    dropouts = chain.get("dropouts")
    if dropouts and dropouts.get("rate_per_min"):
        lines.append(
            f"**Dropouts:** {dropouts.get('rate_per_min')} per min, {dropouts.get('avg_ms')} ms avg"
        )
    if chain.get("device_ir"):
        lines.append(f"**Device IR:** {chain['device_ir'].get('path', 'n/a')}")
    return "\n\n".join(lines)


def process_audio(voice_path: str, preset_name: str, seed: Any, *control_values: Any):
    if not voice_path:
        return None, "⚠️ Upload an audio file first."

    chain = build_chain(preset_name, list(control_values))
    data: Dict[str, Any] = {"preset": preset_name}
    if seed not in (None, ""):
        try:
            data["seed"] = int(seed)
        except (TypeError, ValueError):
            return None, "⚠️ Seed must be an integer."
    data["config"] = json.dumps({"chain": chain})

    files = {
        "file": (Path(voice_path).name, open(voice_path, "rb"), "audio/wav"),
    }

    try:
        response = requests.post(f"{API_BASE_URL}/process", data=data, files=files, timeout=120)
    finally:
        files["file"][1].close()

    if response.status_code != 200:
        try:
            payload = response.json()
            message = payload.get("error") or payload
        except ValueError:
            message = response.text or f"HTTP {response.status_code}"
        return None, f"❌ Processing failed: {message}"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.write(response.content)
    tmp.flush()
    tmp.close()

    details = response.headers.get("X-FX-Details")
    request_id = response.headers.get("X-Request-Id")
    detail_lines = []
    if request_id:
        detail_lines.append(f"Request ID: `{request_id}`")
    if details:
        try:
            parsed = json.loads(details)
            for key, value in parsed.items():
                detail_lines.append(f"**{key}:** {value}")
        except json.JSONDecodeError:
            detail_lines.append(details)

    status = "\n".join(detail_lines) if detail_lines else "✅ Render complete."
    return tmp.name, status


def update_controls(preset_name: str):
    values = get_control_values(preset_name)
    summary = format_preset_summary(preset_name)
    return (*values, summary)


CUSTOM_CSS = """
.gradio-container { font-family: 'Inter', sans-serif; }
.main-header { text-align: center; padding: 20px; border-radius: 12px; color: white;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); margin-bottom: 20px; }
.control-card { background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 12px; padding: 16px; }
.preset-card { background: linear-gradient(135deg, #74b9ff 0%, #0984e3 100%); color: white; border-radius: 12px; padding: 16px; }
"""


initial_values = get_control_values(INITIAL_PRESET)


with gr.Blocks(css=CUSTOM_CSS, title="Voice Lab FX Console", theme=gr.themes.Soft()) as demo:
    gr.HTML("""
    <div class='main-header'>
        <h1 style='margin: 0;'>🎙️ Voice Lab FX</h1>
        <p style='margin: 8px 0 0 0;'>Upload audio, pick a preset, fine-tune, and render.</p>
    </div>
    """)

    with gr.Row():
        with gr.Column(scale=2):
            voice_input = gr.Audio(label="Upload Audio", type="filepath")
            preset_dropdown = gr.Dropdown(
                choices=list(PRESET_MAP.keys()),
                value=INITIAL_PRESET,
                label="Preset",
            )
            seed_input = gr.Number(label="Seed (optional)", precision=0)
            preset_summary = gr.Markdown(format_preset_summary(INITIAL_PRESET))
        with gr.Column(scale=3):
            control_components: Dict[str, gr.components.Component] = {}
            value_iter = iter(initial_values)
            for section_id, section_label in SECTION_ORDER:
                with gr.Group():
                    gr.HTML(f"<h3>{section_label}</h3>")
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

    output_audio = gr.Audio(label="Processed Output", type="filepath")
    status_markdown = gr.Markdown()

    with gr.Row():
        process_button = gr.Button("🚀 Render", variant="primary")
        clear_button = gr.Button("🧹 Clear")

    control_list = [control_components[c["id"]] for c in CONTROL_DEFS]

    preset_dropdown.change(
        fn=update_controls,
        inputs=preset_dropdown,
        outputs=control_list + [preset_summary],
    )

    process_button.click(
        fn=process_audio,
        inputs=[voice_input, preset_dropdown, seed_input, *control_list],
        outputs=[output_audio, status_markdown],
    )

    clear_button.click(
        fn=lambda: (None, None, format_preset_summary(INITIAL_PRESET)),
        outputs=[output_audio, status_markdown, preset_summary],
    )


if __name__ == "__main__":
    demo.launch()
