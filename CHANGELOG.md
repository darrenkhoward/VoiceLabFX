# VoiceLabFX Changelog

All notable changes to this project will be documented in this file.

## [2025-09-23] - UI and Audio Processing Improvements

### Added
- Ducking slider now visible on all presets (not just "Street Sounds")
- Enhanced warp effect with stronger time-stretching (±25% vs previous ±9%)

### Changed
- **Ducking Control Visibility**: Removed `"visible_in":["Street Sounds"]` restriction from ducking slider
  - **Rationale**: Users can upload background audio on any preset, so ducking controls should always be available
  - **Impact**: Ducking slider now appears on "Cellphone Spotty" and "Dry/Bypass" presets when background audio is present

- **Warp Effect Strength**: Increased time-stretching factor from ±9% to ±25%
  - **Rationale**: Previous ±9% was too subtle to be audible in most voice recordings
  - **Impact**: Warp effect is now clearly audible when enabled, providing obvious time-domain artifacts

### Fixed
- **Code Quality Improvements**:
  - Removed unused `np_rand` variable in `process_pipeline` function
  - Replaced inefficient JSON round-trip serialization with `copy.deepcopy()` in `apply_overrides`
  - Simplified chain copying in `chain_for` function using `.copy()` instead of JSON serialization
  - Added missing `copy` import to support improved deep copying
  - Improved code formatting and spacing consistency

### Technical Details
- **File Modified**: `presets.json` - Line 70: Removed visibility restriction from ducking slider
- **File Modified**: `app.py` - Line 176: Changed warp factor from `±0.09` to `±0.25`
- **File Modified**: `app.py` - Lines 4-5, 307-310, 402-418: Code quality improvements

### Testing Recommendations
1. Test ducking slider visibility on all three presets
2. Upload background audio on "Cellphone Spotty" preset and verify ducking control works
3. Test warp effect at maximum settings to confirm increased audibility
4. Verify all existing functionality remains intact after code cleanup

---

## Previous Changes
(No previous changelog entries - this is the first documented version)
