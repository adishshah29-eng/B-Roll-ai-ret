"""CUTS evaluation: relevance-only greedy vs cut-aware sequence on a fixed set of scripts.

    python -m eval.eval_cuts                 # prints the sweep over CUT_WEIGHT and the per-script table

Metrics (per transition between consecutive clips):
  jump      same take, close in time, near-identical framing (or an identical look repeated)
  flip      screen direction reverses                       (needs optical-flow features: local clips only)
  exposure  brightness jump > 0.25
  colour    colour-temperature jump > 0.20
  problems  jump + flip + exposure + colour
  rel loss  how much mean relevance the cut-aware choice gives up versus greedy
"""
import os
import sys

os.environ.setdefault("EPOCH_INDEXER", "0")

from app import cuts, planner  # noqa: E402
from app.search import Searcher  # noqa: E402
from app.store import SnapshotHolder  # noqa: E402

SCRIPTS = {
    "city morning": "Every morning the city wakes up in a rush. Traffic fills the roads as people head to work. "
                    "Inside offices teams get busy on their laptops. At lunch street food stalls come alive. "
                    "In the evening the skyline glows as the day ends.",
    "monsoon": "Heavy rain lashed the city today. Commuters waited at flooded stations. Street vendors covered their "
               "stalls. Roads turned into rivers by evening. Children splashed through the puddles.",
    "food": "The day starts with chai at a roadside stall. Fresh vegetables are piled high in the market. "
            "A cook stirs a hot pan. Families share a meal together. Street food keeps the city fed.",
    "farm": "Before sunrise the farmer walks to his field. A tractor turns the soil. Green crops sway in the wind. "
            "Workers carry the harvest to the market. Evening falls over the village.",
    "tech": "Startups are changing how we work. A developer types late into the night. Teams meet to plan the next "
            "release. A phone lights up with a notification. The city runs on data.",
    "nature": "Mountains rise above the clouds. A river winds through the forest. Birds take off at dawn. "
              "Waterfalls crash into the valley. The sun sets over the sea.",
    "festival": "The festival of lights begins at dusk. Lamps glow on every doorstep. Crowds fill the streets. "
                "Fireworks light up the sky. Families gather to celebrate.",
    "travel": "Trains carry millions across the country every day. A platform fills with passengers. "
              "Buses crawl through busy junctions. Aerial views show a city that never sleeps. Travellers finally arrive.",
    "school": "Children walk to school in the morning. A teacher writes on the board. Students work at their desks. "
              "Playgrounds fill with laughter. The bell rings and the day ends.",
    "hindi city": "हर सुबह शहर जाग उठता है। सड़कों पर ट्रैफिक बढ़ जाता है। दफ्तरों में लोग काम में जुट जाते हैं। "
                  "बाज़ार में रौनक लौट आती है। शाम को आसमान सुनहरा हो जाता है।",
    "hindi rain": "आज मुंबई में भारी बारिश हुई। लोग स्टेशन पर इंतज़ार करते रहे। सड़कें नदी बन गईं। बच्चे पानी में खेलते रहे।",
    # dense single-topic scripts: the realistic jump-cut trap (one subject, many lines, few long takes in the library)
    "rain dense": "Rain falls on the street. Water runs along the road. Wet streets shine under the lights. "
                  "Umbrellas move through the crowd. Puddles ripple as cars pass. The storm keeps on.",
    "old street": "A street in India looked like this long ago. Crowds moved through the market. "
                  "Carts and people filled the road. Shopkeepers watched the day go by. Children ran between the stalls.",
    "traffic dense": "Traffic crawls through the junction. Cars queue at the signal. Buses and bikes weave through. "
                     "Horns echo down the road. The jam stretches for miles. Drivers wait and wait.",
    "construction": "A new building rises above the skyline. Workers climb the scaffolding. Cranes lift steel beams. "
                    "Engineers check the plans. By night the lights come on.",
}


def run(searcher, weights=(0.0, 0.06, 0.10, 0.25, 0.4, 0.6, 1.0), use_truth=True):
    rows = []
    for w in weights:
        agg = {"g_prob": 0, "c_prob": 0, "g_rel": [], "c_rel": [], "g_jump": 0, "c_jump": 0, "g_flip": 0, "c_flip": 0,
               "g_exp": 0, "c_exp": 0, "g_col": 0, "c_col": 0, "g_same": 0, "c_same": 0, "g_prog": 0, "c_prog": 0, "n": 0}
        per = {}
        for name, text in SCRIPTS.items():
            p = planner.plan(searcher, text, use_truth=use_truth, use_cuts=True, cut_weight=w, today="2026-10-03")
            g, c = p["sequence"]["greedy"], p["sequence"]["cuts"]
            per[name] = (g, c)
            agg["g_prob"] += g["problems"]; agg["c_prob"] += c["problems"]
            agg["g_rel"].append(g["mean_rel"]); agg["c_rel"].append(c["mean_rel"])
            for k, a in (("jump", "jump"), ("flip", "flip"), ("exposure", "exp"), ("colour", "col"),
                         ("same_size", "same"), ("progress", "prog")):
                agg["g_" + a] += g[k]; agg["c_" + a] += c[k]
            agg["n"] += g["transitions"]
        gr, cr = sum(agg["g_rel"]) / len(agg["g_rel"]), sum(agg["c_rel"]) / len(agg["c_rel"])
        rows.append((w, agg, gr, cr, per))
    return rows


def main():
    s = Searcher(SnapshotHolder())
    s.warmup()
    rows = run(s)
    print(f"{len(SCRIPTS)} scripts, {rows[0][1]['n']} transitions each strategy\n")
    print(f"{'weight':>7} | {'greedy':^31} | {'cut-aware':^31} | {'problems':>9} | {'rel loss':>8}")
    print(f"{'':>7} | {'jump flip exp col same prog':^31} | {'jump flip exp col same prog':^31} | {'reduction':>9} |")
    for w, a, gr, cr, _ in rows:
        red = 1 - a["c_prob"] / a["g_prob"] if a["g_prob"] else 0.0
        loss = (gr - cr) / gr if gr else 0.0
        print(f"{w:7.2f} | {a['g_jump']:4d} {a['g_flip']:4d} {a['g_exp']:3d} {a['g_col']:3d} {a['g_same']:4d} {a['g_prog']:4d}"
              f"   | {a['c_jump']:4d} {a['c_flip']:4d} {a['c_exp']:3d} {a['c_col']:3d} {a['c_same']:4d} {a['c_prog']:4d}"
              f"   | {red:9.0%} | {loss:8.1%}")
    w, a, gr, cr, per = next((r for r in rows if abs(r[0] - cuts.CUT_WEIGHT) < 1e-9), rows[-1])
    print(f"\nper script at CUT_WEIGHT={w}:  problems greedy → cut-aware")
    for name, (g, c) in per.items():
        print(f"  {name:14} {g['problems']:2d} → {c['problems']:2d}   (jump {g['jump']}→{c['jump']}, exposure {g['exposure']}→{c['exposure']}, "
              f"same-size {g['same_size']}→{c['same_size']}, progress {g['progress']}→{c['progress']})")


if __name__ == "__main__":
    sys.exit(main())
