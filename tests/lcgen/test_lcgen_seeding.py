"""
Lifecycle generation must be reproducible from a seed.

It used to draw from an unseeded np.random.default_rng() in every lifecycle,
so two runs with identical inputs produced different storm timelines and no
run could be repeated.
"""
import numpy as np
import pandas as pd

from stormsim.lcgen import simulation

PROB_SCHEDULE = pd.DataFrame(
    {"day_of_year": np.arange(1, 366), "trop_day_cdf": np.linspace(1 / 365, 1.0, 365)}
)
STORM_SET = pd.DataFrame({"storm_id": [11, 22, 33, 44], "cdf": [0.25, 0.5, 0.75, 1.0]})


def _params(**extra):
    return {
        "initialize_year": 2030,
        "lifecycle_duration": 20,
        "num_lcs": 5,
        "lam_target": 2.0,
        "min_arrival_trop_days": 3,
        **extra,
    }


def _run(params):
    return simulation.run_simulation(PROB_SCHEDULE, STORM_SET, params)


def test_same_seed_reproduces_every_lifecycle():
    a = _run(_params(seed=1234))
    b = _run(_params(seed=1234))
    assert not a.empty
    assert a["lifecycle"].nunique() > 1
    pd.testing.assert_frame_equal(a, b)


def test_different_seeds_give_different_timelines():
    a = _run(_params(seed=1))
    b = _run(_params(seed=2))
    assert not a.equals(b)


def test_run_lc_generator_reports_the_seed_it_picked(tmp_path, monkeypatch):
    monkeypatch.setattr(simulation.load, "load_relative_probabilities", lambda *a, **k: PROB_SCHEDULE)
    monkeypatch.setattr(simulation.load, "load_storm_id_cdf", lambda *a, **k: STORM_SET)
    out = tmp_path / "lcg.csv"
    config = {
        "inputs": {"rel_prob_file": "unused.csv", "storm_id_prob_file": "unused.csv"},
        "outputs": {"output_file": str(out)},
        "simulation_params": _params(),
    }

    class Ctx:
        s3_config = None
        def get_input_path(self, key):
            return config["inputs"][key]
        def get_output_path(self):
            return str(out)
        def get_pandas_storage_options(self):
            return None

    first = simulation.run_lc_generator(config, storage_context=Ctx())
    first_csv = out.read_text()
    assert isinstance(first["seed"], int)
    assert "seed" not in config["simulation_params"]  # the caller's dict is left alone

    config["simulation_params"] = _params(seed=first["seed"])
    again = simulation.run_lc_generator(config, storage_context=Ctx())
    assert again["seed"] == first["seed"]
    assert out.read_text() == first_csv
