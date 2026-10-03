"""Jev line scoring with the API mocked: typed answers become lines and spots, engine order, failure falls through."""
import pytest

from app import jev
from app.editor import llm

UNITS = [{"id": 0, "kind": "speech", "start": 0.0, "end": 3.0, "text": "Hello everyone welcome back"},
         {"id": 1, "kind": "speech", "start": 3.4, "end": 9.6, "text": "We hiked to the top of the volcano at sunrise"},
         {"id": 2, "kind": "speech", "start": 9.8, "end": 14.0, "text": "Subscribe for more"}]

ANSWERS = {  # keyed by the line text: what a live Jev call returned, in its response shape
    "Hello everyone welcome back": {"visual": {"type": "noul", "noul": 0.1},
                                    "importance": {"type": "score", "score": 0.2, "confidence": 0.9},
                                    "role": {"type": "choice", "choice": "hook", "confidence": 0.9}},
    "We hiked to the top of the volcano at sunrise": {"visual": {"type": "noul", "noul": 0.95},
                                                      "importance": {"type": "score", "score": 3.6, "confidence": 0.8},
                                                      "role": {"type": "choice", "choice": "story", "confidence": 0.7}},
    "Subscribe for more": {"visual": {"type": "noul", "noul": 0.05},
                           "importance": {"type": "score", "score": 0.0, "confidence": 0.99},
                           "role": {"type": "choice", "choice": "cta", "confidence": 0.95}},
}


@pytest.fixture
def jev_on(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("EPOCH_SCORER", raising=False)
    monkeypatch.setattr(llm, "offline_queries", lambda text, vis=None: ("volcano sunrise", ["hiking volcano"]))


def test_typed_answers_become_scored_lines_and_a_spot(jev_on, monkeypatch):
    sent = []

    def fake(state, questions, session=None):
        sent.append((state, questions))
        return ANSWERS[state["line"]]
    monkeypatch.setattr(jev, "decide", fake)
    out = llm._jev(UNITS, 14.0, "a hike", None, "balanced")
    assert out["provider"] == "jev" and len(out["lines"]) == 3
    by_id = {l["id"]: l for l in out["lines"]}
    assert by_id[1]["importance"] == 0.9 and by_id[1]["visual"] == 0.95 and by_id[1]["role"] == "story"
    assert by_id[0]["query"] == "" and by_id[2]["role"] == "cta"          # not filmable: no search written
    assert [s["text"] for s in out["slots"]] == [UNITS[1]["text"]]
    state, questions = next(x for x in sent if x[0]["line"] == UNITS[1]["text"])
    assert state["previous_line"] == UNITS[0]["text"] and state["script"] == "a hike"
    assert {q["type"] for q in questions.values()} == {"noul", "score", "choice"}


def test_mostly_failing_jev_raises_so_plan_falls_through(jev_on, monkeypatch):
    def boom(state, questions, session=None):
        raise RuntimeError("Jev HTTP 500: sk-or-test leaked?")
    monkeypatch.setattr(jev, "decide", boom)
    with pytest.raises(RuntimeError) as e:
        llm._jev(UNITS, 14.0, None, None, "balanced")
    assert "sk-or-test" not in str(e.value)


def test_engine_order(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.delenv("EPOCH_SCORER", raising=False)
    assert llm._order() == ["gemini", "jev"]
    monkeypatch.setenv("EPOCH_SCORER", "jev")
    assert llm._order() == ["jev", "gemini"] and llm.provider_name() == "jev"
    monkeypatch.setenv("EPOCH_SCORER", "offline")
    assert llm.provider_name() == "offline"
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("EPOCH_SCORER")
    assert llm._order() == ["jev"]


def test_answer_helpers_clamp_and_default():
    assert jev.noul({"noul": 1.4}) == 1.0 and jev.noul(None, 0.3) == 0.3
    assert jev.score01({"score": 2}, 5) == 0.5 and jev.score01({}, 5) == 0.0
    assert jev.choice({"choice": "data"}) == "data" and jev.choice(None, "x") == "x"
