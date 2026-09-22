"""Multi-day trips end to end against the fixture database (ADR-031): create,
change one day, change the whole trip, what-if, restore, and the assistant."""
from __future__ import annotations

import secrets
from datetime import timedelta

import pytest

from app.nlu.timeparse import today_ist

pytestmark = pytest.mark.db

D1 = (today_ist() + timedelta(days=1)).isoformat()
D2 = (today_ist() + timedelta(days=2)).isoformat()
TRIP = {"date": D1, "end_date": D2, "start_time": "10:00", "end_time": "18:00",
        "interests": ["garden", "museum", "cafe"], "budget_total": 3000}


def headers() -> dict:
    return {"X-NavigIQ-Session": secrets.token_hex(12)}


def code(r) -> str:
    return r.json()["error"]["code"]


def ids_by_day(it: dict) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for s in it["stops"]:
        out.setdefault(s["day"], []).append(s["poi"]["id"])
    return out


def assert_well_formed(it: dict, budget: int | None = None) -> None:
    assert it["kind"] == "trip" and it["day_count"] == len(it["days"])
    assert [s["seq"] for s in it["stops"]] == list(range(1, len(it["stops"]) + 1))
    ids = [s["poi"]["id"] for s in it["stops"]]
    assert len(ids) == len(set(ids)), "a place repeats across days"
    for d in it["days"]:
        own = [s for s in it["stops"] if s["day"] == d["day"]]
        assert [s["day_seq"] for s in own] == list(range(1, len(own) + 1))
        assert d["summary"]["stop_count"] == len(own)
        assert all(d["start_time"] <= s["arrive"] and s["depart"] <= d["end_time"] for s in own)
    total = sum(s["estimated_cost"]["typical"] for s in it["stops"])
    assert it["summary"]["estimated_cost"]["typical"] == total
    assert it["summary"]["estimated_cost"]["excludes"] == "transportation"
    assert it["transition_note"].startswith("Transition buffers are included")
    if budget is not None:
        assert total <= budget


async def test_trip_create_and_read(async_client):
    h = headers()
    r = await async_client.post("/api/v1/plans", headers=h, json=TRIP)
    assert r.status_code == 201, r.text
    body = r.json()
    it = body["itinerary"]
    assert_well_formed(it, budget=3000)
    assert [d["date"] for d in it["days"]] == [D1, D2]
    assert body["validator_report"]["valid"] and body["validator_report"]["days"]
    assert any("per day" in a for a in body["assumptions"])
    got = (await async_client.get(f"/api/v1/plans/{it['itinerary_id']}", headers=h)).json()
    assert got["itinerary"]["days"][0]["spec"]["date"] == D1
    listed = (await async_client.get("/api/v1/plans", headers=h)).json()["plans"]
    assert listed[0]["day_count"] == 2 and listed[0]["end_date"] == D2


async def test_changing_one_day_keeps_the_others(async_client):
    h = headers()
    it = (await async_client.post("/api/v1/plans", headers=h, json=TRIP)).json()["itinerary"]
    pid = it["itinerary_id"]
    before = ids_by_day(it)

    r = await async_client.post(f"/api/v1/plans/{pid}/modify", headers=h, json={
        "operations": [{"op": "remove_stop", "target_seq": 1, "day": 2}]})
    assert r.status_code == 200, r.text
    new = r.json()["itinerary"]
    assert_well_formed(new)
    after = ids_by_day(new)
    assert after[1] == before[1], "day 1 must not change"
    assert before[2][0] not in after[2]
    assert r.json()["summary"][0].startswith("Day 2: removed")
    assert r.json()["comparison"]["changed_days"] == [2]

    # the same stop named by its trip-wide number
    first_of_day2 = next(s for s in new["stops"] if s["day"] == 2)
    r = await async_client.post(f"/api/v1/plans/{pid}/modify", headers=h, json={
        "operations": [{"op": "remove_stop", "target_seq": first_of_day2["seq"]}]})
    assert r.status_code == 200, r.text
    assert first_of_day2["poi"]["id"] not in ids_by_day(r.json()["itinerary"]).get(2, [])
    assert ids_by_day(r.json()["itinerary"])[1] == before[1]


async def test_day_budget_and_pace_changes(async_client):
    h = headers()
    it = (await async_client.post("/api/v1/plans", headers=h, json=TRIP)).json()["itinerary"]
    pid = it["itinerary_id"]
    r = await async_client.post(f"/api/v1/plans/{pid}/modify", headers=h, json={
        "operations": [{"op": "set_budget", "amount": 300, "day": 1}]})
    assert r.status_code in (200, 409), r.text
    if r.status_code == 200:
        new = r.json()["itinerary"]
        assert new["days"][0]["summary"]["estimated_cost"]["typical"] <= 300
        assert ids_by_day(new)[2] == ids_by_day(it)[2]
        assert new["days"][0]["spec"]["budget_total"] == 300
    else:
        assert code(r) == "INFEASIBLE" and r.json()["error"]["details"]["feasibility"]["day"] == 1

    r = await async_client.post(f"/api/v1/plans/{pid}/modify", headers=h, json={
        "operations": [{"op": "set_pace", "pace": "relaxed"}]})
    assert r.status_code == 200, r.text
    new = r.json()["itinerary"]
    assert_well_formed(new)
    assert all(d["spec"]["pace"] == "relaxed" for d in new["days"])


