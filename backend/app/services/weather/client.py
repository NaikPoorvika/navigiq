"""NQ-025 - Weather via Open-Meteo.

Free, no API key, no account. The only outbound call NavigIQ makes.

DEGRADES GRACEFULLY: if Open-Meteo is unreachable the planner continues
without weather filtering and says so, rather than failing. Weather improves
an itinerary; its absence must not prevent one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type

import httpx

BASE_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 5.0

# mm/hour over the trip window that makes outdoor stops a bad idea.
HEAVY_RAIN_MM = 2.5


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


async def get_window(
    lat: float,
    lon: float,
    on: date_type,
    start_hour: int,
    end_hour: int,
) -> WeatherWindow:
    """Forecast for the trip window only, not the whole day."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.get(BASE_URL, params={
                "latitude": lat, "longitude": lon,
                "hourly": "temperature_2m,precipitation",
                "start_date": on.isoformat(), "end_date": on.isoformat(),
                "timezone": "Asia/Kolkata",
            })
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        return WeatherWindow(
            available=False,
            degraded_reason=f"{type(exc).__name__}: {exc}")

    hourly = data.get("hourly", {})
    precip = hourly.get("precipitation") or []
    temps = hourly.get("temperature_2m") or []

    lo = max(0, start_hour)
    hi = min(len(precip), end_hour + 1)
    if lo >= hi:
        return WeatherWindow(available=False,
                             degraded_reason="window outside forecast range")

    window_precip = [p for p in precip[lo:hi] if p is not None]
    window_temps = [t for t in temps[lo:hi] if t is not None]

    max_precip = max(window_precip) if window_precip else 0.0
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