import gradio as gr
import numpy as np
import soundfile as sf
import scipy.signal as sig
import tempfile
import os
import random
import json

SR = 16000  # Target sample rate for phone realism

# Helper functions
def normalize(x):
    return x / (np.max(np.abs(x)) + 1e-9)

def apply_notch(x, freq=60, Q=30, sr=SR):
    b, a = sig.iirnotch(freq / (sr / 2), Q)
    return sig.lfilter(b, a, x)

def safe_agc(x, target_db=-12, boost_db=6, cut_db=12, atk_ms=30, rel_ms=300):
    win = int(0.2 * SR)
    rms = np.sqrt(sig.convolve(x**2, np.ones(win) / win, 'same') + 1e-9)
    target = 10 ** (target_db / 20)
    raw = np.clip(target / rms, 10 ** (-cut_db / 20), 10 ** (boost_db / 20))
    atk = np.exp(-1 / (atk_ms * 0.001 * SR))
    rel = np.exp(-1 / (rel_ms * 0.001 * SR))
    g = np.empty_like(raw)
    g[0] = raw[0]
    for n in range(1, len(g)):
        coef = atk if raw[n] > g[n-1] else rel
        g[n] = coef * g[n-1] + (1 - coef) * raw[n]
    return x * g

def soft_limiter(x, thresh_db=-12.4, ratio=3.1):
    t = 10 ** (thresh_db / 20)
    y = np.copy(x)
    m = np.abs(y) > t
    y[m] = np.sign(y[m]) * (t + (np.abs(y[m]) - t) / ratio)
    return y

# New FX functions
def apply_stutter(x, amt, sr=SR):
    if amt <= 0: return x
    window = int(sr * 0.05)
    out = []
    i = 0
    while i < len(x):
        chunk = x[i:i + window]
        if random.random() < amt:
            repeats = random.randint(1, 3)
            for _ in range(repeats):
                out.append(chunk)
        else:
            out.append(chunk)
        i += window
    return np.concatenate(out)[:len(x)]

def apply_robotize(x, amt, sr=SR):
    if amt <= 0: return x
    fft_size = 1024
    hop = fft_size // 4
    phases = np.zeros(fft_size)
    out = np.zeros(len(x) + fft_size)
    for i in range(0, len(x) - fft_size, hop):
        frame = x[i:i + fft_size] * np.hanning(fft_size)
        spectrum = np.fft.fft(frame)
        mag = np.abs(spectrum)
        phase = np.angle(spectrum)
        new_phase = phases + amt * np.pi
        phases = new_phase
        new_spectrum = mag * np.exp(1j * new_phase)
        out[i:i + fft_size] += np.real(np.fft.ifft(new_spectrum)) * np.hanning(fft_size)
    return out[:len(x)]

def apply_mp3_sizzle(x, amt):
    if amt <= 0: return x
    noise = np.random.normal(0, amt * 0.01, size=x.shape)
    return x + noise

def apply_rf_noise(x, amt):
    if amt <= 0: return x
    noise = np.random.normal(0, amt * 0.02, size=x.shape)
    return x + noise

# Phone FX chain
def phone_fx(v, drop_p, chunk_ms, bits, garb, stutter_amt, robot_amt, mp3_amt, rf_amt, sr=SR):
    # Bandpass EQ for phone
    v = sig.lfilter(*sig.butter(2, [300 / (sr / 2), 3500 / (sr / 2)], 'band'), v)
    # Dropout
    w = int(chunk_ms * sr / 1000)
    for i in range(0, len(v), w):
        if random.random() < drop_p:
            v[i:i + w] = 0
    # Garble
    gwin = int(0.06 * sr)
    out = []
    for i in range(0, len(v), gwin):
        seg = v[i:i + gwin]
        if random.random() < garb:
            seg = sig.resample(seg, int(len(seg) / (1 + random.uniform(-0.2, 0.2))))
        out.append(seg)
    v = np.concatenate(out)[:len(v)]
    # Bitcrush
    v = np.round(v * (2 ** bits)) / (2 ** bits)
    # New FX
    v = apply_stutter(v, stutter_amt, sr)
    v = apply_robotize(v, robot_amt, sr)
    v = apply_mp3_sizzle(v, mp3_amt)
    v = apply_rf_noise(v, rf_amt)
    return np.tanh(v)

