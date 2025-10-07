#!/bin/bash
# Revert Background Randomization Changes
# Created: 2025-09-30 23:31:07
# 
# This script reverts all changes made for background start point randomization
# and restores the files to their state before the changes.

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔄 Reverting Background Randomization Changes"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Stop the running app
echo "⏹️  Stopping app on port 7860..."
PID=$(lsof -ti :7860 2>/dev/null)
if [ -n "$PID" ]; then
    kill -9 $PID 2>/dev/null
    echo "   ✅ Stopped process $PID"
else
    echo "   ℹ️  No process running on port 7860"
fi
echo ""

# Restore main app.py
echo "📁 Restoring app.py..."
if [ -f "versions/app_20250930_233107_before_bg_randomization.py" ]; then
    cp versions/app_20250930_233107_before_bg_randomization.py app.py
    echo "   ✅ Restored from: versions/app_20250930_233107_before_bg_randomization.py"
else
    echo "   ❌ ERROR: Backup file not found!"
    exit 1
fi
echo ""

# Restore production app.py
echo "📁 Restoring VoiceLabFX_Production/app.py..."
if [ -f "versions/app_production_20250930_233107_before_bg_randomization.py" ]; then
    cp versions/app_production_20250930_233107_before_bg_randomization.py VoiceLabFX_Production/app.py
    echo "   ✅ Restored from: versions/app_production_20250930_233107_before_bg_randomization.py"
else
    echo "   ❌ ERROR: Backup file not found!"
    exit 1
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Revert Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "To restart the app, run:"
echo "  python3 app_editor_full_ui.py"
echo ""

