# VoiceLabFX Deployment Guide

## 📦 Package Contents

This deployment package contains:

### Core Application Files (9)
- `app.py` - Core audio processing engine
- `app_simple.py` - Production UI
- `presets.json` - Preset configurations
- `requirements.txt` - Python dependencies
- `README.md` - User documentation
- `.gitignore` - Git ignore rules
- `smoke_test.py` - Quick functionality test
- `acceptance_test.py` - Comprehensive validation
- `DEPLOYMENT.md` - This file

### Assets Folder
- `assets/irs/` - Impulse responses (9 files)
- `assets/backgrounds/` - Street ambience (5 files)
- `assets/car_horns/` - Traffic events (27 files)
- `assets/dog_barks/` - Dog events (2 files)
- `assets/baby_cries/` - Baby events (1 file)
- `assets/car_interiors/` - Car ambience (4 files)
- `assets/Party Music/` - Party backgrounds (8 files)

---

## 🖥️ Server Deployment (Animus Server)

### Prerequisites

1. **Python 3.8+** installed
2. **ffmpeg** installed
3. **2GB RAM** minimum
4. **Port 7861** available (or configure different port)

### Installation Steps

#### 1. Upload Package to Server

```bash
# Upload via SCP
scp -r VoiceLabFX_Production/ user@animus-server:/path/to/deployment/

# Or use SFTP, rsync, etc.
```

#### 2. Install System Dependencies

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install python3 python3-pip ffmpeg

# CentOS/RHEL
sudo yum install python3 python3-pip ffmpeg
```

#### 3. Install Python Dependencies

```bash
cd /path/to/deployment/VoiceLabFX_Production/
pip3 install -r requirements.txt
```

#### 4. Test Installation

```bash
# Quick test
python3 smoke_test.py

# Should output: "status: OK · Codec: ..."
```

#### 5. Start Application

```bash
# Start on default port (7861)
python3 app_simple.py

# Or specify custom port
# Edit app_simple.py line 315 to change port number
```

#### 6. Verify Application

Open browser to: `http://server-ip:7861`

You should see the VoiceLabFX interface.

---

## 🔧 Configuration

### Change Port Number

Edit `app_simple.py` line 315:

```python
# Change from:
demo.launch(server_name="0.0.0.0", server_port=7861, share=False)

# To your desired port:
demo.launch(server_name="0.0.0.0", server_port=8080, share=False)
```

### Change LUFS Target

Edit `presets.json` for each preset's output section:

```json
"output": {
  "target_lufs": -18  // Change to -16, -20, etc.
}
```

### Add New Presets

Edit `presets.json` and add new preset entries. See existing presets for structure.

---

## 🌐 Web Integration

### Option 1: Direct Access

Users access directly: `http://animus-server:7861`

### Option 2: Reverse Proxy (Recommended)

Use nginx or Apache to proxy requests:

**nginx example:**
```nginx
location /voicelabfx/ {
    proxy_pass http://localhost:7861/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

### Option 3: Subdomain

Point subdomain to server: `voicelabfx.radiostation.com`

---

## 🔒 Security Considerations

### 1. Firewall Rules

```bash
# Allow only from specific IPs
sudo ufw allow from 192.168.1.0/24 to any port 7861

# Or allow from anywhere (less secure)
sudo ufw allow 7861
```

### 2. Authentication

Gradio supports basic auth. Edit `app_simple.py` line 315:

```python
demo.launch(
    server_name="0.0.0.0", 
    server_port=7861, 
    share=False,
    auth=("username", "password")  # Add this line
)
```

### 3. HTTPS

Use reverse proxy (nginx/Apache) with SSL certificate for HTTPS.

---

## 🚀 Production Deployment

### Run as System Service (systemd)

Create `/etc/systemd/system/voicelabfx.service`:

```ini
[Unit]
Description=VoiceLabFX Audio Processor
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/VoiceLabFX_Production
ExecStart=/usr/bin/python3 app_simple.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable voicelabfx
sudo systemctl start voicelabfx
sudo systemctl status voicelabfx
```

### Monitor Logs

```bash
# View service logs
sudo journalctl -u voicelabfx -f

# Or if running manually
python3 app_simple.py 2>&1 | tee voicelabfx.log
```

---

## 🧪 Testing

### Smoke Test

```bash
python3 smoke_test.py
```

Expected output: `status: OK · Codec: ...`

### Acceptance Test

```bash
python3 acceptance_test.py
```

Expected output: `PASS` with all tests showing `OK`

### Manual Test

1. Start application
2. Upload test voice file
3. Try each preset:
   - Spotty Caller
   - Street Sounds
   - Bathroom Caller
4. Verify audio output sounds correct
5. Process same file 3 times - outputs should differ

---

## 🐛 Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'gradio'"

**Solution:** Install dependencies
```bash
pip3 install -r requirements.txt
```

### Issue: "ffmpeg not found"

**Solution:** Install ffmpeg
```bash
sudo apt-get install ffmpeg  # Ubuntu/Debian
```

### Issue: "Port 7861 already in use"

**Solution:** Change port in `app_simple.py` or kill existing process
```bash
lsof -ti :7861 | xargs kill -9
```

### Issue: "No such file or directory: 'assets/...'"

**Solution:** Ensure assets folder is in same directory as app files

### Issue: Audio processing fails

**Solution:** Check logs for specific error. Common causes:
- Missing asset files
- Incorrect file paths in presets.json
- Insufficient memory
- Corrupted input audio

---

## 📊 Performance

### Expected Processing Times

- 30-second voice clip: ~5-10 seconds
- 2-minute voice clip: ~15-30 seconds

### Resource Usage

- RAM: ~500MB-1GB per concurrent user
- CPU: Moderate (depends on audio length)
- Disk: Minimal (temp files auto-cleaned)

### Scaling

For multiple concurrent users:
- Increase server RAM (2GB per 2-3 concurrent users)
- Consider load balancing multiple instances
- Monitor CPU usage

---

## 🔄 Updates

### Updating Presets

1. Edit `presets.json`
2. Restart application
3. Refresh browser

### Updating Code

1. Backup current installation
2. Replace `app.py` and/or `app_simple.py`
3. Restart application
4. Run tests to verify

### Adding Assets

1. Add files to appropriate `assets/` subfolder
2. Update `presets.json` to reference new files
3. Restart application

---

## 📞 Support

For technical issues:
1. Check logs: `sudo journalctl -u voicelabfx -f`
2. Run tests: `python3 smoke_test.py`
3. Verify all dependencies installed
4. Contact system administrator

---

## ✅ Deployment Checklist

- [ ] Server meets system requirements
- [ ] Python 3.8+ installed
- [ ] ffmpeg installed
- [ ] All files uploaded to server
- [ ] Dependencies installed (`pip3 install -r requirements.txt`)
- [ ] Smoke test passes
- [ ] Application starts without errors
- [ ] Can access UI in browser
- [ ] All 3 presets work correctly
- [ ] Firewall configured (if needed)
- [ ] Service configured for auto-start (optional)
- [ ] Monitoring/logging configured
- [ ] Backup plan in place

---

_VoiceLabFX Deployment Guide v1.0_

