import hashlib

import numpy as np
import pandas as pd
from stormsim.eurotop.runup_and_ot_eurotop_2018 import runup_and_ot_eurotop_2018

DEFAULT_SEED = 0


def _first(stm, key):
    """First value of a storm field, whether it arrived as a Series or a scalar."""
    value = stm[key] if key in stm else None
    if hasattr(value, "iloc"):
        return value.iloc[0] if len(value) else None
    if hasattr(value, "__len__") and not isinstance(value, str):
        return value[0] if len(value) else None
    return value


def storm_rng(seed, *identity):
    """
    Generator for one storm's EurOtop uncertainty draw.

    The draw has to stay random across storms — one perturbation reused for
    every storm would be a systematic bias, not uncertainty — while a rerun
    of the same configuration reproduces it. Mixing the storm's identity into
    the seed gives both. seed=None restores unseeded behaviour for callers
    that deliberately want a fresh ensemble member each run.
    """
    if seed is None:
        return np.random.default_rng()
    digest = hashlib.blake2b(
        "|".join(str(part) for part in identity).encode(), digest_size=8
    ).digest()
    return np.random.default_rng([int(seed), int.from_bytes(digest, "big")])


# ---------------------------------------------------------
# Compute responses using G2 approach
# ---------------------------------------------------------
def _compute_g2_response(stm, args, pse_config):
    """Computes response using the G2 approach (G2 approach stage calculation)."""
    # G2 Approach
    # stage_val = swl + 0.7*Ks*np.min([1.12*Hm0, 0.55*ds])
    # Ks = 1 (default), 0.7, 0.5, 0.3 based on rows of buildings
    Ks = pse_config.get("Ks", 1)

    # Compute Water Depth
    ds = args["SWL"] - pse_config["toe_elevation"]

    # Compute Stage
    stage_val = args["SWL"] + 0.7 * Ks * np.minimum(1.12 * args["Hm0"], 0.55 * ds)

    return {
        "location_id": stm["location_id"].to_numpy() if hasattr(stm["location_id"], "to_numpy") else stm["location_id"],
        "stormevent_id": stm["stormevent_id"].to_numpy() if "stormevent_id" in stm and hasattr(stm["stormevent_id"], "to_numpy") else stm.get("stormevent_id"),
        "storm_id": stm["storm_id"].to_numpy(),
        "overtopping_rate": np.zeros_like(stage_val),
        "runup": np.zeros_like(stage_val),
        "overtopping_volume": np.zeros_like(stage_val),
        "stage": stage_val,
        "lifecycle": stm["lifecycle"],
        "date": stm["date"].to_numpy()
    }

# ---------------------------------------------------------
# Compute responses using Eurotop 2018 approach
# ---------------------------------------------------------
def _compute_eurotop_response(stm, args, pse_config, s_v_file, rng=None):
    """Computes response using the Eurotop 2018 empirical formulas."""
    A = runup_and_ot_eurotop_2018(args, rng=rng)
    A.structure_response()

    # Compute dt
    dates = stm["date"].to_numpy().astype("datetime64[s]")
    dt_vals = np.diff(dates).astype("timedelta64[s]").astype(int)
    dt = np.unique(dt_vals)[0] if len(dt_vals) > 0 else 0

    # Compute Overtopping Volume
    Q_val = np.cumsum(A.q) * dt * pse_config["protection_length"]

    # Compute Stage via interpolation
    stage_val = np.interp(
        Q_val,
        s_v_file.iloc[:, 0].to_numpy(),
        s_v_file.iloc[:, 1].to_numpy()
    )

    return {
        "location_id": stm["location_id"].to_numpy() if hasattr(stm["location_id"], "to_numpy") else stm["location_id"],
        "stormevent_id": stm["stormevent_id"].to_numpy() if "stormevent_id" in stm and hasattr(stm["stormevent_id"], "to_numpy") else stm.get("stormevent_id"),
        "storm_id": stm["storm_id"].to_numpy(),
        "overtopping_rate": A.q.copy(),
        "runup": A.R2p.copy(),
        "overtopping_volume": Q_val,
        "stage": stage_val,
        "lifecycle": stm["lifecycle"],
        "date": stm["date"].to_numpy()
    }

# ---------------------------------------------------------
# Compute storm metrics (q, R2p, Q, stage)
# ---------------------------------------------------------
def compute_storm_response(stm, args, pse_config, s_v_file, seed=DEFAULT_SEED):
    # Prepare forcing fields
    SWL  = stm["water_elevation"].to_numpy()
    Hm0  = stm["wave_height"].to_numpy()
    Tm10 = stm["wave_peak_period"].to_numpy()

    args["SWL"]  = SWL
    args["Hm0"]  = Hm0
    args["Tm10"] = Tm10

    # ---------------------------------------------------------
    # EARLY EXIT: If any forcing contains NaN → return NaN outputs
    # ---------------------------------------------------------
    if np.isnan(SWL).any() or np.isnan(Hm0).any() or np.isnan(Tm10).any():
        return {
            "location_id": stm["location_id"].to_numpy() if hasattr(stm["location_id"], "to_numpy") else stm["location_id"],
            "stormevent_id": stm["stormevent_id"].to_numpy() if "stormevent_id" in stm and hasattr(stm["stormevent_id"], "to_numpy") else stm.get("stormevent_id"),
            "storm_id": stm["storm_id"].to_numpy(),
            "overtopping_rate": np.nan,
            "runup": np.nan,
            "overtopping_volume": np.nan,
            "stage": np.nan,
            "lifecycle": stm["lifecycle"],
            "date": stm["date"].to_numpy()
        }

    # Delegate computation based on structure type
    if pse_config["type"] == 0:
        # G2 has no uncertainty draw, so it needs no generator
        return _compute_g2_response(stm, args, pse_config)
    else:
        rng = storm_rng(
            seed,
            pse_config.get("name"),
            _first(stm, "location_id"),
            _first(stm, "lifecycle"),
            _first(stm, "storm_id"),
            _first(stm, "stormevent_id"),
        )
        return _compute_eurotop_response(stm, args, pse_config, s_v_file, rng=rng)
