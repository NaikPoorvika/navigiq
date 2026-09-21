"""Weather via Open-Meteo (section 48).

Free, no API key. DEGRADES GRACEFULLY: if Open-Meteo is unreachable, disabled,
or the date is beyond its forecast horizon, the caller gets
`available=False` with a reason and continues WITHOUT weather optimisation.
Weather is never invented - there is no fallback forecast.

Responses are cached in-process for 30 minutes (bounded, 256 entries) keyed
by rounded coordinates and date, so a burst of requests makes one call.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date as date_type

import httpx

BASE_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 3.0
FAILURE_BACKOFF_S = 300    # after a failure, skip the provider for 5 minutes
FORECAST_HORIZON_DAYS = 15
HEAVY_RAIN_MM = 2.5          # mm/hour within the window that makes outdoor stops a bad idea
RAIN_PROBABILITY_WET = 60    # % chance that counts as "rain likely"
CACHE_TTL_S = 1800
CACHE_MAX = 256

_cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_down_until = 0.0          # monotonic time until which the provider is treated as down


@dataclass
class WeatherWindow:
    available: bool
    heavy_rain_expected: bool = False
    rain_likely: bool = False
    max_precip_mm: float = 0.0
    max_precip_probability: int | None = None
    mean_temp_c: float | None = None
    condition: str = "unknown"
    degraded_reason: str | None = None

    @property
    def wet(self) -> bool:
        return self.heavy_rain_expected or self.rain_likely

    def to_dict(self) -> dict:
        return {
            "available": self.available, "heavy_rain_expected": self.heavy_rain_expected,
            "rain_likely": self.rain_likely, "max_precip_mm": round(self.max_precip_mm, 2),
            "max_precip_probability": self.max_precip_probability,
            "mean_temp_c": self.mean_temp_c, "condition": self.condition,
            "degraded_reason": self.degraded_reason, "source": "open-meteo",
        }


def _cache_get(key: tuple) -> dict | None:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        _cache.move_to_end(key)
        return hit[1]
    return None


def _cache_put(key: tuple, value: dict) -> None:
    _cache[key] = (time.monotonic(), value)
    _cache.move_to_end(key)
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)


async def _fetch_day(lat: float, lon: float, on: date_type) -> dict:
    key = (round(lat, 2), round(lon, 2), on.isoformat())
    cached = _cache_get(key)
    if cached is not None:
        return cached
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        r = await client.get(BASE_URL, params={
            "latitude": key[0], "longitude": key[1],
            "hourly": "temperature_2m,precipitation,precipitation_probability",
            "start_date": key[2], "end_date": key[2], "timezone": "Asia/Kolkata",
        })
        r.raise_for_status()
        data = r.json()
    _cache_put(key, data)
    return data


async def get_window(lat: float, lon: float, on: date_type, start_hour: int,
                     end_hour: int) -> WeatherWindow:
    """Forecast for the requested window only, not the whole day."""
    from app.config import settings
    from app.nlu.timeparse import today_ist
    if not settings.WEATHER_ENABLED:
        return WeatherWindow(available=False, degraded_reason="weather disabled")
    horizon = (on - today_ist()).days
    if horizon < 0 or horizon > FORECAST_HORIZON_DAYS:
        return WeatherWindow(available=False,
                             degraded_reason="date outside the forecast horizon")
    global _down_until
    if time.monotonic() < _down_until:
        # A recent failure: do not make every plan wait for another timeout.
        return WeatherWindow(available=False, degraded_reason="weather service unreachable")
    try:
        data = await _fetch_day(lat, lon, on)
    except Exception as exc:  # noqa: BLE001 - any failure degrades, never crashes
        _down_until = time.monotonic() + FAILURE_BACKOFF_S
        return WeatherWindow(available=False, degraded_reason=f"{type(exc).__name__}")
    return summarize(data, start_hour, end_hour)


def summarize(data: dict, start_hour: int, end_hour: int) -> WeatherWindow:
    hourly = data.get("hourly", {}) or {}
    precip = hourly.get("precipitation") or []
    prob = hourly.get("precipitation_probability") or []
    temps = hourly.get("temperature_2m") or []
    lo = max(0, start_hour)
    hi = min(len(precip), end_hour + 1)
    if lo >= hi:
        return WeatherWindow(available=False, degraded_reason="window outside forecast range")
    window_precip = [p for p in precip[lo:hi] if p is not None]
    window_prob = [p for p in prob[lo:hi] if p is not None] if prob else []
    window_temps = [t for t in temps[lo:hi] if t is not None]
    if not window_precip:
        return WeatherWindow(available=False, degraded_reason="no forecast values")
    max_precip = max(window_precip)
    max_prob = max(window_prob) if window_prob else None
    mean_temp = round(sum(window_temps) / len(window_temps), 1) if window_temps else None
    heavy = max_precip >= HEAVY_RAIN_MM
    likely = heavy or (max_prob is not None and max_prob >= RAIN_PROBABILITY_WET
                       and max_precip > 0.2)
    condition = "heavy_rain" if heavy else ("rain_likely" if likely else (
        "light_rain" if max_precip > 0.1 else "dry"))
    return WeatherWindow(available=True, heavy_rain_expected=heavy, rain_likely=likely,
                         max_precip_mm=max_precip, max_precip_probability=max_prob,
                         mean_temp_c=mean_temp, condition=condition)
