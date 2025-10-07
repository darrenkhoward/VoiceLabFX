import app, tempfile, numpy as np, soundfile as sf

SR = app.SR
x = np.random.randn(int(SR*0.5)).astype(np.float32) * 0.05
f = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
sf.write(f.name, x, SR)

args = [app.BOJAN_PRESET_DEFAULTS[k] for k in app.PROCESS_AUDIO_PARAM_ORDER]
out, status = app.process_audio(f.name, *args)
print("status:", status)
print("output file:", out)
