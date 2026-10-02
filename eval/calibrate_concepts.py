"""Which signal tells "something you can film" from "talk"?   python -m eval.calibrate_concepts

A. concept similarity (text vs concept list)            what the offline engine used: reported only to show it cannot work
B. text -> library IMAGE similarity (top-5 mean)        "does anything in the library look like this line?"
C. linear probe on the sentence embedding               "is this a filmable line?" (leave-one-out cross-validation)
"""
import numpy as np
import yaml
from sklearn.linear_model import LogisticRegression

from app import models
from app.config import RESOURCES
from app.editor import llm
from app.store import build_snapshot


def bal_acc(y, s):
    best = (0, 0.0)
    for thr in np.unique(s):
        pred = s >= thr
        b = (pred[y == 1].mean() + (~pred)[y == 0].mean()) / 2
        if b > best[0]:
            best = (b, float(thr))
    return best


def main():
    spec = yaml.safe_load(open(RESOURCES / "visualness.yaml", encoding="utf-8"))
    lines = spec["visual"] + spec["talk"]
    y = np.array([1] * len(spec["visual"]) + [0] * len(spec["talk"]))
    X = models.embed_texts(lines)
    print(f"{len(spec['visual'])} visual + {len(spec['talk'])} talk lines")

    a = np.array([llm.concepts(t, 1)[0][1] for t in lines])
    b_acc, b_thr = bal_acc(y, a)
    print(f"A concept similarity      : best balanced accuracy {b_acc:.0%} at {b_thr:.3f}")

    E = build_snapshot().E
    img = np.array([np.sort(E @ x)[-5:].mean() for x in X])
    b_acc, b_thr = bal_acc(y, img)
    print(f"B library image similarity: best balanced accuracy {b_acc:.0%} at {b_thr:.3f}   (visual mean {img[y == 1].mean():.3f}, talk mean {img[y == 0].mean():.3f})")

    ok = 0
    probs = np.zeros(len(y))
    for i in range(len(y)):                              # leave-one-out
        m = np.ones(len(y), bool)
        m[i] = False
        clf = LogisticRegression(C=2.0, max_iter=1000).fit(X[m], y[m])
        probs[i] = clf.predict_proba(X[i:i + 1])[0, 1]
        ok += int((probs[i] >= 0.5) == y[i])
    print(f"C linear probe (LOO)      : accuracy {ok / len(y):.0%}  (visual kept {np.mean(probs[y == 1] >= 0.5):.0%}, talk rejected {np.mean(probs[y == 0] < 0.5):.0%})")
    print("\nlines the probe gets wrong:")
    for i in np.where((probs >= 0.5) != y)[0]:
        print(f"  {'visual' if y[i] else 'talk  '} p={probs[i]:.2f}  {lines[i][:78]}")


if __name__ == "__main__":
    main()
