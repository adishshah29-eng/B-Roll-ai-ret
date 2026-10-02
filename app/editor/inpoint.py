"""Where in the clip should the cutaway start?  A stock clip is 10-40 s and its thumbnail is one frame, so "start at 0.0" can
land on a title, a fade or the wrong part of the shot. For each chosen clip we sample a few windows (as many as fit), send the
frames with the narration to Gemini in ONE call, and start the clip at the window that best shows what is being said.
Needs a Gemini key; without one, or on any failure, the clips keep their default start."""
import base64

import cv2
import numpy as np

from .. import db, gemini
from ..sources import hydrate

MAX_WINDOWS = 5
MIN_STEP_S = 0.8        # windows closer than this look the same
LETTERS = "ABCDE"


def _file(sh: dict):
    c = db.conn()
    if sh.get("file_id"):
        r = c.execute("SELECT path, duration FROM files WHERE id=?", (sh["file_id"],)).fetchone()
        if r:
            return r
    if sh.get("stock_id"):
        return hydrate.ensure_file(sh["stock_id"])
    return None


def _frames(path: str, times: list) -> list:
    cap = cv2.VideoCapture(str(path))
    out = []
    try:
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, fr = cap.read()
            if not ok:
                out.append(None)
                continue
            h, w = fr.shape[:2]
            fr = cv2.resize(fr, (384, int(384 * h / w)))
            ok, buf = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 80])
            out.append(buf.tobytes() if ok else None)
    finally:
        cap.release()
    return out


PROMPT = """You are choosing the start point of a B-roll clip. For each SPOT you get the narration and frames A, B, C... taken at
different moments of one stock clip. Say which frame best shows what the narration is about (the subject clearly visible, not a
title card, fade, blur or an unrelated moment). If no frame shows it, answer null.
Return JSON only: {"spots": [{"spot": int, "best": "A" | "B" | ... | null}]}
"""


def refine(slots: list) -> dict | None:
    """Set shot['trim_in'] on each slot's clip in place. Returns a small status dict, or None if skipped."""
    if not gemini.enabled():
        return None
    parts, index, n_img = [{"text": PROMPT}], {}, 0
    for i, s in enumerate(slots):
        sh = s.get("shot")
        if not sh or s.get("locked"):
            continue
        try:
            f = _file(sh)
        except Exception:
            continue
        if f is None:
            continue
        sd = s["end"] - s["start"]
        D = f["duration"] or 0
        room = D - sd
        if room < MIN_STEP_S:                       # clip barely longer than the spot: nothing to choose
            continue
        n = max(2, min(MAX_WINDOWS, int(room / MIN_STEP_S) + 1))
        ins = [float(x) for x in np.linspace(0, room, n)]
        frames = _frames(f["path"], [t + sd / 2 for t in ins])
        if sum(1 for b in frames if b) < 2:
            continue
        index[i] = ins
        parts.append({"text": f"\nSPOT {i}: narration: \"{(s.get('text') or '')[:200]}\""})
        for k, b in enumerate(frames):
            if b:
                parts += [{"text": f"frame {LETTERS[k]}:"}, {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}}]
                n_img += 1
    if not index:
        return None
    try:
        data = gemini.generate_json("", temperature=0.1, timeout=90, parts=parts)
    except Exception as e:
        return {"ok": False, "error": gemini.redact(e)}
    moved = 0
    for r in data.get("spots", []):
        try:
            i = int(r["spot"])
        except (KeyError, TypeError, ValueError):
            continue
        if i not in index:
            continue
        ins, best = index[i], str(r.get("best") or "").strip().upper()[:1]
        sh = slots[i]["shot"]
        if best in LETTERS[:len(ins)]:
            sh["trim_in"] = round(ins[LETTERS.index(best)], 2)
            slots[i]["inpoint"] = {"windows": len(ins), "at": sh["trim_in"], "fits": True}
            moved += sh["trim_in"] > 0.05
        else:
            slots[i]["inpoint"] = {"windows": len(ins), "at": sh.get("trim_in"), "fits": False}
    return {"ok": True, "spots": len(index), "moved": moved, "images": n_img}
