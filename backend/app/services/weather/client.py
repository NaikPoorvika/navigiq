"""NQ-025 - Weather via Open-Meteo.

Free, no API key, no account. The only outbound call NavigIQ makes.

ONE REQUEST PER TRIP. get_windows fetches the whole date range in a single
call and slices it per day. A 7-day trip previously made 7 requests at 1-5 s
each. Responses are cached in-process for 10 minutes - a forecast does not
meaningfully change between two plans a minute apart.

DEGRADES GRACEFULLY: if Open-Meteo is unreachable, planning continues without
weather filtering and says so. Weather improves an itinerary; its absence
must not prevent one.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date as date_type

import httpx

BASE_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 8.0
CACHE_TTL_S = 600
CACHE_MAX_ENTRIES = 256

# mm/hour over the trip window that makes outdoor stops a bad idea.
HEAVY_RAIN_MM = 2.5

_cache: dict[tuple, tuple[float, dict]] = {}


@dataclass
class WeatherWindow:
    available: bool
    heavy_rain_expected: bool = False
    max_precip_mm: float = 0.0
    mean_temp_c: float | None = None
    condition: str = "unknown"
    degraded_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "heavy_rain_expected": self.heavy_rain_expected,
            "max_precip_mm": round(self.max_precip_mm, 2),
            "mean_temp_c": self.mean_temp_c,
            "condition": self.condition,
            "degraded_reason": self.degraded_reason,
            "source": "open-meteo",
        }


def window_for_day(
    precip: list,
    temps: list,
    day_offset: int,
    start_hour: int,
    end_hour: int,
) -> WeatherWindow:
    """Summarise one day of a multi-day hourly series. Pure - no network.

    Index 0 of the series is 00:00 local time on the first requested date,
    so day N occupies indexes N*24 .. N*24+23.
    """
    base = day_offset * 24
    lo = base + max(0, start_hour)
    hi = min(len(precip), base + min(23, end_hour) + 1)
    if lo >= hi:
        return WeatherWindow(available=False,
                             degraded_reason="date outside the forecast range")

    window_precip = [p for p in precip[lo:hi] if p is not None]
    window_temps = [t for t in (temps[lo:hi] if temps else []) if t is not None]
    if not window_precip:
        return WeatherWindow(available=False,
                             degraded_reason="no forecast data for this window")

    max_precip = max(window_precip)
    mean_temp = (round(sum(window_temps) / len(window_temps), 1)
                 if window_temps else None)

    if max_precip >= HEAVY_RAIN_MM:
        condition = "heavy_rain"
    elif max_precip > 0.1:
        condition = "light_rain"
    else:
        condition = "clear"

    return WeatherWindow(
        available=True,
        heavy_rain_expected=max_precip >= HEAVY_RAIN_MM,
        max_precip_mm=max_precip,
        mean_temp_c=mean_temp,
        condition=condition,
    )


async def get_windows(
    lat: float,
    lon: float,
    dates: list[date_type],
    start_hour: int,
    end_hour: int,
) -> dict[date_type, WeatherWindow]:
    """Forecast for the trip window on each date, in ONE request."""
    if not dates:
        return {}
    first, last = min(dates), max(dates)
    key = (round(lat, 2), round(lon, 2), first.isoformat(), last.isoformat())
    now = time.monotonic()

    cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_TTL_S:
        hourly = cached[1]
    else:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                r = await client.get(BASE_URL, params={
                    "latitude": lat, "longitude": lon,
                    "hourly": "temperature_2m,precipitation",
                    "start_date": first.isoformat(),
                    "end_date": last.isoformat(),
                    "timezone": "Asia/Kolkata",
                })
                r.raise_for_status()
                hourly = r.json().get("hourly", {})
        except Exception as exc:  # noqa: BLE001
            reason = f"{type(exc).__name__}: {exc}"
            return {d: WeatherWindow(available=False, degraded_reason=reason)
                    for d in dates}

        if len(_cache) >= CACHE_MAX_ENTRIES:
            _cache.clear()
        _cache[key] = (now, hourly)

    precip = hourly.get("precipitation") or []
    temps = hourly.get("temperature_2m") or []
    return {
        d: window_for_day(precip, temps, (d - first).days, start_hour, end_hour)
        for d in dates
    }


async def get_window(
    lat: float,
    lon: float,
    on: date_type,
    start_hour: int,
    end_hour: int,
) -> WeatherWindow:
    """Single-day convenience wrapper."""
    return (await get_windows(lat, lon, [on], start_hour, end_hour))[on]