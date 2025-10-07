# VoiceLabFX - Radio Caller Effects Processor

Professional audio processing system for creating realistic phone caller effects for radio production.

## 🎯 Overview

VoiceLabFX creates unique, realistic fake phone callers for radio stations. Each time you process the same voice file, it produces a different-sounding caller with randomized background sounds, network artifacts, and event timing.

## 🎛️ Features

- **3 Production-Ready Presets:**
  - **Spotty Caller** - Poor cellular connection with heavy network artifacts
  - **Street Sounds** - Outdoor caller with traffic and urban ambience
  - **Bathroom Caller** - Indoor caller with bathroom reverb and muffled party music

- **Randomized Processing** - Same input produces unique outputs every time
- **Broadcast-Ready** - LUFS normalization for consistent loudness
- **Easy-to-Use Interface** - Simple preset selection with minimal controls

## 📋 System Requirements

- Python 3.8 or higher
- ffmpeg (for audio decoding)
- 2GB RAM minimum
- Linux, macOS, or Windows

## 🚀 Installation

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install ffmpeg

**Ubuntu/Debian:**
```bash
sudo apt-get install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
Download from https://ffmpeg.org/

## 💻 Usage

### 1. Start the Application

```bash
python app_simple.py
```

### 2. Open in Browser

Navigate to: `http://localhost:7861`

### 3. Process Audio

1. Upload a voice recording (WAV, MP3, OGG, FLAC)
2. Select a preset from the dropdown
3. Adjust effect intensity and output level
4. Click "Process Audio"
5. Download the processed result

### 4. Preset-Specific Controls

**Street Sounds:**
- Background Level slider (traffic/urban ambience volume)

**Bathroom Caller:**
- Reverb Amount slider (bathroom acoustics)
- Party Music Level slider (muffled music from next room)

## 🎚️ Presets Configuration

Presets are defined in `presets.json`. Each preset includes:

- **Phone quality tier** (ultra_low, low, standard, high, ultra_high)
- **Network artifacts** (dropouts, jitter, garble, packet loss)
- **Background audio** (ambience loops with random start points)
- **Events** (car horns, dogs, babies with randomized timing)
- **Room acoustics** (impulse response convolution)
- **Output normalization** (target LUFS level)

## 🔧 For Developers

### Run Tests

**Quick functionality test:**
```bash
python smoke_test.py
```

**Comprehensive validation:**
```bash
python acceptance_test.py
```

### Core Files

- `app.py` - Core audio processing engine
- `app_simple.py` - Simplified production UI
- `presets.json` - Preset configurations
- `assets/` - Audio assets (IRs, backgrounds, events)

## 📦 Asset Files

The `assets/` folder contains:

- **irs/** - Impulse responses for room acoustics
- **backgrounds/** - Ambient sound loops (street noise, etc.)
- **car_horns/** - Traffic event sounds
- **dog_barks/** - Dog bark events
- **baby_cries/** - Baby cry events
- **car_interiors/** - Car interior ambience
- **Party Music/** - Party music backgrounds

## 🎯 Key Features

### Randomization

Every processing run produces unique output:
- Background audio starts at random position
- Events (horns, dogs, babies) occur at random times
- Network artifacts happen at different moments
- Random file selection when multiple backgrounds available

### LUFS Normalization

All outputs are normalized to broadcast-standard loudness levels (default: -18 LUFS) for consistent volume across different processed files.

## 📞 Support

For technical support or questions, contact your system administrator.

---

_VoiceLabFX - Part of the Voice Lab Initiative for iHeartMedia Premiere Networks_
