"""Tiny text helpers shared by retrieval and the editor: stop words, light stemming, content tokens."""
import re

STOP = set("""a an the and or but if then so of to in on at by for with from as is are was were be been being am i me my we our us you your
he she it they them his her its their this that these those there here what which who whom whose when where why how not no yes do does did
done have has had will would can could should may might must just very really also too than about into over under up down out off again
more most some any each other such only own same both few all let lets lot lots like get got going go goes went gonna want need think know
say said tell told hi hello everyone welcome back channel today comments comment subscribe video guys thing things stuff one two""".split())


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def tokens(text: str) -> list:
    """Content stems of a query / tag string, order kept, duplicates removed."""
    seen, out = set(), []
    for w in re.findall(r"[a-z]{3,}", (text or "").lower()):
        if w in STOP:
            continue
        s = stem(w)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
