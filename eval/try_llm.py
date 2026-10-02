"""See what the B-roll planner does with a script that has little to film (a Python lecture).   python -m eval.try_llm
Runs the offline engine always, and Gemini when a key is present. Errors are redacted; the key is never printed."""
from app import gemini
from app.editor import llm, slots

LINES = [
    "Hi everyone, welcome back to the channel.",
    "Today we are going to learn Python from scratch.",
    "Python is a popular programming language used in AI and web development.",
    "That's why it's used in AI and web dev.",
    "You write your code in an editor and run it to see the result.",
    "Variables are just names that store values.",
    "I think the key idea here is consistency.",
    "A website is built from code that runs on a server somewhere in a data center.",
    "Let me know in the comments what you want to learn next.",
]


def main():
    units, t = [], 0.0
    for i, text in enumerate(LINES):
        units.append({"id": i, "kind": "speech", "start": round(t, 2), "end": round(t + 4.2, 2), "text": text, "frame": None})
        t += 5.0
    dur = t
    print("== offline engine, line by line")
    for u in units:
        q, alts = llm.offline_queries(u["text"])
        print(f"  p(filmable)={llm.visual_prob(u['text']):.2f}  {('-> ' + q + '  ' + str(alts)) if q else '-> (left alone)'}   <- {u['text'][:56]}")
    print("\n== offline plan:", {k: v for k, v in llm.offline_plan(units, dur, []).items() if k != "slots"})
    if gemini.enabled():
        print("\n== key check:", gemini.check())
        r = llm.plan(units, [], dur, [], None)
        print("== plan() provider:", r["provider"], "| error:", r.get("error"), "|", r.get("ms"), "ms")
        print("   summary:", r.get("summary"))
        for s in r["slots"]:
            print(f"   {s['start']:5.1f}-{s['end']:5.1f}  {s['query']!r:34} alts={s.get('alt_queries')}  [{s.get('reason', '')[:50]}]")


if __name__ == "__main__":
    main()
