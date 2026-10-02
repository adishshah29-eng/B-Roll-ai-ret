"""One results table for all three pillars, with ablations.

    python -m eval.eval_all                 # uses whatever Edit Memory currently holds
    python -m eval.eval_all --seed-memory   # first teach a SIMULATED editor (prefers close-ups) from 2 past projects

Rows (same scripts, same library, only the switches change):
    baseline      relevance only (no TRUE, no CUTS, no YOURS)
    + TRUE        wrong-place / contradicting footage removed, evidence bonus
    + CUTS        sequence chosen with Viterbi instead of greedy
    + YOURS       edit memory + house style
    all three
Columns: contradictions in the final timeline (judged by the TRUE rules for every row), cut problems, same-size repeats,
size progressions, mean relevance, share of close-ups (the simulated editor's taste), plan latency p50 / p95.
"""
import os
import statistics
import sys
import time
from datetime import date

os.environ.setdefault("EPOCH_INDEXER", "0")

from app import db, export, memory, planner, truth  # noqa: E402
from app.search import Searcher  # noqa: E402
from app.store import SnapshotHolder  # noqa: E402
from eval.eval_cuts import SCRIPTS  # noqa: E402

PLACE_SCRIPTS = {
    "mumbai": "Heavy rain lashed Mumbai today, bringing traffic to a halt. Commuters waited for hours at flooded local stations. "
              "Street vendors covered their stalls with plastic sheets. By evening the city's roads turned into rivers.",
    "delhi": "Winter fog settled over Delhi this morning. Traffic crawled along the ring road. Commuters crowded the metro. "
             "Street food stalls steamed in the cold.",
    "kolkata": "In Kolkata the monsoon arrived early this year. Trams rolled through flooded streets. "
               "People waded home along the river. Vendors sold tea under plastic sheets.",
    "old india": "In 1906 a street in India looked like this. Crowds moved through the market. Carts filled the road.",
}
PAST = {  # past projects for the simulated editor (who always picks a local close-up when one exists)
    "past_chai": "The day starts with chai at a roadside stall. Fresh vegetables are piled high in the market. A cook stirs a hot pan. Families share a meal together.",
    "past_tech": "A developer types late into the night. Teams meet to plan the next release. A phone lights up with a notification. The city runs on data.",
    "past_street": "Rain falls on the street. Crowds move through the market. Traffic crawls through the junction. People walk home at night.",
}
TODAY = "2026-10-03"


def seed_memory(searcher):
    """Simulate an editor with a taste for close-ups: for each line pick the best CLOSE-UP from local footage,
    export the timeline as XML, and import it back exactly like a real past project."""
    from app.search import shot_cards
    import numpy as np
    memory.clear()
    out_dir = os.path.join(os.path.dirname(__file__), "projects")
    os.makedirs(out_dir, exist_ok=True)
    snap = searcher.holder.get()
    for name, script in PAST.items():
        beats = planner.split_beats(script)
        cards_per_beat = []
        for b in beats:
            cands = searcher.candidates(b.text, k=40, filters={"source": ["own"]})
            pick = next((c for c in cands if snap.size[c[0]] == "close"), cands[0] if cands else None)
            sc = np.zeros(len(snap))
            if pick:
                sc[pick[0]] = pick[1]
                cards_per_beat.append({"i": b.i, "text": b.text, "dur": b.dur, "chosen": [shot_cards(snap, [pick[0]], sc)[pick[0]]]})
            else:
                cards_per_beat.append({"i": b.i, "text": b.text, "dur": b.dur, "chosen": []})
        xml = export.to_xmeml(cards_per_beat, name=name)
        open(os.path.join(out_dir, name + ".xml"), "w", encoding="utf-8").write(xml)
        open(os.path.join(out_dir, name + ".txt"), "w", encoding="utf-8").write(script)
        print(f"  {name}: {memory.import_timeline(xml, script, name)}")


def chosen_of(p):
    return [s for b in p["beats"] for s in b["chosen"]]


def contradictions(p, scripts_text):
    """How many chosen shots the TRUE rules would reject for their own line (judged independently of the plan's switches)."""
    from datetime import date as _d
    beats = planner.split_beats(scripts_text)
    claims = truth.inherit_places([truth.extract_claims(b.text) for b in beats])
    ids = [s["id"] for b in p["beats"] for s in b["chosen"]]
    facts = truth.fetch_facts(ids)
    n = 0
    for b, cl in zip(p["beats"], claims):
        for s in b["chosen"]:
            if truth.verdict(cl, facts.get(s["id"], {}), _d.fromisoformat(TODAY)).status == "bad":
                n += 1
    return n


def run_config(searcher, scripts, **flags):
    tot = {"clips": 0, "contra": 0, "problems": 0, "same": 0, "prog": 0, "close": 0}
    rels, lat = [], []
    for text in scripts.values():
        t0 = time.perf_counter()
        p = planner.plan(searcher, text, today=TODAY, **flags)
        lat.append((time.perf_counter() - t0) * 1000)
        ch = chosen_of(p)
        rep = p["sequence"]["cuts"] if flags.get("use_cuts") else p["sequence"]["greedy"]
        tot["clips"] += len(ch)
        tot["contra"] += contradictions(p, text)
        tot["problems"] += rep["problems"]
        tot["same"] += rep["same_size"]
        tot["prog"] += rep["progress"]
        tot["close"] += sum(1 for s in ch if s["size"] == "close")
        rels.append(rep["mean_rel"])
    lat.sort()
    return tot, statistics.mean(rels), lat[len(lat) // 2], lat[min(len(lat) - 1, int(len(lat) * 0.95))]


def main():
    s = Searcher(SnapshotHolder())
    s.warmup()
    if "--seed-memory" in sys.argv:
        print("Seeding Edit Memory from a SIMULATED editor (always picks the close-up alternative):")
        seed_memory(s)
    st = memory.style()
    print(f"\nEdit Memory: {st['n']} lessons, size mix {st['size_mix']}")
    scripts = {**SCRIPTS, **PLACE_SCRIPTS}
    configs = [
        ("baseline (relevance only)", dict(use_truth=False, use_cuts=False, use_memory=False)),
        ("+ TRUE", dict(use_truth=True, use_cuts=False, use_memory=False)),
        ("+ CUTS", dict(use_truth=False, use_cuts=True, use_memory=False)),
        ("+ YOURS", dict(use_truth=False, use_cuts=False, use_memory=True)),
        ("all three", dict(use_truth=True, use_cuts=True, use_memory=True)),
    ]
    for c in configs:                       # warm every code path once so latency is steady-state
        planner.plan(s, "Traffic fills the roads today.", today=TODAY, **c[1])
    print(f"\n{len(scripts)} scripts ({len(SCRIPTS)} general + {len(PLACE_SCRIPTS)} with place/date claims), same library, same scripts\n")
    print(f"{'configuration':27} {'clips':>5} {'contradict.':>11} {'cut probs':>9} {'same-size':>9} {'progress':>8} {'relevance':>9} {'close-ups':>9} {'p50 ms':>7} {'p95 ms':>7}")
    for name, flags in configs:
        t, rel, p50, p95 = run_config(s, scripts, **flags)
        print(f"{name:27} {t['clips']:5d} {t['contra']:11d} {t['problems']:9d} {t['same']:9d} {t['prog']:8d} {rel:9.3f} {t['close'] / max(t['clips'], 1):9.0%} {p50:7.0f} {p95:7.0f}")
    print("\ncontradict. = chosen shots that the TRUE rules reject for their own line (judged the same way for every row)")


if __name__ == "__main__":
    main()
