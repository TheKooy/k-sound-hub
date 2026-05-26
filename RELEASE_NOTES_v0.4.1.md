# K-Sounds Hub v0.4.1

Stability release for live gaming/audio use.

## Fixes

- Fixed MICRO mute path so the exported virtual microphone is muted reliably in apps such as Discord.
- Fixed MICRO mute also silencing MIC OUT monitoring as expected.
- Reduced live meter overhead during real gaming/audio use.
- Stopped UI-only meter capture probes when the window is hidden/minimized or meters are disabled.
- Reduced meter polling pressure by using safer capture chunks/latency.
- Fixed MIC OUT soundboard add/remove routing behavior.
- Prevented soundboard Qt player freeze cases.
- Avoided QtMultimedia device enumeration for direct soundboard playback.
- Cleaned up external soundboard ffmpeg/pacat playback processes with timeout-based cleanup.
- Fixed CI QtMultimedia PulseAudio dependency.

## Notes

- For heavy K-Sounds + game + voice chat setups, PipeWire quantum `512 / 48000` is recommended for better crackle resistance.
- Use the release assets attached to the GitHub release for installation instead of GitHub automatic source archives.
