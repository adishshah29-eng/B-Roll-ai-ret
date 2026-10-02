"""ffmpeg via the bundled imageio-ffmpeg binary (no system install). Normalise uploads and render the final cut."""
import json
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

EXE = imageio_ffmpeg.get_ffmpeg_exe()
WORK_H = 720


def run(args, timeout=3600):
    r = subprocess.run([EXE, "-hide_banner", "-y"] + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        tail = r.stderr.strip().splitlines()[-3:] if r.stderr.strip() else ["(no output)"]
        raise RuntimeError("ffmpeg failed: " + " | ".join(tail))
    return r


def probe(path) -> dict:
    """Duration / size / audio presence from `ffmpeg -i` output (imageio-ffmpeg ships no ffprobe)."""
    r = subprocess.run([EXE, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    err = r.stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    v = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", err)
    return {"duration": dur, "width": int(v.group(1)) if v else 0, "height": int(v.group(2)) if v else 0,
            "has_audio": "Audio:" in err}


def normalise(src, dst):
    """Any upload → browser-playable 720p (or smaller) H.264 + AAC with fast start. Keeps orientation."""
    run(["-i", str(src), "-vf", f"scale=-2:'min({WORK_H},ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)])


def render(aroll, slots, dst, W, H, has_audio=True):
    """Overlay each B-roll slot onto the A-roll for [start, end]; the A-roll audio plays throughout.
    slots: [{"path", "src_in", "start", "end"}]. B-roll is scaled to cover the frame and centre-cropped."""
    args = ["-i", str(aroll)]
    for s in slots:
        dur = max(0.1, s["end"] - s["start"])
        args += ["-ss", f"{max(0.0, s['src_in']):.3f}", "-t", f"{dur + 0.2:.3f}", "-i", str(s["path"])]
    chains, last = [], "[0:v]"
    for i, s in enumerate(slots, 1):
        chains.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
                      f"fps=30,tpad=stop_mode=clone:stop_duration=10,setpts=PTS-STARTPTS+{s['start']:.3f}/TB[b{i}]")
        out = f"[v{i}]"
        chains.append(f"{last}[b{i}]overlay=enable='between(t,{s['start']:.3f},{s['end']:.3f})':eof_action=pass{out}")
        last = out
    fc = ";".join(chains) if chains else "[0:v]null[vout]"
    vout = last if chains else "[vout]"
    args += ["-filter_complex", fc, "-map", vout]
    if has_audio:
        args += ["-map", "0:a?", "-c:a", "aac", "-b:a", "160k"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(dst)]
    run(args)
    return Path(dst)
