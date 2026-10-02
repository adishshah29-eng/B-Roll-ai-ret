"""TRUE pillar: claims extraction + verdict rules. Pure functions, no DB or models."""
from datetime import date

from app import truth
from app.truth import Claims, extract_claims, match_places, verdict

TODAY = date(2026, 10, 3)


def facts(**kw):
    base = {"weather": None, "weather_conf": 0.0, "shot_date": None, "date_source": "unknown", "source": "own",
            "title": None, "tags": None, "ocr_text": None, "gps_lat": None, "gps_lon": None}
    base.update(kw)
    return base


# ---------- claims ----------
def test_claims_english():
    c = extract_claims("Heavy rain lashed Mumbai today, bringing traffic to a halt.")
    assert c.place == "Mumbai" and c.weather == "rain" and c.time_kind == "recent" and c.time_phrase == "today"


def test_claims_hindi():
    c = extract_claims("आज मुंबई में भारी बारिश हुई")
    assert c.place == "Mumbai" and c.weather == "rain" and c.time_kind == "recent"


def test_claims_year_and_old_names():
    c = extract_claims("In 1906, a street in Calcutta looked like this.")
    assert c.place == "Kolkata" and c.time_kind == "year" and c.year == 1906


def test_year_must_look_like_a_year_claim():
    assert extract_claims("Over 2000 people gathered").time_kind is None
    assert extract_claims("In 2019 the city flooded").year == 2019


def test_city_beats_country_and_region_in_claim_order():
    c = extract_claims("Across India, in Maharashtra, Mumbai was hit hardest")
    assert c.places[0] == "Mumbai" and set(c.places) >= {"India", "Maharashtra"}


def test_no_claims_in_generic_line():
    assert not extract_claims("Teams get busy on their laptops.").any()


# ---------- place matching ----------
def test_match_places_tolerates_ocr_without_spaces_and_case():
    assert match_places("DelhiMetro STATION")[0][0] == "Delhi"
    assert match_places("MUMBAI LOCAL")[0][0] == "Mumbai"
    assert match_places("बारिश में दिल्ली") [0][0] == "Delhi"


def test_short_aliases_need_word_boundaries():
    assert match_places("agrarian reform") == []          # 'agra' must not match inside 'agrarian'
    assert match_places("the pune road")[0][0] == "Pune"


def test_hierarchy():
    assert truth.is_within("Mumbai", "Maharashtra") and truth.is_within("Mumbai", "India")
    assert not truth.is_within("Maharashtra", "Mumbai") and not truth.is_within("Delhi", "Maharashtra")


# ---------- place verdicts ----------
def test_wrong_city_on_signboard_is_bad_with_evidence():
    v = verdict(extract_claims("Heavy rain in Mumbai today"), facts(ocr_text="DELHI METRO"), TODAY)
    assert v.status == "bad" and v.checks["place"]["status"] == "bad"
    assert "Delhi" in v.evidence[0] and "Mumbai" in v.evidence[0]


def test_matching_signboard_confirms_and_boosts():
    v = verdict(extract_claims("Rain in Mumbai"), facts(ocr_text="MUMBAI LOCAL CST"), TODAY)
    assert v.status == "ok" and v.delta > 0 and "confirmed" in v.evidence[0]


def test_no_evidence_is_unverified_not_bad():
    v = verdict(extract_claims("Rain in Mumbai"), facts(), TODAY)
    assert v.status == "unverified" and v.delta == 0 and v.label is None


def test_stock_with_no_place_evidence_gets_stock_label():
    v = verdict(extract_claims("Floods hit Mumbai"), facts(source="pixabay", title="rain, street, wet"), TODAY)
    assert v.status == "warn" and v.label == "STOCK · not event footage"


def test_stock_title_naming_the_place_confirms():
    v = verdict(extract_claims("A busy street in Mumbai"), facts(source="commons", title="Street in Mumbai (video) 02"), TODAY)
    assert v.status == "ok" and v.label is None


def test_stock_title_naming_another_city_is_bad():
    v = verdict(extract_claims("Mumbai at night"), facts(source="pixabay", title="new york city, manhattan"), TODAY)
    assert v.status == "bad"


def test_country_level_evidence_cannot_confirm_a_city():
    v = verdict(extract_claims("Traffic in Mumbai"), facts(source="pixabay", tags="india, crossroads, traffic"), TODAY)
    assert v.checks["place"]["status"] == "unverified"


def test_region_claim_is_confirmed_by_city_evidence_but_not_vice_versa():
    assert verdict(extract_claims("Floods in Maharashtra"), facts(ocr_text="Mumbai"), TODAY).checks["place"]["status"] == "ok"
    assert verdict(extract_claims("Floods in Mumbai"), facts(title="maharashtra countryside"), TODAY).checks["place"]["status"] == "unverified"


def test_two_cities_in_narration_do_not_flag_either_city():
    c = extract_claims("From Mumbai to Delhi, the rains arrived")
    assert verdict(c, facts(ocr_text="Delhi Metro"), TODAY).status != "bad"
    assert verdict(c, facts(ocr_text="Mumbai Local"), TODAY).status != "bad"
    assert verdict(c, facts(ocr_text="Kolkata Howrah"), TODAY).status == "bad"


def test_gps_confirms_and_contradicts():
    mumbai = dict(gps_lat=19.07, gps_lon=72.88)
    delhi = dict(gps_lat=28.61, gps_lon=77.21)
    assert verdict(extract_claims("Rain in Mumbai"), facts(**mumbai), TODAY).status == "ok"
    assert verdict(extract_claims("Rain in Mumbai"), facts(**delhi), TODAY).status == "bad"
    assert verdict(extract_claims("Rain in Mumbai"), facts(gps_lat=0.0, gps_lon=0.0), TODAY).status == "unverified"


