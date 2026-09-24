import re

import pandas as pd

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
