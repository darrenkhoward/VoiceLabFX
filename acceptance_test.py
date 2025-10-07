import importlib, tempfile, numpy as np, soundfile as sf, os, shutil
from scipy.io import wavfile
import numpy.fft as nfft
from scipy.signal import butter, sosfiltfilt

m = importlib.import_module('app')
SR = m.SR

def make_noise(sr, sec=2.0, amp=0.08):
    x = np.random.randn(int(sr*sec)).astype(np.float32) * amp
    f = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    sf.write(f.name, x, sr)
    return f.name

def read(path):
    sr,y = wavfile.read(path)
    y = y.astype(np.float32) / (32768.0 if y.dtype.kind=='i' else 1.0)
    return sr,y

order = m.PROCESS_AUDIO_PARAM_ORDER
base = {k: m.BOJAN_PRESET_DEFAULTS.get(k) for k in order}
def build(**ov):
    cfg = dict(base); cfg.update(ov)
    return [cfg[k] for k in order]

results = []

# Prepare signals
in_wav = make_noise(32000, 2.0)         # non-48k input
ir_wav = make_noise(48000, 0.5, 0.1)    # reuse as IR & BG file
ogg_path = None
if shutil.which('ffmpeg'):
    ogg_path = ir_wav.replace('.wav', '.ogg')
    os.system(f'ffmpeg -hide_banner -loglevel error -y -i "{ir_wav}" -c:a libvorbis -q:a 3 "{ogg_path}"')

# A) ultra_high: handset IR must be skipped, bandwidth stays wide
args_with = build(quality_tier='ultra_high', handset_ir_file=ir_wav, handset_ir_gain_db=100.0,
                  bg_file=None, room_ir_file=None, normalize_output=False,
                  bandwidth_mode='Narrowband 300–3500')
args_none = build(quality_tier='ultra_high', handset_ir_file=None,
                  bg_file=None, room_ir_file=None, normalize_output=False,
                  bandwidth_mode='Narrowband 300–3500')

pa, sa = m.process_audio(in_wav, *args_with)
pb, sb = m.process_audio(in_wav, *args_none)
_, ya = read(pa); _, yb = read(pb)
L = min(len(ya), len(yb)); maxdiff = float(np.max(np.abs(ya[:L]-yb[:L]))) if L>0 else 0.0
Y = np.abs(nfft.rfft(yb)); freqs = np.fft.rfftfreq(len(yb), d=1.0/SR)
frac_high = float(Y[freqs>=10000].sum()/(Y.sum()+1e-9))
okA = (maxdiff < 1e-6) and (frac_high > 0.01)
results.append(("A_ultra_high_handsetIR_skip", okA, f"maxdiff={maxdiff:.3e}, frac_high10k={frac_high:.3f}, statusB={sb}"))

# B) Landline μ-law lives in 300–2400 Hz band (relative emphasis check)
ag = build(quality_tier='good_landline', bg_file=None, room_ir_file=None, normalize_output=False)
ab = build(quality_tier='bad_landline',  bg_file=None, room_ir_file=None, normalize_output=False)
ac = build(quality_tier='cordless',      bg_file=None, room_ir_file=None, normalize_output=False)
pg, _ = m.process_audio(in_wav, *ag); pb2, _ = m.process_audio(in_wav, *ab); pc2, _ = m.process_audio(in_wav, *ac)
_, yg = read(pg); _, yb2 = read(pb2); _, yc2 = read(pc2)
L2 = min(len(yg), len(yb2), len(yc2)); yg=yg[:L2]; yb2=yb2[:L2]; yc2=yc2[:L2]
from scipy.signal import butter, sosfiltfilt
sos_band = butter(4, [300/(SR/2), 2400/(SR/2)], btype='band', output='sos')
sos_high = butter(4, 5000/(SR/2), btype='high', output='sos')
bg = sosfiltfilt(sos_band, yg); bb = sosfiltfilt(sos_band, yb2); bc = sosfiltfilt(sos_band, yc2)
hg = sosfiltfilt(sos_high, yg); hb = sosfiltfilt(sos_high, yb2); hc = sosfiltfilt(sos_high, yc2)
diff_band_bg = float(np.mean(np.abs(bb - bg))); diff_band_cg = float(np.mean(np.abs(bc - bg)))
diff_high_bg = float(np.mean(np.abs(hb - hg))); diff_high_cg = float(np.mean(np.abs(hc - hg)))
okB = (diff_band_bg > diff_high_bg) and (diff_band_cg > diff_high_cg)
results.append(("B_landline_mulaw_band", okB, f"band_bg={diff_band_bg:.4f} vs high_bg={diff_high_bg:.4f}; band_cg={diff_band_cg:.4f} vs high_cg={diff_high_cg:.4f}"))

# C) IR double guard: same Room IR & BG IR → skip one; outputs match BG IR only case
both = build(quality_tier='standard', bg_file=ir_wav, room_ir_file=ir_wav, room_ir_gain_db=100.0,
             bg_ir_file=ir_wav, bg_ir_gain_db=100.0, normalize_output=False)
bgonly = build(quality_tier='standard', bg_file=ir_wav, room_ir_file=None,
               bg_ir_file=ir_wav, bg_ir_gain_db=100.0, normalize_output=False)
pc1, sc1 = m.process_audio(in_wav, *both); pc2, sc2 = m.process_audio(in_wav, *bgonly)
_, y1 = read(pc1); _, y2 = read(pc2)
L3 = min(len(y1), len(y2)); d = float(np.max(np.abs(y1[:L3]-y2[:L3]))) if L3>0 else 0.0
okC = d < 1e-6 and ('IR:BG only' in sc1)
results.append(("C_ir_double_guard", okC, f"maxdiff={d:.3e}, status1={sc1}"))

# D) Background decode: ogg & wav both decode; status lists chosen BG basename
wav_dec = m._decode_any_to_float32(ir_wav, SR); ogg_ok=True
if ogg_path: ogg_ok = m._decode_any_to_float32(ogg_path, SR).size>0
bgstat = build(quality_tier='standard', normalize_output=False, bg_file=ir_wav)
pbg, sdbg = m.process_audio(in_wav, *bgstat)
okD = (wav_dec.size>0) and ogg_ok and (('BG:'+os.path.basename(ir_wav)) in sdbg)
results.append(("D_bg_decode_status", okD, f"status={sdbg}"))

OK = all(flag for _,flag,_ in results)
print("PASS" if OK else "FAIL")
for name, flag, info in results:
    print(f"{name}: {'OK' if flag else 'FAIL'} — {info}")
