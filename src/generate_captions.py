import sys

from storage import StorageBoundaryError, recording_path, write_private_text

def format_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millies = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millies:03d}"

def transcribe(video_path):
    try:
        video_path = recording_path(video_path, must_exist=True)
    except (StorageBoundaryError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("ERROR: Faster Whisper is unavailable; install src/requirements.txt", file=sys.stderr)
        return 2

    print("Loading local Whisper large-v3-turbo model...")
    # Local-only is intentional: captured media must never trigger an implicit upload.
    model = WhisperModel("large-v3-turbo", device="auto", compute_type="default", local_files_only=True)
    
    print(f"Transcribing: {video_path}")
    # vad_filter skips silent parts to massively speed up processing
    segments, info = model.transcribe(video_path, beam_size=5, vad_filter=True)
    
    srt_path = video_path.with_suffix(".srt")
    
    captions = []
    for i, segment in enumerate(segments, start=1):
        start = format_timestamp(segment.start)
        end = format_timestamp(segment.end)
        captions.append(f"{i}\n{start} --> {end}\n{segment.text.strip()}\n")
        print(f"[{start} -> {end}] {segment.text}")
    write_private_text(srt_path, "\n".join(captions))
            
    print(f"\nSuccess! SRT file saved to: {srt_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_captions.py RECORDING_UNDER_projects/recordings")
        sys.exit(1)
    sys.exit(transcribe(sys.argv[1]) or 0)
