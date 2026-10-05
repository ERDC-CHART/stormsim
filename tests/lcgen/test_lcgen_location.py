"""
An LCG serves every reach in a study, so it carries no location_id unless a
caller passes one. It used to stamp the project's free-text Location on every
row, which no reach code ever matched.
"""
import numpy as np
import pandas as pd

from stormsim.lcgen import simulation

PROB_SCHEDULE = pd.DataFrame(
    {"day_of_year": np.arange(1, 366), "trop_day_cdf": np.linspace(1 / 365, 1.0, 365)}
)
STORM_SET = pd.DataFrame({"storm_id": [11, 22], "cdf": [0.5, 1.0]})
PARAMS = {
    "initialize_year": 2030,
    "lifecycle_duration": 10,
    "num_lcs": 2,
    "lam_target": 2.0,
    "min_arrival_trop_days": 3,
    "seed": 7,
}


def test_no_location_means_no_location_column():
    df = simulation.run_simulation(PROB_SCHEDULE, STORM_SET, PARAMS)
    assert not df.empty
    assert "location_id" not in df.columns
    assert df.columns[0] == "lifecycle"


def test_a_given_location_is_written():
    df = simulation.run_simulation(PROB_SCHEDULE, STORM_SET, PARAMS, location_id="DE001")
    assert (df["location_id"] == "DE001").all()


def test_an_empty_run_has_no_location_column_either():
    df = simulation.run_simulation(PROB_SCHEDULE, STORM_SET, {**PARAMS, "num_lcs": 0})
    assert "location_id" not in df.columns
