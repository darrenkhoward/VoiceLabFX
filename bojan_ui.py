"""Minimal VoiceLab FX UI for preset demo (Bojan deployment)."""
from pathlib import Path
from typing import Optional, Tuple

import gradio as gr

from app import (
    BOJAN_PRESET_CONFIGS,
    process_bojan_preset,
)

PRESET_NAMES = list(BOJAN_PRESET_CONFIGS.keys())


def render_preset(audio_path: Optional[str], preset: str, normalize: bool) -> Tuple[Optional[str], str]:
    if not audio_path:
        return None, "⚠️ Upload caller audio first."

    output_path, status = process_bojan_preset(audio_path, preset, normalize_override=normalize)
    if not output_path:
        return None, status or "❌ Processing failed."

    return output_path, status or "✅ Render complete."


custom_css = """
.gradio-container { font-family: 'Inter', sans-serif; }
.header { text-align: center; padding: 16px 0; margin-bottom: 12px; }
.preset-card { background: #6c5ce7; color: white; border-radius: 12px; padding: 16px; }
"""


def build_demo() -> gr.Blocks:
    with gr.Blocks(css=custom_css, title="VoiceLab FX — Call Presets", theme=gr.themes.Soft()) as demo:
        gr.HTML(
            """
            <div class='header'>
                <h1 style='margin:0;'>🎙️ VoiceLab FX — Rapid Caller Presets</h1>
                <p style='margin:6px 0 0 0;'>Upload dry voice, pick a scenario, download the processed caller.</p>
            </div>
            """
        )

        with gr.Row():
            with gr.Column(scale=2):
                voice = gr.Audio(label="Caller Voice", type="filepath")
                preset = gr.Dropdown(PRESET_NAMES, value=PRESET_NAMES[0], label="Preset")
                normalize = gr.Checkbox(True, label="Normalize Output (-18 LUFS)")
                status = gr.Markdown("Ready.")
            with gr.Column(scale=3):
                output = gr.Audio(label="Processed Caller", type="filepath")

        run_btn = gr.Button("🚀 Render Caller", variant="primary")
        clear_btn = gr.Button("🧹 Clear")

        run_btn.click(
            fn=render_preset,
            inputs=[voice, preset, normalize],
            outputs=[output, status],
        )

        clear_btn.click(
            fn=lambda: (None, "Ready."),
            outputs=[output, status],
        )

    return demo


if __name__ == "__main__":
    build_demo().launch()
