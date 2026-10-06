import re

import pandas as pd
import pytest

from stormsim.eurotop import processing


def test_save_results_keeps_the_location_out_of_the_key(tmp_path):
    results = {
        "location_id": ["Charleston, SC", "LB-1~2"],
        "lifecycle": [0, 0],
        "overtopping_rate": [1.0, 2.0],
        "stage": [0.5, 0.6],
    }

    processing._save_results(results, "hydro_responses.parquet", str(tmp_path))

    names = sorted(p.name for p in tmp_path.iterdir())
    # a space or "~" in an S3 key breaks pyarrow; the filename carries a slug
    assert names == [
        "hydro_responses_loc_Charleston-SC_lc_0.parquet",
        "hydro_responses_loc_LB-1-2_lc_0.parquet",
        "stage_hydro_responses_loc_Charleston-SC_lc_0.parquet",
        "stage_hydro_responses_loc_LB-1-2_lc_0.parquet",
    ]
    # aggregate_q must still pair the files by location
    assert all(re.search(r"loc_([A-Za-z0-9-]+)_lc_(\d+)", name) for name in names)
    # the column keeps what the user typed
    df = pd.read_parquet(tmp_path / "hydro_responses_loc_Charleston-SC_lc_0.parquet")
    assert df["location_id"].tolist() == ["Charleston, SC"]


def _hydrograph(tmp_path, **cols):
    path = tmp_path / "LC-0_storm.parquet"
    pd.DataFrame({"lifecycle": [0, 0], "hydro_tstp": [0, 1], **cols}).to_parquet(path)
    return str(path)


def _echo_location(monkeypatch):
    # stand-in for the physics: hand the location through to _save_results
    monkeypatch.setattr(
        processing,
        "compute_storm_response",
        lambda stm, *a, **k: {"location_id": [stm["location_id"].iloc[0]], "lifecycle": [0], "stage": [1.0]},
    )


def test_the_callers_reach_code_replaces_the_hydrograph_location(tmp_path, monkeypatch):
    _echo_location(monkeypatch)
    lc_file = _hydrograph(tmp_path, location_id=["Spring creek south"] * 2)
    out = tmp_path / "out"
    out.mkdir()

    processing.process_lc_file(lc_file, {"single_file": False, "location_id": "REACH1"}, {}, None, str(out))

    assert sorted(p.name for p in out.iterdir()) == [
        "LC-0_storm_responses_loc_REACH1_lc_0.parquet",
        "stage_LC-0_storm_responses_loc_REACH1_lc_0.parquet",
    ]


def test_a_hydrograph_without_a_location_needs_one_from_the_caller(tmp_path, monkeypatch):
    _echo_location(monkeypatch)
    lc_file = _hydrograph(tmp_path)

    with pytest.raises(ValueError, match="location_id"):
        processing.process_lc_file(lc_file, {"single_file": False}, {}, None, str(tmp_path))
