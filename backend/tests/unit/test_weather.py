"""Tests for per-day slicing of a multi-day forecast. No network."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.weather.client import window_for_day  # noqa: E402


def series(days, rain=None, temp=25.0):
    """Hourly arrays for `days` days. rain = {(day, hour): mm}."""
    precip = [0.0] * 24 * days
    temps = [temp] * 24 * days
    for (d, h), mm in (rain or {}).items():
        precip[d * 24 + h] = mm
    return precip, temps


def test_each_day_is_sliced_independently():
    """Rain on day 2 must not leak into day 1 or day 3."""
    p, t = series(3, {(1, 16): 5.0})
    assert not window_for_day(p, t, 0, 15, 20).heavy_rain_expected
    assert window_for_day(p, t, 1, 15, 20).heavy_rain_expected
    assert not window_for_day(p, t, 2, 15, 20).heavy_rain_expected


def test_rain_outside_the_trip_window_is_ignored():
    p, t = series(1, {(0, 8): 10.0})
    assert not window_for_day(p, t, 0, 15, 20).heavy_rain_expected


def test_window_boundaries_are_inclusive():
    """Rain in the trip's last hour counts; rain the hour after does not."""
    p, t = series(1, {(0, 20): 5.0})
    assert window_for_day(p, t, 0, 15, 20).heavy_rain_expected
    p, t = series(1, {(0, 21): 5.0})
    assert not window_for_day(p, t, 0, 15, 20).heavy_rain_expected


def test_light_rain_is_not_heavy():
    p, t = series(1, {(0, 16): 0.5})
    w = window_for_day(p, t, 0, 15, 20)
    assert w.condition == "light_rain"
    assert not w.heavy_rain_expected


def test_day_beyond_the_forecast_is_unavailable_not_invented():
    p, t = series(2)
    w = window_for_day(p, t, 5, 15, 20)
    assert w.available is False
    assert w.degraded_reason


def test_missing_values_are_skipped_not_treated_as_zero():
    p, t = series(1)
    p[15:21] = [None] * 6
    assert window_for_day(p, t, 0, 15, 20).available is False


def test_temperature_is_averaged_over_the_window_only():
    p, t = series(1, temp=20.0)
    t[15:21] = [30.0] * 6
    assert window_for_day(p, t, 0, 15, 20).mean_temp_c == 30.0