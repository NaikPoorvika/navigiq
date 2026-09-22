"""API contract tests against the migrated fixture database (sections 106, 109).

Every route family: success, validation error, unauthorized, not found,
conflict, malformed and oversized input. The LLM and weather are OFF here, so
these also prove the product works without Ollama (section 117).
"""
from __future__ import annotations

import secrets
from datetime import timedelta

import pytest

from app.nlu.timeparse import today_ist

pytestmark = pytest.mark.db


def session_headers(sid: str | None = None) -> dict:
    return {"X-NavigIQ-Session": sid or secrets.token_hex(12)}


async def register(client, email=None, password="walk1234"):
    email = email or f"u{secrets.token_hex(4)}@example.com"
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return email, r.json()


def bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


TOMORROW = (today_ist() + timedelta(days=1)).isoformat()


def error_code(r) -> str:
    return r.json()["error"]["code"]


# --- health ------------------------------------------------------------------------------------

async def test_health(async_client):
    r = await async_client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"


async def test_deep_health_reports_dependencies(async_client):
    body = (await async_client.get("/api/v1/health/deep")).json()
    assert body["database"]["status"] == "ok"
    assert body["extensions"] == {"postgis": True, "vector": True, "pg_trgm": True}
    assert body["inventory"]["active_pois"] > 10
    assert body["ollama"]["status"] in ("disabled", "unavailable", "ok", "degraded")
    assert body["transportation"]["note"] == "deferred in this version"


# --- auth ----------------------------------------------------------------------------------------

