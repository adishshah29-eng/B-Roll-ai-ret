"""Generate TRUE-pillar test fixtures: real footage with a planted signboard overlay and a container creation date
patched into the MP4 `mvhd` atom (so the date is genuine metadata, `date_source=meta`, not a file timestamp).

    python -m eval.make_traps            # writes footage/traps/*.mp4 (synthetic fixtures; replace/add real clips freely)

Each trap is documented in TRAPS below and reused by eval/contradictions.yaml in P9.
"""
import os
import struct
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "footage" / "traps"
FONT = r"C:\Windows\Fonts\arialbd.ttf"
W, H = 640, 360

# name, base clip, start second, seconds, signboard text (None = no sign), container date, expected for the demo script
TRAPS = [
    ("trap_delhi_sign_rain", "pixabay_5278.mp4", 8, 8, "DELHI METRO", "2026-09-28",
     "rain + Delhi signboard: narration 'rain in Mumbai' -> place BAD"),
    ("trap_mumbai_sign_rain", "pixabay_5278.mp4", 30, 8, "MUMBAI LOCAL", "2026-09-30",
     "rain + Mumbai signboard, recent: 'rain in Mumbai today' -> place OK, time OK, weather OK"),
    ("trap_2019_flood", "pixabay_5278.mp4", 44, 8, None, "2019-08-10",
     "rain, recorded 2019: 'floods today' -> time WARN + label FILE · 2019"),
    ("trap_sunny_mumbai", "pixabay_91744.mp4", 2, 8, "WELCOME TO MUMBAI", "2026-09-29",
     "sunny + Mumbai sign: 'heavy rain in Mumbai' -> place OK but weather WARN/BAD"),
    ("trap_kolkata_sign_traffic", "pixabay_220283.mp4", 4, 8, "KOLKATA HOWRAH BRIDGE", "2026-09-27",
     "traffic + Kolkata sign: any Mumbai/Delhi traffic line -> place BAD"),
]


def sign_layer(text, w=W, h=H):
    """RGBA overlay with a bold white-on-blue signboard in the lower third."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    size = 54
    while size > 20:
        f = ImageFont.truetype(FONT, size)
        tw = d.textlength(text, font=f)
        if tw <= w - 80:
            break
        size -= 4
    box = (20, h - 112, w - 20, h - 32)
    d.rectangle(box, fill=(18, 62, 140, 255), outline=(255, 255, 255, 255), width=3)
    d.text(((w - tw) / 2, h - 108 + (76 - size) / 2 - 6), text, font=f, fill=(255, 255, 255, 255))
    return np.array(img)


def patch_creation_date(path: Path, iso: str):
    """Write the creation/modification time into the first `mvhd` atom (seconds since 1904-01-01)."""
    secs = int((datetime.fromisoformat(iso) - datetime(1904, 1, 1)).total_seconds())
    data = bytearray(path.read_bytes())
    i = data.find(b"mvhd")
    if i < 0:
        raise RuntimeError("no mvhd atom")
    ver = data[i + 4]
    if ver == 0:
        struct.pack_into(">II", data, i + 8, secs, secs)
    else:
        struct.pack_into(">QQ", data, i + 8, secs, secs)
    path.write_bytes(bytes(data))


def make(name, base, start_s, dur_s, sign, date):
    src = ROOT / "footage" / base
    if not src.exists():
        print(f"skip {name}: base clip {base} missing")
        return None
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(start_s * fps))
    dst = OUT / f"{name}.mp4"
    w = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    layer = sign_layer(sign) if sign else None
    n = 0
    for _ in range(int(dur_s * fps)):
        ok, fr = cap.read()
        if not ok:
            break
        fr = cv2.resize(fr, (W, H))
        if layer is not None:
            a = layer[:, :, 3:4].astype(np.float32) / 255.0
            fr = (fr.astype(np.float32) * (1 - a) + layer[:, :, 2::-1].astype(np.float32) * a).astype(np.uint8)
        w.write(fr)
        n += 1
    w.release()
    cap.release()
    patch_creation_date(dst, f"{date}T12:00:00")
    return dst, n


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for t in TRAPS:
        r = make(*t[:6])
        print(("made " + r[0].name + f" ({r[1]} frames)") if r else "-", "|", t[6])
