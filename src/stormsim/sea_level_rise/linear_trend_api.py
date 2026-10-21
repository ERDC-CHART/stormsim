import pandas as pd

from stormsim.noaa_py import sea_level_trends


def get_noaa_linear_trend(station_id):
    """
    NOAA's linear sea level trend for a station, from stormsim's snapshot
    (stormsim/noaa_py/noaa_sea_level_trends.json), not a live download.

    Returns:
        (pd.DataFrame, np.ndarray): the station's row, and alpha, its trend in
        mm/yr, as a one-element array.

    Raises:
        ValueError: the station is not in the snapshot.
    """
    s = sea_level_trends.station(station_id)
    p = sea_level_trends.provenance()
    print(f"NOAA linear trend for {station_id}: {s['trend_mm_yr']} mm/yr, from the snapshot "
          f"retrieved {p['retrieved_at']} from {p['source']} (sha256 {p['response_sha256'][:12]})")
    data_out = pd.DataFrame([{
        "Station ID": int(station_id),
        "Station Name": s["name"],
        "MSL Trends (mm/yr)": s["trend_mm_yr"],
        "Trend error (mm/yr)": s["trend_error_mm_yr"],
        "Record start": s["record_start"],
        "Record end": s["record_end"],
    }])
    return data_out, data_out["MSL Trends (mm/yr)"].to_numpy()