# Ambience loop and ducking (refined with threshold/fade from JSON, plus normalization/boost)
def loop_asset(name, L, vol, sr=SR, random_start=True, loop_mode="none"):
    if not os.path.exists(name):
        print(f"Ambience file {name} not found - returning silence.")
        return np.zeros(L)
    s, _ = sf.read(name)
    s = s.mean(1) if s.ndim > 1 else s
    s = normalize(s) * 1.41  # Normalize and boost ~3 dB
    if random_start:
        offset = random.randint(0, len(s) - 1)
        s = s[offset:]
    if loop_mode == "none":
        if len(s) < L:
            s = np.concatenate([s, np.zeros(L - len(s))])
        else:
            s = s[:L]
    else:  # Fallback tile if mode changes
        s = np.tile(s, int(np.ceil(L / len(s))))[:L]
    return s * vol

def duck(bg, fg, amt, threshold_db=-20, fade_ms=50, sr=SR):
    threshold = 10 ** (threshold_db / 20)
    env = np.abs(sig.hilbert(fg))
    env /= env.max() + 1e-9
    # Apply duck only when voice > threshold, with fade
    duck_mask = (env > threshold).astype(float)
    # Simple fade simulation (convolve for smoothing)
    fade_win = int(fade_ms * sr / 1000)
    hanning_win = np.hanning(fade_win)
    duck_mask = sig.convolve(duck_mask, hanning_win / hanning_win.sum(), 'same')
    return bg * (1 - amt * duck_mask[:, None])

# Cellphone IR convolution
def apply_phone_ir(v, gain, ir_path="cellphone_ir.wav"):
    if gain <= 0 or not os.path.exists(ir_path):
        return v
    ir, _ = sf.read(ir_path)
    ir = ir.mean(1) if ir.ndim > 1 else ir
    wet = sig.fftconvolve(v, ir)[:len(v)]
    return normalize((1 - gain) * v + gain * wet)

# Main process function
def process(audio_file, drop_prob, chunk_ms, bits, garble_amt, stutter_amt, robot_amt, mp3_amt, rf_amt, agc_db, thresh_db, ratio, duck_amt, amb_vol, lowpass_cutoff, reduce_reverb, phone_ir_gain=0):
    if audio_file is None:
        return None
    v, sr = sf.read(audio_file)
    v = v.mean(1) if v.ndim > 1 else v
    if sr != SR:
        v = sig.resample(v, int(len(v) * SR / sr))
    v = phone_fx(v, drop_prob, chunk_ms, bits, garble_amt, stutter_amt, robot_amt, mp3_amt, rf_amt, SR)
    v = apply_phone_ir(v, phone_ir_gain)
    v = safe_agc(v, agc_db)
    v = soft_limiter(v, thresh_db, ratio)
    if lowpass_cutoff < SR / 2:
        norm_cutoff = lowpass_cutoff / (SR / 2)
        b, a = sig.butter(4, norm_cutoff, btype='low')
        v = sig.lfilter(b, a, v)
    v = apply_notch(v, 60, 30, SR)
    ambience = loop_asset("city_trimmed.wav", len(v), amb_vol, SR)
    v_stereo = np.stack([v, v], axis=1)
    amb_stereo = np.stack([ambience, ambience], axis=1)
    mixed = normalize(v_stereo + duck(amb_stereo, v_stereo[:, 0], duck_amt, sr=SR))
    if reduce_reverb:
        b, a = sig.butter(4, 200 / (SR / 2), btype='high')
        mixed[:, 0] = sig.lfilter(b, a, mixed[:, 0])
        mixed[:, 1] = sig.lfilter(b, a, mixed[:, 1])
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    sf.write(tmp.name, mixed, SR)
    return tmp.name

