# K-Sounds Hub v0.4.3

## Highlights

- Smooths EQ and volume slider updates to reduce audible update artifacts.
- Moves EQ filter-chain latency to `512/48000`, matching the stable K-Sounds graph profile.
- Adds a 10-band editable EQ with 0.5 dB gain steps.
- Migrates older 8-band presets to the new 10-band layout.
- Makes EQ gain and frequency values editable from the preset dialog.
- Refines EQ preset UI spacing, value badges, slider contrast, and focus behavior.
- Keeps the soundboard architecture unchanged: independent bus/routing remains intact.

## Validation

- Python compile check passed.
- Test suite passed: 16 tests.

