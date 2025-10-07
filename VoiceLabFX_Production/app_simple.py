# VoiceLabFX — Simplified Preset-Based UI
# Production-ready interface with JSON-driven presets

from __future__ import annotations
import os, json
from typing import Dict, Any, Optional, List, Tuple
import gradio as gr

# Import the core processing engine from the full app
from app import process_audio, SR

PRESETS_FILE = "presets.json"

def load_presets() -> Dict[str, Any]:
    """Load preset configurations from JSON file"""
    if not os.path.exists(PRESETS_FILE):
        return {"presets": {}, "user_controls": {"global": [], "preset_specific": {}}}
    
    with open(PRESETS_FILE, 'r') as f:
        return json.load(f)

def map_preset_to_process_params(preset_config: Dict[str, Any], intensity: float = 1.0, 
                                  user_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Convert JSON preset configuration to process_audio() parameters.
    
    Args:
        preset_config: Preset configuration from JSON
        intensity: Global intensity multiplier (0.0-1.0) to scale all effects
        user_overrides: User-adjusted parameters (e.g., bg_gain_db, room_ir_mix_percent)
    
    Returns:
        Dictionary of parameters for process_audio()
    """
    user_overrides = user_overrides or {}
    
    # Source processing
    source = preset_config.get("source", {})
    dereverb_amt = source.get("dereverb", 0.0) * intensity
    src_hpf = source.get("src_hpf", 0)
    src_lpf = source.get("src_lpf", 20000)
    leveler_amt = source.get("leveler_amt", 0.0) * intensity
    wpe_strength = source.get("wpe_strength", 0.0) * intensity
    cleanup_mix = source.get("cleanup_mix", 1.0)
    
    # Room IR
    room_ir = preset_config.get("room_ir", {})
    room_ir_file = room_ir.get("file")
    room_ir_mix = user_overrides.get("room_ir_mix_percent", room_ir.get("mix_percent", 0)) * intensity
    
    # Codec settings
    codec = preset_config.get("codec", {})
    mu_law_amt = codec.get("mu_law_amt", 0.0) * intensity
    bandwidth_override = codec.get("bandwidth_override")
    
    # Network artifacts
    artifacts = preset_config.get("network_artifacts", {})
    rf_amt = artifacts.get("rf_noise", 0.0) * intensity
    dropout_prob = artifacts.get("dropout_prob", 0.0) * intensity
    plc_ms = artifacts.get("plc_ms", 60)
    dropout_depth_db = artifacts.get("dropout_depth_db", -24)
    garble_intensity = artifacts.get("garble_intensity", 0.0) * intensity
    stutter_amt = artifacts.get("stutter_amt", 0.0) * intensity
    jitter_intensity = artifacts.get("jitter_intensity", 0.0) * intensity
    reorder_prob = artifacts.get("reorder_prob", 0.0) * intensity
    
    # Background
    bg = preset_config.get("background", {})
    bg_files = bg.get("files", [])
    bg_gain_db = user_overrides.get("bg_gain_db", bg.get("gain_db", -60))
    bg_hpf = bg.get("hpf", 60)
    bg_lpf = bg.get("lpf", 8000)
    bg_duck_db = bg.get("duck_db", -60)
    
    # Background IR
    bg_ir = preset_config.get("background_ir", {})
    bg_ir_file = bg_ir.get("file")
    bg_ir_gain_db = bg_ir.get("gain_db", 0)
    
    # Handset IR
    handset_ir = preset_config.get("handset_ir", {})
    handset_ir_file = handset_ir.get("file")
    handset_ir_gain_db = handset_ir.get("gain_db", 0)
    
    # Events
    events = preset_config.get("events", {})
    traffic_files = events.get("traffic_files", [])
    traffic_ev_min = events.get("traffic_ev_min", 0)
    traffic_vol_db = events.get("traffic_vol_db", -20)
    baby_ev_min = events.get("baby_ev_min", 0)
    dog_ev_min = events.get("dog_ev_min", 0)
    
    # Output
    output = preset_config.get("output", {})
    target_lufs = user_overrides.get("target_lufs", output.get("target_lufs", -18))
    
    # Quality tier
    quality_tier = preset_config.get("quality_tier", "standard")
    
    # Build parameter dict for process_audio()
    params = {
        "dereverb_amt": dereverb_amt,
        "src_hpf": src_hpf,
        "src_lpf": src_lpf,
        "leveler_amt": leveler_amt,
        "wpe_strength": wpe_strength,
        "cleanup_mix": cleanup_mix,
        "room_ir_file": room_ir_file,
        "room_ir_gain_db": room_ir_mix,  # Note: room_ir_gain_db is actually mix %
        "bg_file": bg_files,
        "bg_ir_file": bg_ir_file,
        "bg_ir_gain_db": bg_ir_gain_db,
        "bg_gain_db": bg_gain_db,
        "bg_hpf": bg_hpf,
        "bg_lpf": bg_lpf,
        "bg_duck_db": bg_duck_db,
        "quality_tier": quality_tier,
        "custom_low_freq": 300,
        "custom_high_freq": 3400,
        "custom_compression": 0.0,
        "custom_noise": 0.0,
        "custom_dropout_mult": 1.0,
        "custom_garble_mult": 1.0,
        "bandwidth_mode": bandwidth_override or "Narrowband 300–3500",
        "opus_bitrate_kbps": 24,
        "post_mu_grit": mu_law_amt,
        "plc_ms": plc_ms,
        "dropout_prob": dropout_prob,
        "dropout_depth_db": dropout_depth_db,
        "garble_prob": garble_intensity,
        "stutter_amt": stutter_amt,
        "jitter_intensity": jitter_intensity,
        "buffer_prob": 0.0,
        "reorder_prob": reorder_prob,
        "codec_type": "amr_nb",
        "codec_intensity": 0.0,
        "mic_proximity": 0.5,
        "mic_type": "handset",
        "mp3_amt": 0.0,
        "rf_amt": rf_amt,
        "handset_ir_file": handset_ir_file,
        "handset_ir_gain_db": handset_ir_gain_db,
        "traffic_files": traffic_files,
        "traffic_ev_min": traffic_ev_min,
        "traffic_vol_db": traffic_vol_db,
        "baby_files": [],
        "baby_ev_min": baby_ev_min,
        "baby_vol_db": -12,
        "dog_files": [],
        "dog_ev_min": dog_ev_min,
        "dog_vol_db": -12,
        "normalize_output": True,
        "target_lufs": target_lufs
    }
    
    return params

def process_with_preset(audio_file: str, preset_name: str, intensity: float, 
                        bg_level: Optional[float] = None, 
                        reverb_amount: Optional[float] = None,
                        party_level: Optional[float] = None,
                        target_lufs: float = -18.0) -> Tuple[str, str]:
    """
    Process audio using a preset with user-adjustable parameters.
    
    Args:
        audio_file: Path to input audio file
        preset_name: Name of preset to use
        intensity: Global effect intensity (0.0-1.0)
        bg_level: Background level override (dB) for Street Sounds
        reverb_amount: Reverb mix override (%) for Bathroom Caller
        party_level: Party music level override (dB) for Bathroom Caller
        target_lufs: Output loudness target
    
    Returns:
        Tuple of (output_audio_path, status_message)
    """
    if not audio_file:
        return None, "Error: No audio file provided"
    
    # Load presets
    preset_data = load_presets()
    presets = preset_data.get("presets", {})
    
    if preset_name not in presets:
        return None, f"Error: Preset '{preset_name}' not found"
    
    preset_config = presets[preset_name]
    
    # Build user overrides
    user_overrides = {"target_lufs": target_lufs}
    
    if preset_name == "Street Sounds" and bg_level is not None:
        user_overrides["bg_gain_db"] = bg_level
    
    if preset_name == "Bathroom Caller":
        if reverb_amount is not None:
            user_overrides["room_ir_mix_percent"] = reverb_amount
        if party_level is not None:
            user_overrides["bg_gain_db"] = party_level
    
    # Map preset to process parameters
    params = map_preset_to_process_params(preset_config, intensity, user_overrides)
    
    # Call the core processing function
    try:
        output_path, status = process_audio(audio_file, **params)
        description = preset_config.get("description", "")
        full_status = f"✅ {preset_name}: {description}\n\n{status}"
        return output_path, full_status
    except Exception as e:
        return None, f"Error processing audio: {str(e)}"

# Build Gradio UI
def build_ui():
    preset_data = load_presets()
    presets = preset_data.get("presets", {})
    preset_names = list(presets.keys())
    
    with gr.Blocks(title="VoiceLabFX — Simplified", theme=gr.themes.Soft(primary_hue="purple")) as demo:
        gr.Markdown("# 🎙️ VoiceLabFX — Simplified Preset Interface")
        gr.Markdown("Create realistic phone caller effects with easy-to-use presets.")
        
        with gr.Row():
            with gr.Column(scale=1):
                # Input
                audio_input = gr.Audio(label="📁 Upload Voice Recording", type="filepath")
                
                # Preset selector
                preset_dropdown = gr.Dropdown(
                    choices=preset_names,
                    value=preset_names[0] if preset_names else None,
                    label="🎯 Select Preset",
                    info="Choose the type of caller effect"
                )
                
                # Global controls
                gr.Markdown("### Global Controls")
                intensity_slider = gr.Slider(
                    minimum=0.0, maximum=1.0, value=1.0, step=0.05,
                    label="Effect Intensity",
                    info="Overall strength of all effects (0% = bypass, 100% = full)"
                )
                
                target_lufs_slider = gr.Slider(
                    minimum=-23.0, maximum=-14.0, value=-18.0, step=0.5,
                    label="Output Level (LUFS)",
                    info="Target loudness for broadcast"
                )
                
                # Preset-specific controls (conditionally visible)
                gr.Markdown("### Preset-Specific Controls")
                
                # Street Sounds controls
                bg_level_slider = gr.Slider(
                    minimum=-40.0, maximum=-12.0, value=-22.0, step=1.0,
                    label="Background Level (dB)",
                    info="Traffic/urban ambience volume",
                    visible=False
                )
                
                # Bathroom Caller controls
                reverb_slider = gr.Slider(
                    minimum=0.0, maximum=25.0, value=12.0, step=1.0,
                    label="Reverb Amount (%)",
                    info="Bathroom reverb wetness",
                    visible=False
                )
                
                party_level_slider = gr.Slider(
                    minimum=-40.0, maximum=-18.0, value=-28.0, step=1.0,
                    label="Party Music Level (dB)",
                    info="Muffled party music from next room",
                    visible=False
                )
                
                # Process button
                process_btn = gr.Button("🎬 Process Audio", variant="primary", size="lg")
            
            with gr.Column(scale=1):
                # Output
                audio_output = gr.Audio(label="🔊 Processed Audio", type="filepath")
                status_output = gr.Textbox(label="Status", lines=10, max_lines=20)
        
        # Update visibility of preset-specific controls based on preset selection
        def update_controls_visibility(preset_name):
            is_street = (preset_name == "Street Sounds")
            is_bathroom = (preset_name == "Bathroom Caller")
            return (
                gr.update(visible=is_street),  # bg_level_slider
                gr.update(visible=is_bathroom),  # reverb_slider
                gr.update(visible=is_bathroom)   # party_level_slider
            )
        
        preset_dropdown.change(
            fn=update_controls_visibility,
            inputs=[preset_dropdown],
            outputs=[bg_level_slider, reverb_slider, party_level_slider]
        )
        
        # Process button click
        process_btn.click(
            fn=process_with_preset,
            inputs=[
                audio_input, preset_dropdown, intensity_slider,
                bg_level_slider, reverb_slider, party_level_slider, target_lufs_slider
            ],
            outputs=[audio_output, status_output]
        )
    
    return demo

if __name__ == "__main__":
    demo = build_ui()
    demo.launch(server_name="0.0.0.0", server_port=7861, share=False)

