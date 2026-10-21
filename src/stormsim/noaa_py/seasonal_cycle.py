from . import sea_level_trends


def get_station_seasonal_trend(station_id: str):
    """
    NOAA's average seasonal sea level cycle for a station, from stormsim's
    snapshot (noaa_py/noaa_sea_level_trends.json), not a live download.

    Returns:
        dict: 'month' (1-12) and 'level', the month's departure from the
        station's mean sea level in metres.

    Raises:
        ValueError: the station is not in the snapshot.
    """
    s = sea_level_trends.station(station_id)
    p = sea_level_trends.provenance()
    print(f"NOAA seasonal cycle for {station_id}: from the snapshot retrieved "
          f"{p['retrieved_at']} from {p['source']} (sha256 {p['response_sha256'][:12]})")
    return {"month": list(range(1, 13)), "level": list(s["seasonal_m"])}
