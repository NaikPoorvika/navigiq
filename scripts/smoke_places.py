import asyncio, os, sys
sys.path.insert(0, "backend")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq")

from app.db.base import Base  # noqa: F401
from app.db.session import AsyncSessionLocal
from app.services.places.resolver import resolve_place

QUERIES = ["Indiranagar", "Koramangala", "Malleshwaram", "malleswaram",
           "Jayanagar", "Whitefield", "Nandi Hills", "Cubbon Park",
           "asdfghjkl"]


async def main():
    async with AsyncSessionLocal() as db:
        for q in QUERIES:
            r = await resolve_place(db, q)
            if r.match:
                m = r.match
                print(f"{q:<16} -> {m.name:<24} {m.kind:<14} "
                      f"{m.lat:.5f},{m.lon:.5f}  {r.confidence}")
                if r.needs_clarification and r.alternatives:
                    print(f"{'':<19} ambiguous with: "
                          f"{r.alternatives[0].name} ({r.alternatives[0].kind})")
            else:
                print(f"{q:<16} -> NOT FOUND ({r.confidence})")


asyncio.run(main())