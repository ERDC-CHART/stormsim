"""
Sea level trends and seasonal cycles come from the snapshot shipped with
stormsim, never a live NOAA download.

The live downloads broke every Hydrograph Manipulator run in October 2026,
when NOAA retired its sltrends/data/ files: the seasonal fetch returned None
and the run crashed, and the trend fetch returned NaN without an error.
"""
import json

import pytest
import requests

from stormsim.noaa_py import sea_level_trends, seasonal_cycle
from stormsim.sea_level_rise import linear_trend_api


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a run must not call NOAA")
    monkeypatch.setattr(requests, "get", refuse)


def test_lewes_comes_from_the_snapshot(no_network):
    _, alpha = linear_trend_api.get_noaa_linear_trend(8557380)
    assert alpha[0] == pytest.approx(3.78, abs=0.01)  # the rate NOAA's old table gave

    cycle = seasonal_cycle.get_station_seasonal_trend("8557380")
    assert cycle["month"] == list(range(1, 13))
    # NOAA's old seasonal file, in metres, had January at -0.082 (CHART's seed copy)
    assert cycle["level"][0] == pytest.approx(-0.082, abs=0.002)

    p = sea_level_trends.provenance()
    assert p["source"].startswith("https://api.tidesandcurrents.noaa.gov/")
    assert len(p["response_sha256"]) == 64 and p["retrieved_at"]


def test_unknown_station_raises(no_network):
    with pytest.raises(ValueError, match="1234567"):
        seasonal_cycle.get_station_seasonal_trend(1234567)


def test_refresh_refuses_changed_units(monkeypatch, tmp_path):
    row = json.loads(sea_level_trends.SNAPSHOT.read_text())["stations"]["8557380"]
    payload = {"SeaLvlTrends": [{
        "stationId": "8557380", "stationName": row["name"],
        "trendUnits": "mm/yr", "seasonalUnits": "inches",  # NOAA switched a unit
        "trend": 3.78, "trendError": 0.13, "startDate": "", "endDate": "",
        "seasonalCycleMonth": [{"month": m, "seasonalVar": 0.0} for m in range(1, 13)],
    }]}

    class Response:
        status_code, headers, content = 200, {}, b"{}"
        def raise_for_status(self): pass
        def json(self): return payload

    monkeypatch.setattr(requests, "get", lambda *a, **k: Response())
    out = tmp_path / "snapshot.json"
    with pytest.raises(ValueError, match="trendUnits"):
        sea_level_trends.refresh(out)
    assert not out.exists()


def test_refresh_refuses_a_seasonal_cycle_its_monthly_means_contradict(monkeypatch, tmp_path):
    lewes = sea_level_trends.station("8557380")
    row = {
        "stationId": "8557380", "stationName": "Lewes",
        "trendUnits": "inches/decade", "seasonalUnits": "inches",
        "trend": 1.49, "trendError": 0.05, "startDate": "", "endDate": "",
        "seasonalCycleMonth": [{"month": m + 1, "seasonalVar": v / 0.3048}
                               for m, v in enumerate(lewes["seasonal_m"])],
        "monthlyMeans": "monthly-means",
    }
    # monthly means with no seasonal swing at all: the two sources disagree
    means = {"units": "feet", "data": [
        {"month": m, "msl": 0.1, "mslDeseasonalized": 0.1} for m in range(1, 13)]}

    class Response:
        status_code, headers, content = 200, {}, b"{}"
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body

    monkeypatch.setattr(requests, "get", lambda url, **k: Response(
        means if url == "monthly-means" else {"SeaLvlTrends": [row]}))
    out = tmp_path / "snapshot.json"
    with pytest.raises(ValueError, match="cross-check"):
        sea_level_trends.refresh(out)
    assert not out.exists()


def test_old_snapshot_warns(monkeypatch, tmp_path, capsys):
    snapshot = json.loads(sea_level_trends.SNAPSHOT.read_text())
    snapshot["provenance"]["retrieved_at"] = "2023-01-01T00:00:00+00:00"
    old = tmp_path / "snapshot.json"
    old.write_text(json.dumps(snapshot))
    monkeypatch.setattr(sea_level_trends, "SNAPSHOT", old)
    sea_level_trends._snapshot.cache_clear()
    try:
        sea_level_trends.station("8557380")
    finally:
        sea_level_trends._snapshot.cache_clear()
    assert "WARNING" in capsys.readouterr().out
