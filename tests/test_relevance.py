"""Relevance rules that need no network: spot guarantee, line parsing, wrong-place rule, keep-only-confirmed filter."""
from app.editor import llm, relevance, slots, suggest

UNITS = [{"id": 0, "kind": "speech", "start": 0.0, "end": 3.0, "text": "Hello everyone welcome back"},
         {"id": 1, "kind": "speech", "start": 3.4, "end": 9.6, "text": "Honestly consistency matters more than talent in the long run"}]


def test_a_ten_second_video_always_gets_a_spot_even_with_weak_lines():
    lines = [{"id": 0, "importance": 0.1, "visual": 0.2, "role": "hook", "query": "", "alt_queries": [], "anchor": ""},
             {"id": 1, "importance": 0.2, "visual": 0.5, "role": "key point", "query": "person working out", "alt_queries": [], "anchor": ""}]
    spots = slots.select_spots(lines, UNITS, 10.0, "light", None)
    assert len(spots) == 1 and spots[0]["guaranteed"] and spots[0]["query"] == "person working out"


def test_longer_videos_get_one_spot_per_ten_seconds_at_least():
    units = [{"id": i, "kind": "speech", "start": i * 10.0, "end": i * 10.0 + 9.0, "text": f"line {i} about the mountains"} for i in range(3)]
    lines = [{"id": i, "importance": 0.1, "visual": 0.6, "role": "key point", "query": f"mountain {i}", "alt_queries": [], "anchor": ""} for i in range(3)]
    assert len(slots.select_spots(lines, units, 30.0, "light", None)) >= 3


def test_topic_spot_when_nothing_is_filmable():
    spot = llm.topic_spot(UNITS, 10.0, "A talk about habits and consistency", None)
    assert len(spot) == 1 and "consistency" in spot[0]["query"]


def test_malformed_gemini_lines_do_not_break_parsing():
    bad = {"lines": [{"id": "x"}, {"id": 9999}, {"id": 1, "importance": "high", "visual": None, "role": 5, "query": None}, {"nope": 1}]}
    out = llm._parse_lines(bad, UNITS)
    assert len(out) == 1 and out[0]["importance"] == 0.0 and out[0]["query"] == ""


def test_banned_words_are_removed_from_queries():
    assert llm.clean_query("web development screen") == "web development"


def test_a_clip_titled_with_another_place_is_flagged_as_wrong_place():
    assert suggest.wrong_place({"title": "Street in Mumbai (video) 03", "file": "x"}, ["Jaipur"]) == "Mumbai"
    assert suggest.wrong_place({"title": "Jaipur market", "file": "x"}, ["Jaipur"]) is None
    assert suggest.wrong_place({"title": "Street in Mumbai", "file": "x"}, []) is None          # video names no place: nothing to contradict


def test_filter_keeps_only_picture_confirmed_clips_and_marks_empty_beats():
    a, b, c = ({"id": i, "licence": {"class": "safe", "commercial": True}, "file": f"f{i}"} for i in (1, 2, 3))
    beats = [{"i": 0, "text": "line one", "chosen": [a], "alts": [b, c]}, {"i": 1, "text": "line two", "chosen": [b], "alts": [c]}]
    sl = [{"text": "line one", "shot": None, "alts": [a, b, c], "judge": {"good_ids": [2], "of": 3, "reason": "ok"}},
          {"text": "line two", "shot": None, "alts": [b, c], "judge": {"good_ids": [], "of": 2, "reason": "none fit", "queries": ["q"]}}]
    relevance._apply(beats, sl)
    assert [x["id"] for x in beats[0]["chosen"]] == [2] and beats[0]["no_match"] is False      # the confirmed alternative replaces the rejected pick
    assert beats[1]["chosen"] == [] and beats[1]["no_match"] is True and beats[1]["alts"] == []  # nothing fit: empty, not irrelevant
    out = relevance._finish({"beats": beats})
    assert out["licences"]["counts"] == {"safe": 1} and out["licences"]["commercial_ok"]
