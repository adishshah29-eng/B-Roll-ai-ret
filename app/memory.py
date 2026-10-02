"""YOURS pillar: Edit Memory. Learns from the editor's own choices, with zero labelling.

Sources of signal
  * imported past timelines (FCP7 XML / EDL) + the script they were cut to  →  (narration line, chosen shot) pairs
  * live feedback: every swap and every export in the app                    →  positive (chosen) / negative (passed over) pairs
Use
  * boost(): a new line is matched to similar past lines; the shots chosen then (and their visual neighbours) get a bonus
  * house style: which shot sizes this editor reaches for, folded in as a small prior
Everything is explainable ("chosen 3x in your past edits") and cold-start safe (no history = no effect).
"""
import os
from collections import Counter

import numpy as np

from . import db, timeline_import

MEM_BONUS = 0.04          # max relevance bonus (same units as cosine relevance, ~0.2-0.35)
NEG_PENALTY = 0.03
STYLE_BONUS = 0.02
MIN_SIM = 0.55            # past line must be this similar to the new line to count
NEIGHBOUR_SIM = 0.88      # a visually similar shot earns half credit
MIN_STYLE_N = 5


def _norm(p):
    return os.path.normcase(os.path.normpath(p or ""))


def _match_shot(c, pl):
    """Placement (file + source in/out) → the active shot with the most overlap."""
    row = None
    if pl.get("path"):
        row = c.execute("SELECT id FROM files WHERE lower(replace(path,'/','\\\\'))=?", (_norm(pl["path"]).lower(),)).fetchone()
    if row is None and pl.get("name"):
        row = c.execute("SELECT id FROM files WHERE path LIKE ? ORDER BY id LIMIT 1", ("%" + pl["name"],)).fetchone()
    if row is None:
        return None
    best, best_ov = None, -1.0
    for s in c.execute("SELECT id, t_start, t_end FROM shots WHERE file_id=? AND active=1", (row["id"],)):
        ov = min(s["t_end"], pl["src_out"]) - max(s["t_start"], pl["src_in"])
        if ov > best_ov:
            best, best_ov = s["id"], ov
    return best


def import_timeline(xml_text: str, script: str, project: str) -> dict:
    from .planner import split_beats
    placements = timeline_import.parse(xml_text)
    beats = split_beats(script)
    if not beats:
        return {"pairs": 0, "placements": len(placements), "unmatched": len(placements), "error": "empty script"}
    spans, t = [], 0.0
    for b in beats:
        spans.append((t, t + b.dur, b.text))
        t += b.dur
    c = db.conn()
    added = unmatched = 0
    for pl in placements:
        sid = _match_shot(c, pl)
        mid = (pl["rec_in"] + pl["rec_out"]) / 2
        line = next((tx for a, b, tx in spans if a <= mid < b), spans[-1][2] if mid >= spans[-1][1] else None)
        if sid is None or not line:
            unmatched += 1
            continue
        added += add_pair(project, line, sid, 1, commit=False)
    c.commit()
    return {"pairs": added, "placements": len(placements), "unmatched": unmatched, "project": project}


def add_pair(project: str, text: str, shot_id: int, label: int, commit=True) -> int:
    c = db.conn()
    if c.execute("SELECT 1 FROM memory_pairs WHERE project=? AND text=? AND shot_id=? AND label=?",
                 (project, text, shot_id, label)).fetchone():
        return 0
    c.execute("INSERT INTO memory_pairs(project,text,shot_id,label) VALUES(?,?,?,?)", (project, text, shot_id, label))
    if commit:
        c.commit()
    return 1


def feedback(text: str, chosen_id: int, rejected_ids: list, project="live") -> dict:
    n = add_pair(project, text, chosen_id, 1)
    for r in (rejected_ids or [])[:3]:
        n += add_pair(project, text, int(r), 0)
    return {"added": n}


def clear() -> int:
    c = db.conn()
    n = c.execute("SELECT COUNT(*) FROM memory_pairs").fetchone()[0]
    c.execute("DELETE FROM memory_pairs")
    c.commit()
    return n


def _pairs():
    return db.conn().execute("SELECT text, shot_id, label, project FROM memory_pairs").fetchall()


def style() -> dict:
    """House style from the editor's positive picks."""
    c = db.conn()
    rows = c.execute("""SELECT s.size_tag, m.project FROM memory_pairs m JOIN shots s ON s.id=m.shot_id
                        WHERE m.label=1""").fetchall()
    n = len(rows)
    mix = Counter(r["size_tag"] for r in rows if r["size_tag"])
    return {"n": n, "size_mix": {k: round(v / n, 2) for k, v in mix.most_common()} if n else {},
            "projects": sorted({r["project"] for r in rows}),
            "negatives": c.execute("SELECT COUNT(*) FROM memory_pairs WHERE label=0").fetchone()[0],
            "active": n >= MIN_STYLE_N}


def boost(searcher, text: str, rows: list) -> dict:
    """row -> (bonus, hits) for candidate snapshot rows. Empty dict when there is no usable history."""
    pairs = _pairs()
    if not pairs:
        return {}
    snap = searcher.holder.get()
    texts = sorted({p["text"] for p in pairs})
    T = searcher.encode_many(texts)
    q = searcher.encode(text)
    sim_of = dict(zip(texts, (T @ q).tolist()))
    out = {r: [0.0, 0] for r in rows}
    for p in pairs:
        sim = sim_of[p["text"]]
        if sim < MIN_SIM:
            continue
        w = (sim - MIN_SIM) / (1 - MIN_SIM)
        rs = snap.index_of.get(int(p["shot_id"]))
        if rs is None:
            continue
        sgn = 1.0 if p["label"] == 1 else -NEG_PENALTY / MEM_BONUS
        for r in rows:
            if r == rs:
                out[r][0] += sgn * w
                out[r][1] += 1 if p["label"] == 1 else 0
            elif float(snap.E[r] @ snap.E[rs]) > NEIGHBOUR_SIM:
                out[r][0] += sgn * w * 0.5
    return {r: (float(np.clip(b, -1.0, 1.0)) * MEM_BONUS, h) for r, (b, h) in out.items() if b or h}


def style_bonus(size: str, st: dict) -> float:
    if not st.get("active"):
        return 0.0
    return STYLE_BONUS * st["size_mix"].get(size, 0.0)