# ---------- time verdicts ----------
def test_old_recorded_footage_under_today_is_warn_with_file_label():
    v = verdict(extract_claims("The city floods today"), facts(shot_date="2019-08-10T00:00:00", date_source="meta"), TODAY)
    assert v.status == "warn" and v.label == "FILE · 2019" and "2019-08-10" in v.evidence[0]


def test_recent_recorded_footage_is_ok():
    v = verdict(extract_claims("The city floods today"), facts(shot_date="2026-09-20", date_source="meta"), TODAY)
    assert v.status == "ok" and v.label is None


def test_unreliable_dates_never_trigger_labels():
    for src in ("mtime", "unknown"):
        v = verdict(extract_claims("The city floods today"), facts(shot_date="2019-01-01", date_source=src), TODAY)
        assert v.status == "unverified" and v.label is None


def test_upload_date_is_an_upper_bound():
    old = verdict(extract_claims("Flooding today"), facts(shot_date="2021-05-27", date_source="upload"), TODAY)
    assert old.status == "warn" and old.label == "FILE · 2021"
    new = verdict(extract_claims("Flooding today"), facts(shot_date="2026-10-01", date_source="upload"), TODAY)
    assert new.status == "unverified"


def test_year_claims():
    c = extract_claims("In 1906 this street looked like this")
    assert verdict(c, facts(shot_date="1906", date_source="recorded"), TODAY).status == "ok"
    assert verdict(c, facts(shot_date="2016-03-29", date_source="recorded"), TODAY).status == "bad"
    assert verdict(c, facts(shot_date="1905", date_source="upload"), TODAY).status == "bad"   # uploaded before 1906
    assert verdict(c, facts(), TODAY).status == "unverified"


def test_partial_dates():
    lo, hi = truth.parse_partial_date("2020-04")
    assert (lo, hi) == (date(2020, 4, 1), date(2020, 4, 30))
    assert truth.parse_partial_date("1906") == (date(1906, 1, 1), date(1906, 12, 31))
    assert truth.parse_partial_date("garbage") is None and truth.parse_partial_date(None) is None


# ---------- weather verdicts ----------
def test_weather_bad_only_at_high_confidence_and_clear_opposites():
    c = extract_claims("Heavy rain lashed the city")
    assert verdict(c, facts(weather="sunny", weather_conf=0.98), TODAY).status == "bad"
    assert verdict(c, facts(weather="sunny", weather_conf=0.90), TODAY).status == "warn"     # soft signal: warn only
    assert verdict(c, facts(weather="sunny", weather_conf=0.60), TODAY).status == "unverified"
    assert verdict(c, facts(weather="indoor", weather_conf=0.99), TODAY).status == "unverified"
    assert verdict(c, facts(weather="rain", weather_conf=0.90), TODAY).status == "ok"
    assert verdict(c, facts(weather="cloudy", weather_conf=0.99), TODAY).status == "unverified"   # compatible-ish
    assert verdict(c, facts(weather="night", weather_conf=0.99), TODAY).status == "unverified"


# ---------- combination ----------
def test_worst_check_wins_and_bad_evidence_comes_first():
    c = extract_claims("Heavy rain lashed Mumbai today")
    v = verdict(c, facts(ocr_text="Mumbai", weather="sunny", weather_conf=0.99,
                         shot_date="2026-09-25", date_source="meta"), TODAY)
    assert v.status == "bad" and v.checks["place"]["status"] == "ok"
    assert "sunny" in v.evidence[0]


def test_bonus_is_capped_and_warn_costs_a_little():
    c = extract_claims("Rain in Mumbai today")
    great = verdict(c, facts(ocr_text="Mumbai", weather="rain", weather_conf=0.9, shot_date="2026-10-01", date_source="meta"), TODAY)
    assert 0 < great.delta <= truth.DELTA_CAP
    old = verdict(extract_claims("Floods today"), facts(shot_date="2019-01-01", date_source="meta"), TODAY)
    assert old.delta == truth.DELTA_WARN


# ---------- script-level place context ----------
def test_place_is_inherited_by_later_lines_until_a_new_place_is_named():
    cs = truth.inherit_places([extract_claims(t) for t in [
        "Heavy rain lashed Mumbai today.", "Commuters waited at flooded stations.", "Meanwhile in Delhi it was dry.",
        "Markets stayed open."]])
    assert [c.place for c in cs] == ["Mumbai", "Mumbai", "Delhi", "Delhi"]
    assert [c.place_inherited for c in cs] == [False, True, False, True]


def test_inherited_place_still_rejects_wrong_city_footage_and_explains_why():
    cs = truth.inherit_places([extract_claims("Rain lashed Mumbai."), extract_claims("Commuters waited at stations.")])
    v = verdict(cs[1], facts(source="pixabay", title="metro, bangkok, thailand"), TODAY)
    assert v.status == "bad" and "carried over" in v.evidence[0] and "Bangkok" in v.evidence[0]


def test_inherited_place_does_not_trigger_stock_label_but_time_and_weather_are_not_inherited():
    cs = truth.inherit_places([extract_claims("Rain lashed Mumbai today."), extract_claims("Streets were busy.")])
    assert cs[1].weather is None and cs[1].time_kind is None
    v = verdict(cs[1], facts(source="pixabay", title="street, people"), TODAY)
    assert v.label is None and v.status == "unverified"


def test_dutch_spelling_resolves():
    assert match_places("Nieuws uit Indonesië, markt")[0][0] == "Indonesia"
