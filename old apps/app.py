import gradio as gr
import numpy as np
import soundfile as sf
import scipy.signal as sig
import tempfile
import os

SR = 16000
AMB_WAV = "assets/city_trimmed.wav"  # <-- must be present as wav!
STATIC_WAV = "assets/static.wav"     # (optional) static asset wav
RUMBLE_WAV = "assets/rumble.wav"     # (optional) rumble asset wav

def load_wav(path, sr=SR):
    x, s = sf.read(path)
    if x.ndim > 1: x = x.mean(1)
    if s != sr: x = sig.resample(x, int(len(x)*sr/s))
    return x.astype(np.float32)

def save_wav(arr, sr=SR):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    sf.write(tmp.name, arr, sr)
    return tmp.name

def dropout_fx(x, drop_prob=0.0, chunk_ms=150):
    w = int(chunk_ms * SR / 1000)
    x = x.copy()
    for i in range(0, len(x), w):
        if np.random.rand() < drop_prob:
            x[i:i+w] = 0
    return x

def bitcrush_fx(x, bits=16):
    if bits >= 16: return x
    return np.round(x * (2**bits)) / (2**bits)

def garble_fx(x, intensity=0.0):
    if intensity == 0: return x
    noise = np.random.normal(0, intensity * np.max(np.abs(x)), x.shape)
    return np.clip(x + noise, -1, 1)

def limiter_fx(x, thresh_db=-12, ratio=3):
    t = 10 ** (thresh_db / 20)
    y = x.copy()
    mask = np.abs(y) > t
    y[mask] = np.sign(y[mask]) * (t + (np.abs(y[mask]) - t) / ratio)
    return y

def lowpass_fx(x, cutoff=8000):
    if cutoff >= SR // 2: return x
    b, a = sig.butter(4, cutoff / (SR/2), btype='low')
    return sig.lfilter(b, a, x)

def apply_notch(x, freq=1000, Q=30, sr=SR, enabled=True):
    if not enabled: return x
    b, a = sig.iirnotch(freq, Q, sr)
    return sig.lfilter(b, a, x)

def pitch_shift_fx(x, semitones=0, sr=SR):
    if semitones == 0: return x
    factor = 2**(semitones/12)
    x_rs = sig.resample(x, int(len(x)/factor))
    if len(x_rs) < len(x):
        x_rs = np.pad(x_rs, (0, len(x) - len(x_rs)))
    return x_rs[:len(x)]

def ambience_fx(length, vol=0.5, wav_path=AMB_WAV):
    if wav_path and os.path.exists(wav_path):
        amb = load_wav(wav_path, SR)
        if len(amb) < length:
            amb = np.tile(amb, int(np.ceil(length/len(amb))))
        amb = amb[:length]
        return amb * vol
    noise = np.random.normal(0, 0.01, length)
    return noise * vol

def static_fx(length, vol=0.05):
    noise = np.random.normal(0, 1, length)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1, -2.494956002, 2.017265875, -0.522189400]
    static = sig.lfilter(b, a, noise)
    static = static / (np.max(np.abs(static)) + 1e-9) * vol
    return static

def rumble_fx(length, vol=0.05):
    noise = np.random.normal(0, 1, length)
    b, a = sig.butter(2, 200/(SR/2), 'low')
    rumble = sig.lfilter(b, a, noise)
    rumble = rumble / (np.max(np.abs(rumble)) + 1e-9) * vol
    return rumble

def duck(bg, fg, amt):
    env = np.abs(sig.hilbert(fg))
    env = env / (env.max() + 1e-9)
    return bg * (1 - amt * env)

def squelch_fx(x, vol=1.0, prob=0.0):
    th = 0.03 * np.max(np.abs(x))
    mask = np.abs(x) < th
    x = x.copy()
    x[mask] *= vol
    if prob > 0:
        seglen = int(0.03 * SR)
        for i in range(0, len(x), seglen):
            if np.random.rand() < prob: x[i:i+seglen] = 0
    return x

def agc_fx(x, target_db=-12):
    rms = np.sqrt(np.mean(x ** 2) + 1e-9)
    target = 10 ** (target_db / 20)
    gain = target / (rms + 1e-9)
    return x * gain

def reverb_reduce_fx(x, enabled=True):
    if not enabled: return x
    b, a = sig.butter(1, 200/(SR/2), btype='high')
    dry = sig.lfilter(b, a, x)
    return dry * 0.8  # Simple gain reduction for "drier" sound

def process(
    voice_file,
    drop_prob, chunk_ms, bits, garble_amt,
    lufs, thresh, ratio, duck_amt,
    amb_vol, static_vol, rumble_vol,
    squelch_vol, mid_squelch, pitch,
    lowpass, notch_on, agc_on, reverb_reduce_on
):
    v = load_wav(voice_file, sr=SR)
    v = dropout_fx(v, drop_prob, chunk_ms)
    v = bitcrush_fx(v, bits)
    v = garble_fx(v, garble_amt)
    v = agc_fx(v, lufs) if agc_on else v
    v = limiter_fx(v, thresh, ratio)
    v = lowpass_fx(v, lowpass)
    v = pitch_shift_fx(v, pitch, SR)
    v = apply_notch(v, 1000, 30, SR, enabled=notch_on)
    v = squelch_fx(v, squelch_vol, mid_squelch)
    v = reverb_reduce_fx(v, enabled=reverb_reduce_on)

    # Ambience overlays
    L = len(v)
    amb = ambience_fx(L, amb_vol)
    stat = static_fx(L, static_vol)
    rum = rumble_fx(L, rumble_vol)
    amb = duck(amb, v, duck_amt)
    mix = v + amb + stat + rum
    if np.max(np.abs(mix)) > 0:
        mix = mix / np.max(np.abs(mix))
    return save_wav(mix, SR)

# ---- Gradio UI ----
demo = gr.Interface(
    fn=process,
    inputs=[
        gr.Audio(type="filepath", label="Upload WAV"),
        gr.Slider(0, 1, 0.0, 0.01, label="Dropout Probability"),
        gr.Slider(40, 400, 150, 10, label="Dropout Chunk (ms)"),
        gr.Slider(2, 16, 16, 1, label="Bit Depth (16=off)"),
        gr.Slider(0, 1, 0.0, 0.01, label="Garble Intensity"),
        gr.Slider(-30, -8, -12, 1, label="Target LUFS (AGC Gain)"),
        gr.Slider(-30, 0, -12, 0.5, label="Limiter Threshold (dB)"),
        gr.Slider(1, 20, 3, 1, label="Limiter Ratio"),
        gr.Slider(0, 1, 0.0, 0.01, label="Ducking Amount"),
        gr.Slider(0, 1, 0.0, 0.01, label="Ambience Volume"),
        gr.Slider(0, 1, 0.0, 0.01, label="Static Volume"),
        gr.Slider(0, 1, 0.0, 0.01, label="Rumble Volume"),
        gr.Slider(0, 1, 1.0, 0.01, label="Squelch Amount"),
        gr.Slider(0, 1, 0.0, 0.01, label="Mid-squelch Chance"),
        gr.Slider(-12, 12, 0, 1, label="Pitch Shift (semitones)"),
        gr.Slider(1000, 8000, 8000, 50, label="Lowpass Cutoff (Hz)"),
        gr.Checkbox(True, label="Enable Notch Filter"),
        gr.Checkbox(True, label="Enable AGC"),
        gr.Checkbox(True, label="Reduce Reverb"),
    ],
    outputs=gr.Audio(label="Processed Output"),
    title="Voice Lab FX — Chopper/Numpy/Scipy/Soundfile Master"
)

demo.launch()
