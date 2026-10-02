"""Split the A-roll into clips from BOTH signals.
  video : scene cuts (colour-histogram change, 4 samples/s) + a filmstrip of frames for the timeline
  audio : speech segments from Whisper, pauses between them
  units : speech segments split wherever the picture cuts, each with its text, time and a keyframe
"""
import cv2
import numpy as np

SAMPLE_FPS = 4.0
CUT_THR = 0.45           # Bhattacharyya distance between consecutive histograms that counts as a cut
MIN_SHOT_S = 0.8
STRIP_EVERY_S = 2.0
STRIP_W = 192
PAUSE_MIN_S = 0.4


def video_scan(path, out_dir) -> dict:
    """-> {"cuts": [t...], "shots": [{start,end}], "strip": [{"t","file"}]}; filmstrip jpgs written to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    step = max(1, int(round(fps / SAMPLE_FPS)))
    prev, last_cut, next_strip = None, 0.0, 0.0
    cuts, strip, i = [], [], 0
    try:
        while True:
            if not cap.grab():
                break
            if i % step == 0:
                ok, fr = cap.retrieve()
                if not ok:
                    break
                t = i / fps
                small = cv2.resize(fr, (160, 90), interpolation=cv2.INTER_AREA)
                hist = cv2.calcHist([cv2.cvtColor(small, cv2.COLOR_BGR2HSV)], [0, 1], None, [16, 8], [0, 180, 0, 256])
                cv2.normalize(hist, hist, 1.0, 0.0, cv2.NORM_L1)
                if prev is not None and cv2.compareHist(prev, hist, cv2.HISTCMP_BHATTACHARYYA) > CUT_THR \
                        and t - last_cut >= MIN_SHOT_S:
                    cuts.append(round(t, 2))
                    last_cut = t
                prev = hist
                if t >= next_strip:
                    h, w = fr.shape[:2]
                    th = cv2.resize(fr, (STRIP_W, max(1, int(h * STRIP_W / w))), interpolation=cv2.INTER_AREA)
                    name = f"f{len(strip):04d}.jpg"
                    cv2.imwrite(str(out_dir / name), th, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    strip.append({"t": round(t, 2), "file": name})
                    next_strip += STRIP_EVERY_S
            i += 1
    finally:
        cap.release()
    dur = i / fps if i else (n_frames / fps if fps else 0.0)
    edges = [0.0] + cuts + [dur]
    return {"cuts": cuts, "shots": [{"start": round(a, 2), "end": round(b, 2)} for a, b in zip(edges, edges[1:]) if b > a],
            "strip": strip, "duration": round(dur, 2)}


def _nearest_frame(strip: list, t: float):
    return min(strip, key=lambda f: abs(f["t"] - t))["file"] if strip else None


def build_units(segments: list, cuts: list, strip: list, duration: float) -> list:
    """Speech segments, split at scene cuts that fall inside them, plus the pauses between segments.
    unit = {id, kind: speech|pause, start, end, text, frame}"""
    units = []
    for s in segments:
        inner = [c for c in cuts if s["start"] + 0.4 < c < s["end"] - 0.4]
        edges = [s["start"]] + inner + [s["end"]]
        words = s.get("words") or []
        for a, b in zip(edges, edges[1:]):
            if inner and words:
                txt = " ".join(w["w"] for w in words if a - 0.01 <= (w["s"] + w["e"]) / 2 < b + 0.01).strip() or s["text"]
            else:
                txt = s["text"]
            units.append({"kind": "speech", "start": round(a, 2), "end": round(b, 2), "text": txt,
                          "frame": _nearest_frame(strip, (a + b) / 2)})
    segs = sorted(segments, key=lambda s: s["start"])
    gaps = [(0.0, segs[0]["start"])] if segs and segs[0]["start"] >= PAUSE_MIN_S else []
    gaps += [(a["end"], b["start"]) for a, b in zip(segs, segs[1:]) if b["start"] - a["end"] >= PAUSE_MIN_S]
    if segs and duration - segs[-1]["end"] >= PAUSE_MIN_S:
        gaps.append((segs[-1]["end"], duration))
    for a, b in gaps:
        units.append({"kind": "pause", "start": round(a, 2), "end": round(b, 2), "text": "", "frame": _nearest_frame(strip, (a + b) / 2)})
    units.sort(key=lambda u: u["start"])
    for i, u in enumerate(units):
        u["id"] = i
    return units
