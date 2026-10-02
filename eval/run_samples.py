"""Run every sample script through the planner and print what to expect.   python -m eval.run_samples"""
import os

os.environ.setdefault("EPOCH_INDEXER", "0")

import yaml  # noqa: E402

from app import planner  # noqa: E402
from app.search import Searcher  # noqa: E402
from app.store import SnapshotHolder  # noqa: E402

FILE = os.path.join(os.path.dirname(__file__), "sample_scripts.yaml")
EXTRA = {"ad_cut_long": dict(target_s=15), "creator_motivation": dict(niche="motivation")}


def main():
    s = Searcher(SnapshotHolder())
    s.warmup()
    for sc in yaml.safe_load(open(FILE, encoding="utf-8")):
        kw = EXTRA.get(sc["id"], {})
        p = planner.plan(s, sc["script"], today="2026-10-03", **kw)
        print(f"\n=== {sc['title']}   [{sc['pillar']}]  {kw or ''}")
        print(f"    seq={p['sequence']['mode']} problems={p['sequence']['cuts']['problems']} total={p['format']['actual_s']}s "
              f"licences={p['licences']['counts']} rejected={p['truth']['rejected_total']}")
        for b in p["beats"]:
            c = b["claims"] or {}
            claim = ",".join(x for x in (", ".join(c.get("places", [])[:1]), c.get("time") or "", c.get("weather") or "") if x)
            for sh in b["chosen"] or [None]:
                if sh is None:
                    print(f"  B{b['i'] + 1} [{claim}] -> NO TRUTHFUL SHOT (rejected {b['n_rejected']})")
                    continue
                v = sh.get("verdict", {})
                print(f"  B{b['i'] + 1} [{claim:24}] {sh['size']:6} {sh['file'][:30]:30} {v.get('status', '-'):10} "
                      f"{('label=' + sh['label']) if sh.get('label') else ''} {sh['licence']['class']}")
            for r in b["rejected"][:1]:
                print(f"        x rejected: {r['file'][:28]} - {r['verdict']['evidence'][0][:90]}")


if __name__ == "__main__":
    main()
