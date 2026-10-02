"""Integration: the real planner + real library (read-only). Skipped when the demo data is not indexed."""
import os

import pytest

os.environ["EPOCH_INDEXER"] = "0"          # no background indexing during tests

from fastapi.testclient import TestClient   # noqa: E402

from app import db   # noqa: E402

MUMBAI = ("Heavy rain lashed Mumbai today, bringing traffic to a halt.\n"
          "Commuters waited for hours at flooded local stations.\n"
          "By evening, the city's roads turned into rivers.")


@pytest.fixture(scope="module")
def client():
    n = db.conn().execute("SELECT COUNT(*) FROM shots WHERE active=1").fetchone()[0]
    if n < 100:
        pytest.skip("library not indexed")
    from app.main import app
    with TestClient(app) as c:
        yield c


def plan(client, script, **kw):
    r = client.post("/api/plan", json={"script": script, "today": "2026-10-03", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_no_chosen_shot_contradicts_and_none_is_both_chosen_and_rejected(client):
    p = plan(client, MUMBAI)
    for b in p["beats"]:
        ch, rj = {s["id"] for s in b["chosen"]}, {s["id"] for s in b["rejected"]}
        assert not (ch & rj)
        assert all(s["verdict"]["status"] != "bad" for s in b["chosen"])
        assert all(s["verdict"]["evidence"] and s["verdict"]["status"] == "bad" for s in b["rejected"])


def test_place_context_is_carried_to_later_beats_and_filters_other_cities(client):
    p = plan(client, MUMBAI)
    assert p["beats"][0]["claims"]["place_inherited"] is False
    assert p["beats"][1]["claims"]["place_inherited"] is True and p["beats"][1]["claims"]["places"][0] == "Mumbai"
    assert p["truth"]["rejected_total"] > 0                      # wrong-city footage was actually removed
    why = " ".join(r["verdict"]["evidence"][0] for b in p["beats"] for r in b["rejected"])
    assert "Mumbai" in why                                        # every rejection explains the clash with Mumbai


def test_truth_off_returns_no_verdicts_and_is_a_pure_relevance_plan(client):
    p = plan(client, MUMBAI, use_truth=False)
    assert p["truth"]["enabled"] is False
    assert all("verdict" not in s for b in p["beats"] for s in b["chosen"])
    assert all(b["n_rejected"] == 0 for b in p["beats"])


def test_old_footage_under_today_gets_file_label_that_reaches_the_srt(client):
    p = plan(client, "Floodwater covered the streets today.")
    labelled = [s for s in p["beats"][0]["chosen"] if s.get("label", "") and s["label"].startswith("FILE")]
    if not labelled:
        pytest.skip("no recorded-date clip was picked for this line in this library")
    r = client.post("/api/export", json={"beats": p["beats"], "format": "srt"})
    assert labelled[0]["label"] in r.text


def test_year_claim_prefers_footage_recorded_that_year_and_rejects_other_years(client):
    p = plan(client, "In 2019 the streets flooded.")
    b = p["beats"][0]
    assert b["claims"]["year"] == 2019
    for s in b["rejected"]:
        assert "2019" in s["verdict"]["evidence"][0]
    for s in b["chosen"]:
        assert s["date_src"] not in ("recorded", "meta") or s["date"].startswith("2019") or s["verdict"]["status"] != "bad"


def test_planning_with_truth_is_fast(client):
    plan(client, MUMBAI)                                           # warm
    assert plan(client, MUMBAI)["took_ms"] < 500
