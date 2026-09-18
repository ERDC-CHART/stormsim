"""
The EurOtop 5.18 coefficient draw must be reproducible without becoming
constant.

It used to call np.random.randn() unseeded, so two runs over byte-identical
forcing produced different overtopping rates and different stages — nothing
downstream could be reproduced or compared against a previous run.
"""
import numpy as np
import pandas as pd
import pytest

from stormsim.eurotop.responses import compute_storm_response, storm_rng

PSE = {
    "name": "levee-a",
    "type": 1,
    "app_type": 2,
    "material": "concrete",
    "crest_elevation": 3.2,
    "toe_elevation": -1.3,
    "seaward_slope": 0.25,
    "crest_width": 3,
    "protection_length": 1000,
}

STAGE_VOLUME = pd.DataFrame({"volume": [0, 30, 20000, 100000], "stage": [0, 1, 10, 13]})


def _storm(storm_id=101, lifecycle=1, n=6):
    return pd.DataFrame(
        {
            "location_id": ["DE001"] * n,
            "lifecycle": [lifecycle] * n,
            "stormevent_id": [1] * n,
            "storm_id": [storm_id] * n,
            "date": pd.date_range("2033-10-15", periods=n, freq="30min"),
            "water_elevation": np.linspace(1.0, 3.0, n),
            "wave_height": np.linspace(0.5, 2.0, n),
            "wave_peak_period": np.linspace(6.0, 9.0, n),
        }
    )


def _q(seed, storm_id=101):
    return compute_storm_response(
        _storm(storm_id), PSE.copy(), PSE, STAGE_VOLUME, seed=seed
    )["overtopping_rate"]


def test_same_seed_reproduces_the_run():
    np.testing.assert_array_equal(_q(0), _q(0))


def test_different_seed_gives_a_different_draw():
    assert not np.allclose(_q(0), _q(1))


def test_draw_still_varies_between_storms():
    # one perturbation reused for every storm would be a systematic bias,
    # not uncertainty
    a, b = _q(0, storm_id=101), _q(0, storm_id=102)
    assert not np.allclose(a / a.max(), b / b.max())


def test_seed_none_is_unseeded():
    assert not np.allclose(_q(None), _q(None))


def test_storm_rng_is_stable_per_identity():
    assert storm_rng(7, "levee-a", "DE001", 1, 101).standard_normal() == pytest.approx(
        storm_rng(7, "levee-a", "DE001", 1, 101).standard_normal()
    )
    assert storm_rng(7, "levee-a", "DE001", 1, 101).standard_normal() != pytest.approx(
        storm_rng(7, "levee-b", "DE001", 1, 101).standard_normal()
    )
