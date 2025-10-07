---
title: VoiceLabFX
emoji: 📞
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 4.20.0
app_file: app.py
pinned: false
---

# VoiceLabFX - Phone Call Audio Processor

Transform clean studio audio into realistic phone call simulations for radio production.

## Features

- **Multiple Quality Tiers:** Standard, High, Ultra High
- **Room Acoustics:** Bathroom reverb and other impulse responses
- **Background Mixing:** Street noise, party music with ducking
- **Network Artifacts:** Dropouts, garble, jitter, RF noise
- **Realistic Presets:** Spotty Service, Bathroom Caller, Street Sounds

## How to Use

1. **Upload your audio file** (WAV, MP3, OGG, etc.)
2. **Select a preset** from the dropdown
3. **Adjust sliders** if needed (all show true values)
4. **Click "Process Audio"**
5. **Download the result**

## Presets

### Spotty Service
Poor cellular connection with network artifacts

### Bathroom Caller
Indoor caller with bathroom reverb and party music in background

### Street Sounds
Outdoor caller with traffic and urban ambience

## Technical Details

- **Sample Rate:** 48kHz processing
- **Sliders:** Show true applied values (no hidden multipliers)
- **Quality Tiers:** Bandwidth filtering only (250-6000 Hz to 20-24000 Hz)
- **Network Artifacts:** Realistic packet loss, garble, jitter simulation

## Credits

Developed for radio production by Darren Howard.

