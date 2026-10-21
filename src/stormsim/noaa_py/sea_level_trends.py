"""
NOAA sea level trends and average seasonal cycles, read from a snapshot that
ships with stormsim.

Runs never call NOAA. The values are per-station constants NOAA updates about
once a year, and the sltrends/data/ files stormsim used to download were
retired in October 2026, which broke every run. A snapshot also makes a run
repeatable: its values are fixed by the stormsim version it ran.

Refresh the snapshot from NOAA's derived-products API with
    python -c "from stormsim.noaa_py.sea_level_trends import refresh; refresh()"
It refuses to write anything if NOAA's payload no longer looks as expected.
The "Refresh NOAA sea level trends" workflow runs it quarterly, or on demand,
and opens a PR when NOAA's values change. Loading a snapshot older than 18
months prints a warning in the run's log.
"""
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("noaa_sea_level_trends.json")
SOURCE = "https://api.tidesandcurrents.noaa.gov/dpapi/prod/webapi/product/sealvltrends.json?affil=US"
REFRESH_COMMAND = 'python -c "from stormsim.noaa_py.sea_level_trends import refresh; refresh()"'

# NOAA's labels on the payload. A change means the conversions below may be
# wrong, so refresh stops rather than guessing.
EXPECTED_UNITS = {"trendUnits": "inches/decade", "seasonalUnits": "inches"}
INCHES_PER_DECADE_TO_MM_PER_YEAR = 2.54
# NOAA labels the seasonal cycle inches, but the values are feet: they equal
# the station's monthly mean sea level minus its deseasonalized mean, which
# the monthly-means product serves in feet (checked for 8557380, 2026-10-20).
SEASONAL_FEET_TO_M = 0.3048
# seasonalCycleMonth is not in NOAA's documented output, so refresh checks it
# for this station against the cycle implied by its monthly means.
REFERENCE_STATION = "8557380"  # Lewes, record since 1919
CROSS_CHECK_TOLERANCE_M = 0.005
# NOAA adds each past year once a year; the refresh workflow runs quarterly.
STALE_AFTER_DAYS = 548


@lru_cache(maxsize=1)
def _snapshot():
    snapshot = json.loads(SNAPSHOT.read_text())
    retrieved = datetime.fromisoformat(snapshot["provenance"]["retrieved_at"])
    age = (datetime.now(timezone.utc) - retrieved).days
    if age > STALE_AFTER_DAYS:
        print(f"WARNING: stormsim's NOAA sea level trend snapshot was retrieved {age} days ago "
              f"({retrieved.date()}), and NOAA updates it yearly. Refresh it with {REFRESH_COMMAND}")
    return snapshot


def provenance():
    """Where and when the shipped snapshot came from."""
    return _snapshot()["provenance"]


def station(station_id):
    """Trend (mm/yr) and seasonal cycle (m, January to December) for one station."""
    key = str(station_id).strip()
    try:
        return _snapshot()["stations"][key]
    except KeyError:
        raise ValueError(
            f"NOAA station {key} is not in stormsim's sea level trend snapshot "
            f"({SNAPSHOT.name}, retrieved {provenance()['retrieved_at']}). "
            f"Use a station NOAA publishes a trend for, or refresh with {REFRESH_COMMAND}."
        ) from None


def _convert(row):
    """One NOAA row in stormsim's units, or ValueError if it fails a check."""
    sid = row["stationId"]
    for field, unit in EXPECTED_UNITS.items():
        if row.get(field) != unit:
            raise ValueError(f"station {sid}: {field} is {row.get(field)!r}, expected {unit!r}")
    months = sorted(row["seasonalCycleMonth"], key=lambda m: m["month"])
    if [m["month"] for m in months] != list(range(1, 13)):
        raise ValueError(f"station {sid}: seasonal cycle does not cover months 1-12")
    entry = {
        "name": row["stationName"],
        "trend_mm_yr": round(row["trend"] * INCHES_PER_DECADE_TO_MM_PER_YEAR, 3),
        "trend_error_mm_yr": round(row["trendError"] * INCHES_PER_DECADE_TO_MM_PER_YEAR, 3),
        "seasonal_m": [round(m["seasonalVar"] * SEASONAL_FEET_TO_M, 4) for m in months],
        "record_start": row["startDate"],
        "record_end": row["endDate"],
    }
    values = [entry["trend_mm_yr"], entry["trend_error_mm_yr"], *entry["seasonal_m"]]
    if not all(math.isfinite(v) for v in values):
        raise ValueError(f"station {sid}: non-finite trend or seasonal value")
    # Bounds well outside NOAA's US range (-18 to 16 mm/yr, |seasonal| <= 0.21 m
    # in 2026), so only a unit or format change trips them.
    if abs(entry["trend_mm_yr"]) > 30 or max(abs(v) for v in entry["seasonal_m"]) > 0.5:
        raise ValueError(f"station {sid}: trend or seasonal value out of range; units changed?")
    return sid, entry


