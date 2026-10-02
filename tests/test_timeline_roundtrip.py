import json
from pathlib import Path

import pytest

from app import export, timeline_import

PLAN = Path(__file__).resolve().parent.parent / "data" / "last_plan.json"


@pytest.mark.skipif(not PLAN.exists(), reason="needs data/last_plan.json from a real plan")
def test_xml_and_edl_roundtrip_preserve_clips_and_timing():
    beats = json.loads(PLAN.read_text())["beats"]
    clips = export._clips_from_beats(beats)
    assert clips, "plan produced no timeline clips"

    xml = export.to_xmeml(beats)
    got = timeline_import.parse_xmeml(xml)
    assert len(got) == len(clips)
    for want, g in zip(clips, got):
        assert Path(g["path"]).name == want["name"]
        assert abs(g["src_in"] - want["src_in"]) < 0.05
        assert abs(g["rec_in"] - want["rec_in"]) < 0.05
        assert g["note"].startswith(want["text"][:20])

    edl = timeline_import.parse_edl(export.to_edl(beats))
    assert len(edl) == len(clips)
    assert len({e["reel"] for e in edl}) == len({c["path"] for c in clips})   # unique reel per source
    assert [e["name"] for e in edl] == [c["name"] for c in clips]


def test_timeline_is_gapless_and_ordered():
    beats = json.loads(PLAN.read_text())["beats"] if PLAN.exists() else []
    clips = export._clips_from_beats(beats)
    for a, b in zip(clips, clips[1:]):
        assert abs(a["rec_out"] - b["rec_in"]) < 1e-6
