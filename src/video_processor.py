#!/usr/bin/env python3
"""
Video processor pipeline — syncs iPhone + screen recording, filters both, cuts both.

Steps:
  1. Sync: cross-correlate iPhone audio vs screen room mic → compute offset
  2. Trim both to same start point
  3. Filter iPhone (talking head preset: sharpen + contrast + warm color shift)
  4. Filter screen recording (screencast preset: aggressive sharpen + contrast + gamma)
  5. Auto-editor on iPhone audio → export cut timeline
  6. Apply same cut timeline to screen recording
  7. Output session folder with two DaVinci-ready files

Usage:
    python tools/video_processor.py --iphone footage.mp4 --screen rec_20260529.avi

    # screen recording must have companion .wav (record with: screen_recorder.py --audio)
    # skip sync if both started at the same time:
    python tools/video_processor.py --iphone footage.mp4 --screen rec.avi --no-sync
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from storage import StorageBoundaryError, recording_path, recordings_root, write_private_text


# ── Filter presets ────────────────────────────────────────────────────────────

FILTER_IPHONE = ",".join([
    "unsharp=5:5:0.8:5:5:0",              # light sharpening (talking head)
    "eq=contrast=1.15:saturation=1.08:gamma=0.95",
    "colorbalance=rs=0.03:gs=0:bs=-0.04",  # warm color shift
])

FILTER_SCREEN = ",".join([
    "unsharp=5:5:1.5:5:5:0",              # aggressive sharpening (code text)
    "eq=contrast=1.1:gamma=1.05:saturation=1.05",
])


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd, desc=""):
    label = desc or Path(cmd[0]).name
    print(f"  → {label}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"\nERROR ({label}):\n{result.stderr[-800:]}", file=sys.stderr)
        sys.exit(1)
    return result


def extract_audio(video_path, wav_path):
    run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ar", "44100", "-ac", "1", str(wav_path)],
        f"extract audio ← {video_path.name}",
    )


def compute_sync_offset(wav_iphone, wav_screen):
    """
    Returns offset in seconds (positive = iPhone starts later, trim iPhone).
    Uses first 60s of audio to avoid memory issues on long recordings.
    """
    try:
        import numpy as np
        import scipy.io.wavfile as wavfile
        from scipy.signal import correlate
    except ImportError as exc:
        raise RuntimeError("Sync requires numpy and scipy from src/requirements.txt") from exc

    rate_a, data_a = wavfile.read(str(wav_iphone))
    rate_b, data_b = wavfile.read(str(wav_screen))

    def to_mono_float(data):
        a = data.astype(np.float32)
        if a.ndim > 1:
            a = a.mean(axis=1)
        peak = np.max(np.abs(a))
        return a / (peak + 1e-9)

    a = to_mono_float(data_a)[: 60 * rate_a]
    b = to_mono_float(data_b)[: 60 * rate_b]

    corr = correlate(a, b, mode="full")
    lag = np.argmax(corr) - (len(b) - 1)
    return lag / rate_a


def trim_video(src, dst, start_sec):
    run(
        ["ffmpeg", "-y", "-ss", f"{start_sec:.6f}", "-i", str(src), "-c", "copy", str(dst)],
        f"trim {src.name} by {start_sec:.3f}s",
    )


def apply_filter(src, dst, vf):
    run(
        ["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-c:a", "copy", str(dst)],
        f"filter {src.name}",
    )


def auto_edit_export_timeline(src, timeline_json):
    """Run auto-editor on src, export JSON cut timeline."""
    out_dir = timeline_json.parent
    run(
        [
            "auto-editor", str(src),
            "--no-open",
            "--margin", "0.4sec",
            "--silent-speed", "8",
            "--export", "json",
            "--output-dir", str(out_dir),
        ],
        f"auto-editor: detect cuts ← {src.name}",
    )
    # auto-editor outputs <stem>.json — find and rename
    candidates = [f for f in out_dir.glob("*.json") if f != timeline_json]
    if not candidates:
        print("ERROR: auto-editor produced no JSON output. Check auto-editor version.", file=sys.stderr)
        sys.exit(1)
    candidates[0].rename(timeline_json)


def auto_edit_apply_timeline(src, timeline_json, dst):
    """Apply a previously exported timeline to a different source file."""
    run(
        [
            "auto-editor", str(src),
            "--no-open",
            "--edit-based", f"timeline:{timeline_json}",
            "--output", str(dst),
        ],
        f"apply cuts → {dst.name}",
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Sync, filter, and cut iPhone + screen recording")
    p.add_argument("--iphone", required=True, help="iPhone talking head video (mp4/mov)")
    p.add_argument("--screen", required=True, help="Screen recording AVI (needs companion .wav unless --no-sync)")
    p.add_argument("--no-sync", action="store_true", help="Skip sync — assume both recordings started simultaneously")
    args = p.parse_args()

    try:
        iphone = recording_path(args.iphone, must_exist=True)
        screen = recording_path(args.screen, must_exist=True)
    except (StorageBoundaryError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
    screen_wav = screen.with_suffix(".wav")

    if not args.no_sync and not screen_wav.exists():
        print(
            f"ERROR: Room mic WAV not found: {screen_wav}\n"
            "Record screen with --audio flag, or use --no-sync if recordings started simultaneously.",
            file=sys.stderr,
        )
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = recordings_root() / f"session_{ts}"
    tmp = session / "tmp"
    session.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(exist_ok=True)

    print(f"\nSession: {session}\n")

    # ── 1. SYNC ───────────────────────────────────────────────────────────────
    iphone_src = iphone
    screen_src = screen

    if not args.no_sync:
        print("[1/5] Computing sync offset via audio cross-correlation...")
        iphone_wav = tmp / "iphone_audio.wav"
        extract_audio(iphone, iphone_wav)

        try:
            offset = compute_sync_offset(iphone_wav, screen_wav)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(2)
        direction = "iPhone starts later — trimming iPhone" if offset > 0 else "screen starts later — trimming screen"
        print(f"      Offset: {offset:+.3f}s  ({direction})")
        write_private_text(session / "sync_offset.txt",
            f"offset_seconds={offset:.6f}\niphone={iphone}\nscreen={screen}\n"
        )

        if abs(offset) > 0.033:  # ignore sub-frame differences (<1 frame at 30fps)
            if offset > 0:
                iphone_src = tmp / f"iphone_trimmed{iphone.suffix}"
                trim_video(iphone, iphone_src, offset)
            else:
                screen_src = tmp / "screen_trimmed.avi"
                trim_video(screen, screen_src, abs(offset))
    else:
        print("[1/5] Sync skipped — assuming simultaneous start.")

    # ── 2. FILTER IPHONE ─────────────────────────────────────────────────────
    print("\n[2/5] Filtering iPhone (talking head: sharpen + contrast + warm)...")
    iphone_filtered = tmp / f"iphone_filtered{iphone.suffix}"
    apply_filter(iphone_src, iphone_filtered, FILTER_IPHONE)

    # ── 3. FILTER SCREEN ─────────────────────────────────────────────────────
    print("\n[3/5] Filtering screen (screencast: aggressive sharpen + gamma)...")
    screen_filtered = tmp / "screen_filtered.avi"
    apply_filter(screen_src, screen_filtered, FILTER_SCREEN)

    # ── 4. AUTO-EDITOR: DETECT CUTS FROM IPHONE AUDIO ────────────────────────
    print("\n[4/5] Detecting pauses from iPhone audio (auto-editor)...")
    timeline_json = session / "timeline.json"
    auto_edit_export_timeline(iphone_filtered, timeline_json)

    # ── 5. APPLY CUTS TO BOTH ────────────────────────────────────────────────
    print("\n[5/5] Applying cuts to both files...")
    iphone_cut = session / f"iphone_cut{iphone.suffix}"
    screen_cut = session / "screen_cut.avi"
    auto_edit_apply_timeline(iphone_filtered, timeline_json, iphone_cut)
    auto_edit_apply_timeline(screen_filtered, timeline_json, screen_cut)

    print(f"\n{'─'*50}")
    print(f"Done. Import into DaVinci Resolve as multicam:\n")
    print(f"  {iphone_cut}")
    print(f"  {screen_cut}")
    print(f"\n  Cut timeline: {timeline_json}")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    main()