def _cross_check(row, entry, timeout):
    """ValueError unless the seasonal cycle matches the one the station's
    monthly means imply: monthly mean sea level minus its deseasonalized mean,
    averaged by calendar month."""
    import requests

    response = requests.get(row["monthlyMeans"], timeout=timeout)
    response.raise_for_status()
    means = response.json()
    to_m = {"feet": 0.3048, "meters": 1.0}.get(means.get("units"))
    if to_m is None:
        raise ValueError(f"cross-check: monthly means are in {means.get('units')!r}, expected feet or meters")
    by_month = {m: [] for m in range(1, 13)}
    for r in means["data"]:
        if r.get("msl") is not None and r.get("mslDeseasonalized") is not None:
            by_month[r["month"]].append(r["msl"] - r["mslDeseasonalized"])
    derived = [sum(v) / len(v) * to_m if v else math.nan for v in by_month.values()]
    gaps = [abs(a - b) for a, b in zip(derived, entry["seasonal_m"])]
    worst = max(range(12), key=lambda i: gaps[i] if math.isfinite(gaps[i]) else math.inf)
    if not gaps[worst] <= CROSS_CHECK_TOLERANCE_M:  # also fails on NaN
        raise ValueError(
            f"cross-check: {entry['name']} seasonal cycle from sealvltrends differs from its "
            f"monthly means by {gaps[worst]:.3f} m in month {worst + 1}; units or meaning changed?"
        )


def refresh(path=SNAPSHOT, timeout=60):
    """Fetch NOAA's current trends, check them, and rewrite the snapshot."""
    import requests

    response = requests.get(SOURCE, timeout=timeout)
    response.raise_for_status()
    rows = response.json()["SeaLvlTrends"]
    stations = dict(_convert(row) for row in rows)
    reference = next((row for row in rows if row["stationId"] == REFERENCE_STATION), None)
    if reference is None:
        raise ValueError(f"reference station {REFERENCE_STATION} is missing from NOAA's payload")
    _cross_check(reference, stations[REFERENCE_STATION], timeout)
    if len(stations) < 100:
        raise ValueError(f"only {len(stations)} stations in NOAA's payload; expected about 144")

    try:
        stormsim_version = version("stormsim")
    except PackageNotFoundError:
        stormsim_version = "unknown"
    try:  # the commit of the code that wrote the snapshot, when run from a checkout
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                                capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    snapshot = {
        "provenance": {
            "source": SOURCE,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "http_status": response.status_code,
            "last_modified": response.headers.get("Last-Modified"),
            "etag": response.headers.get("ETag"),
            "response_sha256": hashlib.sha256(response.content).hexdigest(),
            "station_count": len(stations),
            "written_by": f"stormsim {stormsim_version}: {REFRESH_COMMAND}",
            "code_commit": commit,
            "units": {
                "noaa_labels": EXPECTED_UNITS,
                "trend_mm_yr": f"NOAA trend x {INCHES_PER_DECADE_TO_MM_PER_YEAR}",
                "seasonal_m": f"NOAA seasonalVar x {SEASONAL_FEET_TO_M} (values are feet)",
            },
        },
        "stations": dict(sorted(stations.items())),
    }
    Path(path).write_text(json.dumps(snapshot, indent=1) + "\n")
    _snapshot.cache_clear()
    return snapshot["provenance"]