# UI with all sliders always visible, tooltips, and preset handling
with gr.Blocks() as demo:
    gr.Markdown("# Master FX Engine — Street Sounds Demo")
    audio_in = gr.Audio(type="filepath", label="Upload WAV")
    drop_prob = gr.Slider(0, 1, 0, step=0.01, label="Dropout Probability", info="Chance of audio dropouts for spotty connection effect (0=off, 1=constant drops).")
    chunk_ms = gr.Slider(40, 400, 150, step=10, label="Dropout Chunk Size (ms)", info="Length of each dropout in milliseconds.")
    bits = gr.Slider(2, 16, 10, step=1, label="Bitcrush Bits (0=off)", info="Reduce bit depth for lo-fi/grainy sound; 0 disables.")
    garble_amt = gr.Slider(0, 1, 0.02, step=0.01, label="Garble Intensity", info="Adds distortion/warble for garbled transmission (0=off).")
    stutter_amt = gr.Slider(0, 1, 0, step=0.01, label="Stutter Amount", info="Glitchy repetition for poor signal (0=off).")
    robot_amt = gr.Slider(0, 1, 0, step=0.01, label="Robotization Amount", info="Metallic/vocoder effect for robotic voice (0=off).")
    mp3_amt = gr.Slider(0, 1, 0, step=0.01, label="MP3 Sizzle Amount", info="Compression artifacts/sizzle for low-bitrate feel (0=off).")
    rf_amt = gr.Slider(0, 1, 0, step=0.01, label="RF Noise Amount", info="Radio frequency interference/static (0=off).")
    agc_db = gr.Slider(-30, -8, -18, step=0.1, label="Target AGC (dB)", info="Auto gain control target level.")
    thresh_db = gr.Slider(-30, 0, -12.4, step=0.1, label="Limiter Threshold (dB)", info="Peak limiting threshold.")
    ratio = gr.Slider(1, 20, 3.1, step=0.1, label="Limiter Ratio", info="Compression ratio for limiter.")
    duck_amt = gr.Slider(0, 1, 1, step=0.01, label="Ducking Amount", info="How much ambience ducks under voice (0=off).")
    amb_vol = gr.Slider(0, 1, 1, step=0.01, label="Ambience Volume", info="Volume of background street sounds.")
    lowpass_cutoff = gr.Slider(1000, 8000, 8000, step=50, label="Lowpass Cutoff (Hz)", info="High-frequency cutoff for muffled effect.")
    reduce_reverb = gr.Checkbox(True, label="Reduce Reverb", info="Apply high-pass to cut room echo.")
    phone_ir_gain = gr.Slider(0, 2, 1.07, step=0.01, label="Phone IR Gain", info="Wet/dry mix for cellphone speaker convolution (0=off, 1=full wet, >1 for emphasis).")
    audio_out = gr.Audio(label="Processed Output")
    save_btn = gr.Button("Save Preset as JSON")
    load_file = gr.File(label="Load Preset JSON", file_types=[".json"])
    download_output = gr.File(label="Download Preset", visible=False)

    def export_preset(*args):
        keys = ["drop_prob", "chunk_ms", "bits", "garble_amt", "stutter_amt", "robot_amt", "mp3_amt", "rf_amt", "agc_db", "thresh_db", "ratio", "duck_amt", "amb_vol", "lowpass_cutoff", "reduce_reverb", "phone_ir_gain"]
        preset = dict(zip(keys, args))
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        json.dump(preset, open(tmp.name, "w"), indent=4)
        return tmp.name

    def import_preset(file):
        if file is None:
            return [gr.update(value=v) for v in [0, 150, 10, 0.02, 0, 0, 0, 0, -18, -12.4, 3.1, 1, 1, 8000, True, 1.07]]
        with open(file.name, "r") as f:
            preset = json.load(f)
        keys = ["drop_prob", "chunk_ms", "bits", "garble_amt", "stutter_amt", "robot_amt", "mp3_amt", "rf_amt", "agc_db", "thresh_db", "ratio", "duck_amt", "amb_vol", "lowpass_cutoff", "reduce_reverb", "phone_ir_gain"]
        return [gr.update(value=preset.get(k, default)) for k, default in zip(keys, [0, 150, 10, 0.02, 0, 0, 0, 0, -18, -12.4, 3.1, 1, 1, 8000, True, 1.07])]

    save_btn.click(export_preset, inputs=[drop_prob, chunk_ms, bits, garble_amt, stutter_amt, robot_amt, mp3_amt, rf_amt, agc_db, thresh_db, ratio, duck_amt, amb_vol, lowpass_cutoff, reduce_reverb, phone_ir_gain], outputs=download_output)
    load_file.upload(import_preset, inputs=load_file, outputs=[drop_prob, chunk_ms, bits, garble_amt, stutter_amt, robot_amt, mp3_amt, rf_amt, agc_db, thresh_db, ratio, duck_amt, amb_vol, lowpass_cutoff, reduce_reverb, phone_ir_gain])
    submit_btn = gr.Button("Process Audio")
    submit_btn.click(process, inputs=[audio_in, drop_prob, chunk_ms, bits, garble_amt, stutter_amt, robot_amt, mp3_amt, rf_amt, agc_db, thresh_db, ratio, duck_amt, amb_vol, lowpass_cutoff, reduce_reverb, phone_ir_gain], outputs=audio_out)

if __name__ == "__main__":
    demo.launch()