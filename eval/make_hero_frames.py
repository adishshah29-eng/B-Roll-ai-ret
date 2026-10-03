"""Cut the landing-page hero video into scroll-scrub frames.   python -m eval.make_hero_frames
Output: app/static/media/hero/{d,m}/f001.webp ... + poster.jpg   (see manifest.json)
Needs only the ffmpeg bundled with imageio-ffmpeg. Change FPS to trade smoothness for download size."""
import json
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app/static/media/hero.mp4"
OUT = ROOT / "app/static/media/hero"
FPS = 15
DELOGO = "delogo=x=1695:y=855:w=90:h=90"      # fixed generator mark, bottom right of the 1920x1080 source
SETS = {"d": (1600, 72), "m": (800, 66)}


def run(*args):
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", *map(str, args)], check=True)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    for name, (w, q) in SETS.items():
        (OUT / name).mkdir(parents=True)
        run("-i", SRC, "-an", "-vf", f"{DELOGO},fps={FPS},scale={w}:-2:flags=lanczos", "-c:v", "libwebp",
            "-quality", q, "-compression_level", 6, OUT / name / "f%03d.webp")
    run("-ss", 0, "-i", SRC, "-frames:v", 1, "-vf", f"{DELOGO},scale=1600:-2", "-q:v", 3, OUT / "poster.jpg")
    manifest = {"source": "app/static/media/hero.mp4 (audio dropped)", "fps": FPS, "pattern": "f%03d.webp", "poster": "poster.jpg",
                "note": "fixed generator mark removed with ffmpeg delogo; regenerate with python -m eval.make_hero_frames", "sets": {}}
    for name, (w, q) in SETS.items():
        files = sorted((OUT / name).glob("*.webp"))
        kb = sum(f.stat().st_size for f in files) // 1024
        manifest["frames"] = len(files)
        manifest["sets"][name] = {"width": w, "height": round(w * 9 / 16), "quality": q, "total_kb": kb}
        print(name, len(files), "frames", kb, "KB")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