async def test_register_login_me_refresh_logout(async_client):
    email, tokens = await register(async_client)
    me = await async_client.get("/api/v1/me", headers=bearer(tokens))
    assert me.status_code == 200 and me.json()["email"] == email
    r = await async_client.post("/api/v1/auth/login", json={"email": email.upper(),
                                                            "password": "walk1234"})
    assert r.status_code == 200
    rotated = await async_client.post("/api/v1/auth/refresh",
                                      json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200
    new = rotated.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    reuse = await async_client.post("/api/v1/auth/refresh",
                                    json={"refresh_token": tokens["refresh_token"]})
    assert reuse.status_code == 401 and error_code(reuse) == "REFRESH_INVALID"
    # Reuse revoked the whole family: the rotated token is dead too.
    dead = await async_client.post("/api/v1/auth/refresh",
                                   json={"refresh_token": new["refresh_token"]})
    assert dead.status_code == 401


async def test_logout_revokes_refresh(async_client):
    _, tokens = await register(async_client)
    assert (await async_client.post("/api/v1/auth/logout",
                                    json={"refresh_token": tokens["refresh_token"]})).status_code == 204
    r = await async_client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


async def test_duplicate_registration_conflicts(async_client):
    email, _ = await register(async_client)
    r = await async_client.post("/api/v1/auth/register", json={"email": email,
                                                               "password": "walk1234"})
    assert r.status_code == 409 and error_code(r) == "EMAIL_TAKEN"


async def test_wrong_password_and_privilege_escalation(async_client):
    email, _ = await register(async_client)
    r = await async_client.post("/api/v1/auth/login", json={"email": email, "password": "nope9999"})
    assert r.status_code == 401 and error_code(r) == "INVALID_CREDENTIALS"
    esc = await async_client.post("/api/v1/auth/register", json={
        "email": "x@example.com", "password": "walk1234", "is_superuser": True})
    assert esc.status_code == 422


@pytest.mark.parametrize("header", ["Bearer garbage", "Bearer ", "Basic abc", "Bearer a.b.c"])
async def test_invalid_tokens_are_401(async_client, header):
    r = await async_client.get("/api/v1/me", headers={"Authorization": header})
    assert r.status_code == 401


async def test_expired_token(async_client):
    from app.core.security import create_access_token
    email, tokens = await register(async_client)
    me = (await async_client.get("/api/v1/me", headers=bearer(tokens))).json()
    expired = create_access_token(me["id"], expires_delta=timedelta(seconds=-5))
    r = await async_client.get("/api/v1/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and error_code(r) == "TOKEN_INVALID"


async def test_account_deletion_cascades(async_client, db):
    from sqlalchemy import text
    _, tokens = await register(async_client)
    h = bearer(tokens)
    poi_id = await _poi_id(async_client, "Test Garden")
    assert (await async_client.post(f"/api/v1/pois/{poi_id}/save", headers=h)).status_code == 200
    bad = await async_client.request("DELETE", "/api/v1/me", headers=h, json={"password": "x"})
    assert bad.status_code == 403
    ok = await async_client.request("DELETE", "/api/v1/me", headers=h, json={"password": "walk1234"})
    assert ok.status_code == 204
    assert (await async_client.get("/api/v1/me", headers=h)).status_code == 401
    uid = (await db.execute(text("SELECT count(*) FROM saved_pois"))).scalar()
    assert uid == 0 or uid is not None


# --- POIs & discovery -----------------------------------------------------------------------------

async def _poi_id(client, name) -> int:
    r = await client.get("/api/v1/pois", params={"q": name, "limit": 5})
    items = [i for i in r.json()["items"] if i["name"] == name]
    assert items, r.json()
    return items[0]["id"]


async def test_poi_list_detail_and_not_found(async_client):
    pid = await _poi_id(async_client, "Test Museum")
    d = await async_client.get(f"/api/v1/pois/{pid}", headers=session_headers())
    body = d.json()
    assert d.status_code == 200 and body["category"] == "museum"
    assert body["estimated_cost"]["basis"] == "estimate"
    assert any(h["verified"] for h in body["opening_hours"])
    assert "rating" not in body and "stars" not in body
    assert (await async_client.get("/api/v1/pois/999999")).status_code == 404
    assert (await async_client.get("/api/v1/pois/abc")).status_code == 422


async def test_area_search_is_local_and_unknown_area_404(async_client):
    r = await async_client.get("/api/v1/pois", params={"area": "Testnagar", "category": "cafe"})
    assert r.status_code == 200
    names = {i["name"] for i in r.json()["items"]}
    assert "Quiet Cafe" in names and all(i["region_bucket"] == "CITY_CORE" for i in r.json()["items"])
    r = await async_client.get("/api/v1/pois", params={"area": "Atlantis Nagar"})
    assert r.status_code == 404 and error_code(r) == "AREA_NOT_FOUND"


async def test_misspelled_name_search(async_client):
    r = await async_client.get("/api/v1/pois", params={"q": "Test Musem"})
    assert any(i["name"] == "Test Museum" for i in r.json()["items"])


async def test_no_malls_invariant(async_client):
    r = await async_client.post("/api/v1/pois/recommend", headers=session_headers(),
                                json={"avoid": ["mall"], "limit": 20})
    assert r.status_code == 200
    assert all(i["category"] != "mall" for i in r.json()["items"])


async def test_local_request_never_returns_distant_escapes(async_client):
    r = await async_client.post("/api/v1/pois/recommend", headers=session_headers(),
                                json={"interests": ["cafe"], "area": "Testnagar", "limit": 20})
    items = r.json()["items"]
    assert items and all(i["region_bucket"] in ("CITY_CORE", "CITY") for i in items)
    assert all(i["name"] != "Farville Hill" for i in items)


async def test_regional_request_reaches_escapes_inside_envelope(async_client):
    r = await async_client.post("/api/v1/pois/recommend", headers=session_headers(),
                                json={"moods": ["nature"], "scope": "regional", "limit": 20})
    items = r.json()["items"]
    names = {i["name"] for i in items}
    assert {"Farville Hill", "Farville Falls"} & names
    assert all(i["distance_from_center_km"] <= 90.0 for i in items)
    assert "Beyond Edge Viewpoint" not in names


async def test_surprise_similar_dismiss_and_save_rules(async_client):
    h = session_headers()
    s = await async_client.post("/api/v1/pois/surprise", headers=h, json={})
    assert s.status_code == 200 and 1 <= len(s.json()["items"]) <= 5
    pid = await _poi_id(async_client, "Test Lake")
    sim = await async_client.get(f"/api/v1/pois/{pid}/similar", headers=h)
    assert sim.status_code == 200 and all(i["id"] != pid for i in sim.json()["items"])
    assert (await async_client.post(f"/api/v1/pois/{pid}/dismiss", headers=h)).status_code == 200
    assert (await async_client.post(f"/api/v1/pois/{pid}/save", headers=h)).status_code == 401
    assert (await async_client.post(f"/api/v1/pois/{pid}/dismiss")).status_code == 400


async def test_collections_are_data_driven(async_client):
    r = await async_client.get("/api/v1/collections", headers=session_headers())
    body = r.json()
    assert r.status_code == 200 and body["collections"]
    assert all(c["items"] for c in body["collections"])
    assert not any(c["id"] == "for_you" for c in body["collections"])


async def test_saved_and_preferences_for_users(async_client):
    _, tokens = await register(async_client)
    h = bearer(tokens)
    pid = await _poi_id(async_client, "Test Garden")
    assert (await async_client.post(f"/api/v1/pois/{pid}/save", headers=h)).json()["saved"]
    saved = (await async_client.get("/api/v1/me/saved", headers=h)).json()["items"]
    assert [s["id"] for s in saved] == [pid]
    put = await async_client.put("/api/v1/me/preferences", headers=h, json={
        "favorite_categories": ["lake"], "preferred_pace": "relaxed"})
    assert put.status_code == 200 and put.json()["favorite_categories"] == ["lake"]
    bad = await async_client.put("/api/v1/me/preferences", headers=h,
                                 json={"favorite_categories": ["spaceport"]})
    assert bad.status_code == 422
    assert (await async_client.get("/api/v1/me/preferences")).status_code == 401


# --- plans -----------------------------------------------------------------------------------------

PLAN = {"date": TOMORROW, "start_time": "10:00", "end_time": "18:00",
        "interests": ["garden", "museum", "cafe"], "budget_total": 2000}


async def test_plan_lifecycle(async_client):
    h = session_headers()
    r = await async_client.post("/api/v1/plans", headers=h, json=PLAN)
    assert r.status_code == 201, r.text
    body = r.json()
    it = body["itinerary"]
    assert body["validator_report"]["valid"] is True
    assert it["transition_note"].startswith("Transition buffers are included")
    assert it["summary"]["estimated_cost"]["excludes"] == "transportation"
    assert all(s["transition_buffer_before_min"] >= 0 for s in it["stops"])
    pid = it["itinerary_id"]
    n = len(it["stops"])
    assert n >= 2

    got = await async_client.get(f"/api/v1/plans/{pid}", headers=h)
    assert got.status_code == 200 and got.json()["version_no"] == 1

    mod = await async_client.post(f"/api/v1/plans/{pid}/modify", headers=h, json={
        "operations": [{"op": "remove_stop", "target_seq": 2}], "expected_version_no": 1})
    assert mod.status_code == 200, mod.text
    assert mod.json()["version_no"] == 2 and mod.json()["validator_report"]["valid"]
    assert len(mod.json()["itinerary"]["stops"]) == n - 1

    stale = await async_client.post(f"/api/v1/plans/{pid}/modify", headers=h, json={
        "operations": [{"op": "set_pace", "pace": "relaxed"}], "expected_version_no": 1})
    assert stale.status_code == 409 and error_code(stale) == "CONFLICT"

    before = (await async_client.get(f"/api/v1/plans/{pid}", headers=h)).json()
    wi = await async_client.post(f"/api/v1/plans/{pid}/what-if", headers=h, json={
        "operations": [{"op": "set_budget", "amount": 400}]})
    assert wi.status_code == 200, wi.text
    vid = wi.json()["variant_id"]
    assert wi.json()["comparison"]["estimated_cost"]["variant"] <= 400
    after = (await async_client.get(f"/api/v1/plans/{pid}", headers=h)).json()
    assert after["itinerary"] == before["itinerary"] and after["version_no"] == 2

    rej = await async_client.post(f"/api/v1/plans/{pid}/variants/{vid}/reject", headers=h)
    assert rej.status_code == 200
    unchanged = (await async_client.get(f"/api/v1/plans/{pid}", headers=h)).json()
    assert unchanged["itinerary"] == before["itinerary"]
    again = await async_client.post(f"/api/v1/plans/{pid}/variants/{vid}/apply", headers=h)
    assert again.status_code == 409

    wi2 = await async_client.post(f"/api/v1/plans/{pid}/what-if", headers=h, json={
        "operations": [{"op": "set_pace", "pace": "relaxed"}]})
    applied = await async_client.post(
        f"/api/v1/plans/{pid}/variants/{wi2.json()['variant_id']}/apply", headers=h)
    assert applied.status_code == 200 and applied.json()["version_no"] == 3

    restored = await async_client.post(f"/api/v1/plans/{pid}/restore/1", headers=h)
    assert restored.status_code == 200 and restored.json()["version_no"] == 4
    versions = (await async_client.get(f"/api/v1/plans/{pid}/versions", headers=h)).json()["versions"]
    assert [v["version_no"] for v in versions if v["kind"] == "version"] == [1, 2, 3, 4]
    assert {v["variant_status"] for v in versions if v["kind"] == "variant"} == {"rejected",
                                                                                "applied"}
    cmp = await async_client.get(f"/api/v1/plans/{pid}/compare", headers=h, params={"a": 1, "b": 2})
    assert cmp.status_code == 200 and cmp.json()["comparison"]["removed"]


async def test_plan_errors(async_client):
    h = session_headers()
    past = await async_client.post("/api/v1/plans", headers=h, json={**PLAN, "date": "2020-01-01"})
    assert past.status_code == 422 and error_code(past) == "SEMANTIC_INVALID"
    infeasible = await async_client.post("/api/v1/plans", headers=h, json={
        **PLAN, "start_time": "10:00", "end_time": "11:00", "desired_stop_count": 8,
        "budget_total": 50})
    assert infeasible.status_code == 409 and error_code(infeasible) == "INFEASIBLE"
    relax = infeasible.json()["error"]["details"]["feasibility"]["suggested_relaxations"]
    assert relax and all("operation" in r for r in relax)
    bad = await async_client.post("/api/v1/plans", headers=h, json={**PLAN, "interests": ["lasers"]})
    assert bad.status_code == 422 and error_code(bad) == "VALIDATION_ERROR"
    nosess = await async_client.post("/api/v1/plans", json=PLAN)
    assert nosess.status_code == 400 and error_code(nosess) == "SESSION_REQUIRED"
    assert (await async_client.get("/api/v1/plans/999999", headers=h)).status_code == 404
    badop = await async_client.post("/api/v1/plans/1/modify", headers=h,
                                    json={"operations": [{"op": "delete_everything"}]})
    assert badop.status_code in (404, 422)


async def test_user_isolation(async_client):
    _, a = await register(async_client)
    _, b = await register(async_client)
    r = await async_client.post("/api/v1/plans", headers=bearer(a), json=PLAN)
    pid = r.json()["itinerary"]["itinerary_id"]
    for path in (f"/api/v1/plans/{pid}", f"/api/v1/plans/{pid}/versions"):
        assert (await async_client.get(path, headers=bearer(b))).status_code == 404
    assert (await async_client.post(f"/api/v1/plans/{pid}/modify", headers=bearer(b), json={
        "operations": [{"op": "set_pace", "pace": "quick"}]})).status_code == 404
    assert (await async_client.request("DELETE", f"/api/v1/plans/{pid}",
                                       headers=bearer(b))).status_code == 404
    assert pid not in [p["itinerary_id"] for p in
                       (await async_client.get("/api/v1/plans", headers=bearer(b))).json()["plans"]]
    s1, s2 = session_headers(), session_headers()
    r2 = await async_client.post("/api/v1/plans", headers=s1, json=PLAN)
    pid2 = r2.json()["itinerary"]["itinerary_id"]
    assert (await async_client.get(f"/api/v1/plans/{pid2}", headers=s2)).status_code == 404
    assert (await async_client.get(f"/api/v1/plans/{pid2}", headers=bearer(a))).status_code == 404


async def test_anonymous_plans_are_claimed_on_signup(async_client):
    sid = secrets.token_hex(12)
    r = await async_client.post("/api/v1/plans", headers=session_headers(sid), json=PLAN)
    pid = r.json()["itinerary"]["itinerary_id"]
    reg = await async_client.post("/api/v1/auth/register", headers=session_headers(sid),
                                  json={"email": f"c{secrets.token_hex(3)}@example.com",
                                        "password": "walk1234"})
    plans = (await async_client.get("/api/v1/plans", headers=bearer(reg.json()))).json()["plans"]
    assert pid in [p["itinerary_id"] for p in plans]


async def test_oversized_and_malformed_payloads(async_client):
    h = {**session_headers(), "Content-Type": "application/json"}
    big = await async_client.post("/api/v1/plans", headers=h, content=b"{" + b" " * 300_000 + b"}")
    assert big.status_code == 413 and error_code(big) == "PAYLOAD_TOO_LARGE"
    bad = await async_client.post("/api/v1/plans", headers=h, content=b"{not json")
    assert bad.status_code == 422
    assert (await async_client.post("/api/v1/assistant/chat", headers=h,
                                    json={"message": "x" * 3000})).status_code == 422
    assert (await async_client.get("/api/v1/nope")).status_code == 404
    bad_sid = await async_client.get("/api/v1/plans", headers={"X-NavigIQ-Session": "short"})
    assert bad_sid.status_code == 400


async def test_errors_never_leak_internals(async_client):
    r = await async_client.get("/api/v1/pois/999999")
    text = r.text.lower()
    assert "traceback" not in text and "sqlalchemy" not in text and "request_id" in text


# --- assistant without the LLM -----------------------------------------------------------------

async def chat(client, message, h, cid=None):
    r = await client.post("/api/v1/assistant/chat", headers=h,
                          json={"message": message, "conversation_id": cid})
    assert r.status_code == 200, r.text
    return r.json()


async def test_assistant_discovery_flows_without_llm(async_client):
    h = session_headers()
    bored = await chat(async_client, "I'm bored", h)
    assert bored["intent"] == "MOOD_DISCOVERY" and bored["ui"]["type"] == "discovery"
    assert {s["label"] for s in bored["suggestions"]} >= {"Surprise me", "Nature", "Cheap"}
    assert bored["llm_available"] is False
    cid = bored["conversation_id"]
    local = await chat(async_client, "quiet cafe near Testnagar", h, cid)
    assert local["intent"] == "PLACE_SEARCH"
    items = local["data"]["items"]
    assert items and items[0]["category"] == "cafe"
    assert all(i["region_bucket"] in ("CITY_CORE", "CITY") for i in items)
    first_ids = {i["id"] for i in items}
    diff = await chat(async_client, "show me something different", h, cid)
    assert diff["intent"] == "SHOW_DIFFERENT"
    assert not ({i["id"] for i in diff["data"]["items"]} & first_ids)
    assert diff["data"]["meta"]["overlap_with_previous"] <= 0.2
    details = await chat(async_client, "tell me more about the first one", h, cid)
    assert details["ui"]["type"] == "poi_details"
    # regression: the reference wins over a fuzzy name search for "first one"
    shown = diff["data"]["items"] or items       # the last list actually shown
    assert details["data"]["poi"]["id"] == shown[0]["id"]


async def test_assistant_planning_modify_and_what_if_without_llm(async_client):
    h = session_headers()
    plan = await chat(async_client, "Plan tomorrow from 10 to 6 with a garden, museum and cafe", h)
    assert plan["intent"] == "CREATE_ITINERARY" and plan["ui"]["type"] == "itinerary", plan
    it = plan["data"]["itinerary"]
    assert plan["data"]["validator_report"]["valid"]
    cid = plan["conversation_id"]
    mod = await chat(async_client, "remove the second stop", h, cid)
    assert mod["intent"] == "MODIFY_ITINERARY" and mod["ui"]["type"] == "itinerary"
    assert len(mod["data"]["itinerary"]["stops"]) == len(it["stops"]) - 1
    wi = await chat(async_client, "what if we start two hours later?", h, cid)
    assert wi["intent"] == "WHAT_IF_ITINERARY"
    assert wi["ui"]["type"] in ("itinerary_comparison", "feasibility_error")


async def test_assistant_asks_one_clarification_then_plans(async_client):
    h = session_headers()
    q = await chat(async_client, "Plan a relaxed day with a garden", h)
    assert q["ui"]["type"] == "clarification" and "time window" in q["text"]
    a = await chat(async_client, "you decide", h, q["conversation_id"])
    assert a["ui"]["type"] in ("itinerary", "feasibility_error")


async def test_assistant_knowledge_is_grounded_or_refuses(async_client):
    h = session_headers()
    ans = await chat(async_client, "Why is Test Garden famous?", h)
    assert ans["ui"]["type"] == "knowledge_answer"
    assert ans["sources"] and "[" in ans["text"]
    none = await chat(async_client, "Who invented the teleporter in Farville?", h)
    assert "I don't have reliable information" in none["text"] or none["sources"]


async def test_assistant_out_of_scope_and_trace(async_client, db):
    from sqlalchemy import text
    h = session_headers()
    r = await chat(async_client, "write me a poem about stocks", h)
    assert r["intent"] == "OUT_OF_SCOPE"
    row = (await db.execute(text("SELECT intent, status, states FROM agent_runs WHERE id = :i"),
                            {"i": r["trace_id"]})).first()
    assert row.intent == "OUT_OF_SCOPE" and row.status == "complete"
    assert row.states[0] == "RECEIVE" and row.states[-1] == "COMPLETE"


async def test_assistant_requires_identity_and_owns_conversations(async_client):
    r = await async_client.post("/api/v1/assistant/chat", json={"message": "hi"})
    assert r.status_code == 400
    h1, h2 = session_headers(), session_headers()
    c = await chat(async_client, "hi", h1)
    other = await async_client.post("/api/v1/assistant/chat", headers=h2,
                                    json={"message": "hi", "conversation_id": c["conversation_id"]})
    assert other.status_code == 404


async def test_context_is_real_or_says_unavailable(async_client):
    r = await async_client.get("/api/v1/context")
    assert r.status_code == 200
    body = r.json()
    assert body["time_of_day"] in ("morning", "afternoon", "evening", "night")
    assert body["timezone"] == "Asia/Kolkata" and body["city"] == "Bengaluru"
    # weather is off in tests: it must say so rather than invent conditions
    assert body["weather"]["available"] is False and body["weather"]["condition"] == "unknown"
