# Local Video Capture Service

This service records a user-selected display and, only with a second explicit
confirmation, room microphone audio. It is a local CLI utility: it exposes no
HTTP API, webhook, background daemon, or cloud account integration.

All source media, generated captions, intermediate files, and processed output
must live under `projects/recordings/`. The tools reject absolute paths outside
that root and interpret relative paths from that root. Do not pass Personal or
Knowledge paths to these tools.

Read [PRIVACY.md](PRIVACY.md), [AUTHENTICATION.md](AUTHENTICATION.md), and
[RETENTION.md](RETENTION.md) before capture. The service behavior and tool
relationships are defined in [SYSTEM.md](SYSTEM.md) and [BEHAVIOR.md](BEHAVIOR.md).

## Local use

From `services/video/src`:

```bash
python screen_recorder.py --list-monitors
python screen_recorder.py --monitor 1 --consent-confirmed
python screen_recorder.py --monitor 1 --audio --consent-confirmed --audio-consent-confirmed
python generate_captions.py rec_YYYYMMDD_HHMMSS.avi
python video_processor.py --iphone imported/iphone.mp4 --screen rec_YYYYMMDD_HHMMSS.avi
```

The `--iphone` source is deliberately required to be staged beneath
`projects/recordings/` before processing. Captioning uses only an already
installed local Whisper model; it will not download a model or send media to a
remote service.
