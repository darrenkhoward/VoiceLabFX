# Deploy VoiceLabFX to Hugging Face Spaces

## Quick Deploy (Recommended)

### Step 1: Login to Hugging Face
```bash
huggingface-cli login
```
Enter your token when prompted.

### Step 2: Create a New Space
Go to: https://huggingface.co/new-space

- **Owner:** dkh666
- **Space name:** voicelabfx (or your choice)
- **License:** Choose appropriate license
- **SDK:** Gradio
- **Space hardware:** CPU basic (free tier)
- **Visibility:** Public or Private

Click "Create Space"

### Step 3: Clone the Space Repository
```bash
cd /Users/darrenhoward/Desktop/desk\ stuff/VoiceLabFX_LiveDeploy
git clone https://huggingface.co/spaces/dkh666/voicelabfx
```

### Step 4: Copy Files to Space
```bash
cp VoiceLabFX_HuggingFace/* voicelabfx/
cp -r VoiceLabFX_HuggingFace/assets voicelabfx/
```

### Step 5: Setup Git LFS (for large audio files)
```bash
cd voicelabfx
git lfs install
git lfs track "*.ogg"
git lfs track "*.wav"
git lfs track "*.mp3"
```

### Step 6: Commit and Push
```bash
git add .
git commit -m "Initial VoiceLabFX deployment"
git push
```

### Step 7: Wait for Build
- Go to: https://huggingface.co/spaces/dkh666/voicelabfx
- Wait 2-5 minutes for the Space to build
- Your app will be live!

---

## Alternative: Upload via Web Interface

### Step 1: Create Space
1. Go to: https://huggingface.co/new-space
2. Fill in details (name: voicelabfx, SDK: Gradio)
3. Click "Create Space"

### Step 2: Upload Files
1. Click "Files" tab
2. Click "Add file" → "Upload files"
3. Upload these files:
   - `app.py`
   - `presets.json`
   - `requirements.txt`
   - `README.md`
   - `.gitattributes`
4. Upload `assets/` folder (may need to do in batches)

### Step 3: Wait for Build
Space will automatically build and deploy!

---

## Troubleshooting

### "Space build failed"
- Check logs in the Space's "Logs" tab
- Common issue: Missing dependencies in requirements.txt

### "Out of memory"
- Upgrade to CPU upgrade (small fee) or GPU space
- Go to Space Settings → Change hardware

### "Files too large"
- Make sure Git LFS is enabled
- Check `.gitattributes` includes your file types

### "App won't start"
- Check that `app.py` exists (not `app_editor_full_ui.py`)
- Verify requirements.txt has all dependencies

---

## Your Space URL

Once deployed, your Space will be at:
**https://huggingface.co/spaces/dkh666/voicelabfx**

Share this link with your bosses!

---

## Notes

- **Free tier:** CPU basic (should work fine)
- **Build time:** 2-5 minutes
- **Persistent:** Space stays up 24/7
- **Updates:** Just push new commits to update

---

## Quick Commands Reference

```bash
# Login
huggingface-cli login

# Create space (via web)
# https://huggingface.co/new-space

# Clone
git clone https://huggingface.co/spaces/dkh666/voicelabfx

# Setup LFS
cd voicelabfx
git lfs install
git lfs track "*.ogg" "*.wav" "*.mp3"

# Deploy
git add .
git commit -m "Deploy VoiceLabFX"
git push
```

---

## Support

If you run into issues, check:
1. Hugging Face Spaces documentation: https://huggingface.co/docs/hub/spaces
2. Gradio documentation: https://gradio.app/docs/
3. Space logs for error messages

