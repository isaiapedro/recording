#!/usr/bin/env python3
"""
Screen recorder — captures display to AVI using mss + OpenCV.
Use --audio to record room mic alongside video (needed for sync in video_processor.py).
After recording, pipe output to tools/generate_captions.py for auto-transcription.
"""
import argparse
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path

from storage import StorageBoundaryError, output_path, recordings_root


def parse_args():
    p = argparse.ArgumentParser(description="Screen recorder")
    p.add_argument("--monitor", type=int, default=1, help="Monitor index to record (1, 2, 3...). Default: 1")
    p.add_argument("--list-monitors", action="store_true", help="List available monitors and exit")
    p.add_argument("--res", default=None, help="Force output resolution WxH (e.g. 1920x1080). Defaults to monitor resolution.")
    p.add_argument("--fps", type=int, default=30, help="Frames per second (default: 30)")
    p.add_argument("--preview", action="store_true", help="Show live preview window (q to stop)")
    p.add_argument("--region", default=None, help="Capture region x,y,w,h (default: full target monitor)")
    p.add_argument("--lossless", action="store_true", help="Use HFYU lossless codec — larger files, no artifacts on post-zoom")
    p.add_argument("--audio", action="store_true", help="Record room mic to companion .wav for sync")
    p.add_argument("--output", default=None, help="AVI name/path below the service recording root")
    p.add_argument("--consent-confirmed", action="store_true", help="Confirm authorization to capture the selected display")
    p.add_argument("--audio-consent-confirmed", action="store_true", help="Confirm authorization for every captured voice")
    return p.parse_args()


def build_output_path(output_arg):
    if output_arg:
        return output_path(output_arg, suffix=".avi")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_path(recordings_root() / f"rec_{timestamp}.avi", suffix=".avi")


def record_audio(wav_path, stop_event, samplerate=44100):
    try:
        import numpy as np
        import sounddevice as sd
        import soundfile as sf
    except ImportError:
        print("WARNING: sounddevice/soundfile not installed — skipping audio. Run: pip install sounddevice soundfile")
        return

    chunks = []
    with sd.InputStream(samplerate=samplerate, channels=1, dtype="float32") as stream:
        while not stop_event.is_set():
            data, _ = stream.read(samplerate // 10)  # 100ms chunks
            chunks.append(data)

    if chunks:
        audio = np.concatenate(chunks)
        sf.write(str(wav_path), audio, samplerate)
        print(f"Audio saved: {wav_path}")


def record(monitor_idx, fps, output_path, preview, res=None, region=None, lossless=False, audio=False):
    try:
        import cv2
        import mss
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Recording dependencies are unavailable; install src/requirements.txt") from exc
    if fps < 1 or fps > 120:
        raise ValueError("fps must be between 1 and 120")
    with mss.mss() as sct:
        if monitor_idx < 1 or monitor_idx >= len(sct.monitors):
            print(f"Error: Monitor {monitor_idx} not found.")
            print(f"Available monitors: 1 to {len(sct.monitors) - 1}")
            sys.exit(1)

        # Target monitor coordinates from mss
        mon = sct.monitors[monitor_idx]

        if region:
            try:
                rx, ry, rw, rh = map(int, region.split(","))
            except ValueError as exc:
                raise ValueError("region must be x,y,width,height") from exc
            if rw < 1 or rh < 1 or rx < mon["left"] or ry < mon["top"] or rx + rw > mon["left"] + mon["width"] or ry + rh > mon["top"] + mon["height"]:
                raise ValueError("region must be wholly within the selected monitor")
            capture_area = {"top": ry, "left": rx, "width": rw, "height": rh}
        else:
            capture_area = mon

        if res:
            try:
                width, height = map(int, res.lower().split("x"))
            except ValueError as exc:
                raise ValueError("res must be WIDTHxHEIGHT") from exc
            if width < 1 or height < 1:
                raise ValueError("res dimensions must be positive")
        else:
            width, height = capture_area["width"], capture_area["height"]

        fourcc = cv2.VideoWriter_fourcc(*("HFYU" if lossless else "XVID"))
        writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

        stop = [False]
        audio_stop = threading.Event()

        def handle_signal(sig, frame):
            stop[0] = True
            audio_stop.set()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        codec_name = "HFYU (lossless)" if lossless else "XVID"
        print(f"Recording Monitor {monitor_idx} ({capture_area['width']}x{capture_area['height']}) → {output_path}")
        print(f"Output spec: {width}x{height} @ {fps}fps, {codec_name}")

        if audio:
            wav_path = output_path.with_suffix(".wav")
            print(f"Room mic → {wav_path}")
            audio_thread = threading.Thread(target=record_audio, args=(wav_path, audio_stop), daemon=True)
            audio_thread.start()

        print("Press Ctrl+C" + (" or 'q' in preview window" if preview else "") + " to stop recording.")

        try:
            while not stop[0]:
                img = sct.grab(capture_area)
                frame = np.array(img)[:, :, :3]  # drop alpha channel

                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height))

                writer.write(frame)

                if preview:
                    preview_w, preview_h = max(1, width // 4), max(1, height // 4)
                    cv2.imshow("Recording (q to stop)", cv2.resize(frame, (preview_w, preview_h)))
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        audio_stop.set()
                        break
        finally:
            writer.release()
            if preview:
                cv2.destroyAllWindows()
            print(f"\nSaved video: {output_path}")

            if audio:
                audio_stop.set()
                audio_thread.join()


def list_monitors():
    try:
        import mss
    except ImportError as exc:
        raise RuntimeError("Monitor discovery requires the mss dependency") from exc
    with mss.mss() as sct:
        print("\nDetected Monitors:")
        for idx, mon in enumerate(sct.monitors):
            label = "All Combined" if idx == 0 else f"Monitor {idx}"
            print(f"  [{idx}] {label}: {mon['width']}x{mon['height']} at x={mon['left']}, y={mon['top']}")
        print()


def main():
    args = parse_args()

    if args.list_monitors:
        try:
            list_monitors()
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        return

    if not args.consent_confirmed:
        print("Refusing to record: pass --consent-confirmed after confirming display-capture authorization.", file=sys.stderr)
        sys.exit(2)
    if args.audio and not args.audio_consent_confirmed:
        print("Refusing to record audio: pass --audio-consent-confirmed after confirming voice-capture authorization.", file=sys.stderr)
        sys.exit(2)

    try:
        destination = build_output_path(args.output)
        record(
            monitor_idx=args.monitor, fps=args.fps, output_path=destination,
            preview=args.preview, res=args.res, region=args.region,
            lossless=args.lossless, audio=args.audio,
        )
    except (StorageBoundaryError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
