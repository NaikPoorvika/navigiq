"""Load test for the NavigIQ API (section 122: 1 / 5 / 10 / 25 / 50 users).

Each virtual user is an independent browser session (its own
X-NavigIQ-Session) running a realistic mix of requests with think time:
context, recommendations, search, place details, collections, a plan preview
(CP-SAT), and an assistant message. Nothing is mocked: this hits the running
API, database, solver and (when enabled) the local LLM.

    python scripts/load_test.py --base http://127.0.0.1:8010 --duration 30
    python scripts/load_test.py --levels 1,5 --duration 10 --no-chat

Writes a markdown summary to data/artifacts/reports/load_test.md (and prints it).
"""
from __future__ import annotations

import argparse
import asyncio
import random
import secrets
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

SEARCHES = ["lake", "museum", "temple", "cafe", "garden", "market", "palace", "park"]
MOODS = ["peaceful", "foodie", "cultural", "romantic", "adventurous", "nature"]
CHATS = [
    "parks near Jayanagar",
    "something fun indoors",
    "quiet cafes in Basavanagudi",
    "surprise me",
    "museums for a rainy day",
]


class Stats:
    def __init__(self) -> None:
        self.lat: dict[str, list[float]] = defaultdict(list)
        self.err: dict[str, int] = defaultdict(int)
        self.codes: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    def add(self, name: str, ms: float, status: int) -> None:
        self.lat[name].append(ms)
        self.codes[name][status] += 1
        if status >= 500 or status == 0:
            self.err[name] += 1


async def call(client: httpx.AsyncClient, stats: Stats, name: str, method: str, url: str, **kw) -> dict | None:
    t0 = time.perf_counter()
    try:
        r = await client.request(method, url, **kw)
        stats.add(name, (time.perf_counter() - t0) * 1000, r.status_code)
        return r.json() if r.status_code < 400 and r.headers.get("content-type", "").startswith("application/json") else None
    except Exception:  # noqa: BLE001 - a failed request is a data point
        stats.add(name, (time.perf_counter() - t0) * 1000, 0)
        return None


async def user(base: str, stats: Stats, stop_at: float, chat: bool, rng: random.Random) -> None:
    headers = {"X-NavigIQ-Session": f"load{secrets.token_hex(10)}"}
    tomorrow = (datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=1)).isoformat()
    async with httpx.AsyncClient(base_url=base + "/api/v1", headers=headers, timeout=180) as c:
        poi_ids: list[int] = []
        while time.perf_counter() < stop_at:
            roll = rng.random()
            if roll < 0.10:
                await call(c, stats, "GET /context", "GET", "/context")
            elif roll < 0.35:
                body = await call(c, stats, "POST /pois/recommend", "POST", "/pois/recommend",
                                  json={"moods": [rng.choice(MOODS)], "limit": 8})
                if body:
                    poi_ids = [i["id"] for i in body.get("items", [])][:8] or poi_ids
            elif roll < 0.55:
                body = await call(c, stats, "GET /pois?q=", "GET", "/pois",
                                  params={"q": rng.choice(SEARCHES), "limit": 24})
                if body:
                    poi_ids = [i["id"] for i in body.get("items", [])][:8] or poi_ids
            elif roll < 0.70:
                if poi_ids:
                    await call(c, stats, "GET /pois/{id}", "GET", f"/pois/{rng.choice(poi_ids)}")
            elif roll < 0.80:
                await call(c, stats, "GET /collections", "GET", "/collections", params={"limit": 8})
            elif roll < 0.90 or not chat:
                await call(c, stats, "POST /plans/preview", "POST", "/plans/preview", json={
                    "date": tomorrow, "start_time": "10:00", "end_time": "18:00",
                    "interests": rng.sample(["garden", "museum", "cafe", "lake", "temple"], 2)})
            else:
                await call(c, stats, "POST /assistant/chat", "POST", "/assistant/chat",
                           json={"message": rng.choice(CHATS)})
            await asyncio.sleep(rng.uniform(0.2, 0.8))       # think time


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))
    return s[k]


async def run_level(base: str, users: int, duration: float, chat: bool, seed: int) -> tuple[Stats, float]:
    stats = Stats()
    stop_at = time.perf_counter() + duration
    t0 = time.perf_counter()
    await asyncio.gather(*(user(base, stats, stop_at, chat, random.Random(seed + i)) for i in range(users)))
    return stats, time.perf_counter() - t0


def render(results: list[tuple[int, Stats, float]], args) -> str:
    lines = [
        "# Load test",
        "",
        (f"Target `{args.base}` · {args.duration:.0f} s per level · think time 0.2–0.8 s · "
         f"assistant {'included' if args.chat else 'excluded'}."),
        "Latency in ms. Errors are 5xx and connection failures (429 rate-limits are counted separately).",
        "",
        "| Users | Requests | Req/s | Errors | p50 | p95 | p99 | Slowest endpoint (p95) |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for users, st, elapsed in results:
        all_lat = [v for vals in st.lat.values() for v in vals]
        n = len(all_lat)
        errors = sum(st.err.values())
        slow = max(st.lat.items(), key=lambda kv: pct(kv[1], 95))[0] if st.lat else "-"
        lines.append(f"| {users} | {n} | {n / elapsed:.1f} | {errors} ({(errors / n * 100) if n else 0:.1f}%) | "
                     f"{pct(all_lat, 50):.0f} | {pct(all_lat, 95):.0f} | {pct(all_lat, 99):.0f} | "
                     f"{slow} ({pct(st.lat[slow], 95):.0f}) |")
    lines += ["", "## Per endpoint at the highest level", "",
              "| Endpoint | n | p50 | p95 | max | status codes |", "|---|---:|---:|---:|---:|---|"]
    _, st, _ = results[-1]
    for name, vals in sorted(st.lat.items()):
        codes = ", ".join(f"{k}×{v}" for k, v in sorted(st.codes[name].items()))
        lines.append(f"| {name} | {len(vals)} | {pct(vals, 50):.0f} | {pct(vals, 95):.0f} | "
                     f"{max(vals):.0f} | {codes} |")
    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--levels", default="1,5,10,25,50")
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--no-chat", dest="chat", action="store_false")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "artifacts" / "reports" / "load_test.md"))
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    results = []
    for users in [int(x) for x in args.levels.split(",")]:
        st, elapsed = await run_level(args.base, users, args.duration, args.chat, args.seed)
        n = sum(len(v) for v in st.lat.values())
        print(f"{users:>3} users: {n} requests in {elapsed:.1f}s, errors {sum(st.err.values())}", flush=True)
        results.append((users, st, elapsed))
    report = render(results, args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