async def test_trip_what_if_leaves_the_plan_untouched_and_can_be_applied(async_client):
    h = headers()
    it = (await async_client.post("/api/v1/plans", headers=h, json=TRIP)).json()["itinerary"]
    pid = it["itinerary_id"]
    wi = await async_client.post(f"/api/v1/plans/{pid}/what-if", headers=h, json={
        "operations": [{"op": "add_interest", "interest": "romantic", "day": 2}]})
    assert wi.status_code == 200, wi.text
    cmp = wi.json()["comparison"]
    assert [d["day"] for d in cmp["days"]] == [1, 2]
    assert not cmp["days"][0]["changed"]
    current = (await async_client.get(f"/api/v1/plans/{pid}", headers=h)).json()
    assert current["version_no"] == 1 and ids_by_day(current["itinerary"]) == ids_by_day(it)
    applied = await async_client.post(
        f"/api/v1/plans/{pid}/variants/{wi.json()['variant_id']}/apply", headers=h)
    assert applied.status_code == 200 and applied.json()["version_no"] == 2
    assert applied.json()["itinerary"]["kind"] == "trip"
    restored = await async_client.post(f"/api/v1/plans/{pid}/restore/1", headers=h)
    assert restored.status_code == 200, restored.text
    assert ids_by_day(restored.json()["itinerary"]) == ids_by_day(it)
    cmp = (await async_client.get(f"/api/v1/plans/{pid}/compare", headers=h,
                                  params={"a": 1, "b": 2})).json()["comparison"]
    assert cmp["days"] is not None


async def test_trip_change_errors(async_client):
    h = headers()
    it = (await async_client.post("/api/v1/plans", headers=h, json=TRIP)).json()["itinerary"]
    pid = it["itinerary_id"]
    r = await async_client.post(f"/api/v1/plans/{pid}/modify", headers=h, json={
        "operations": [{"op": "set_pace", "pace": "relaxed", "day": 3}]})
    assert r.status_code == 422 and code(r) == "INVALID_MODIFICATION"
    on_day2 = next(s for s in it["stops"] if s["day"] == 2)
    r = await async_client.post(f"/api/v1/plans/{pid}/modify", headers=h, json={
        "operations": [{"op": "add_poi", "poi_id": on_day2["poi"]["id"], "day": 1}]})
    assert r.status_code == 422 and "already on day 2" in r.json()["error"]["message"]
    r = await async_client.post(f"/api/v1/plans/{pid}/modify", headers=h, json={
        "operations": [{"op": "remove_stop", "target_seq": 40}]})
    assert r.status_code == 422

    single = (await async_client.post("/api/v1/plans", headers=h, json={
        **TRIP, "end_date": None})).json()["itinerary"]
    assert single.get("kind") != "trip"
    r = await async_client.post(f"/api/v1/plans/{single['itinerary_id']}/modify", headers=h,
                                json={"operations": [{"op": "set_pace", "pace": "relaxed",
                                                      "day": 2}]})
    assert r.status_code == 422 and "single day" in r.json()["error"]["message"]


@pytest.mark.parametrize("patch", [
    {"end_date": (today_ist() + timedelta(days=9)).isoformat()},    # 9 days
    {"date": D2, "end_date": D1},                                   # backwards
    {"date": None},                                                 # no start
])
async def test_trip_spec_validation(async_client, patch):
    r = await async_client.post("/api/v1/plans", headers=headers(), json={**TRIP, **patch})
    assert r.status_code == 422


async def test_trip_in_the_past_is_rejected_for_its_first_day(async_client):
    r = await async_client.post("/api/v1/plans", headers=headers(), json={
        **TRIP, "date": "2020-01-01", "end_date": "2020-01-02"})
    assert r.status_code == 422 and code(r) == "SEMANTIC_INVALID"
    assert r.json()["error"]["details"]["errors"][0]["message"].startswith("Day 1")


async def chat(client, message, h, cid=None):
    body = {"message": message}
    if cid:
        body["conversation_id"] = cid
    r = await client.post("/api/v1/assistant/chat", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def test_assistant_plans_and_changes_a_trip(async_client):
    h = headers()
    plan = await chat(async_client, "Plan a 2 day trip starting tomorrow with a garden, museum "
                                    "and cafe", h)
    assert plan["ui"]["type"] == "itinerary", plan
    it = plan["data"]["itinerary"]
    assert it["kind"] == "trip" and it["day_count"] == 2
    assert "2-day trip" in plan["text"] and "no place repeats" in plan["text"]
    cid = plan["conversation_id"]
    mod = await chat(async_client, "make day 2 more relaxed", h, cid)
    assert mod["intent"] == "MODIFY_ITINERARY" and mod["ui"]["type"] == "itinerary", mod
    new = mod["data"]["itinerary"]
    assert ids_by_day(new)[1] == ids_by_day(it)[1]
    assert new["days"][1]["spec"]["pace"] == "relaxed"
    assert new["days"][0]["spec"]["pace"] == "balanced"
    rm = await chat(async_client, "remove the first stop on day 2", h, cid)
    assert rm["ui"]["type"] == "itinerary", rm
    first2 = next(s for s in new["stops"] if s["day"] == 2)
    assert first2["poi"]["id"] not in ids_by_day(rm["data"]["itinerary"]).get(2, [])
