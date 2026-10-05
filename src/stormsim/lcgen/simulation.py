import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Any
from . import sampling
from . import load
from . import validation
from ..utilities.storage import StorageContext

def run_simulation(
    prob_schedule: pd.DataFrame,
    storm_set: pd.DataFrame,
    simulation_params: Dict[str, Any],
    location_id: str = "unknown_location",
    columns: Optional[List[str]] = None
) -> pd.DataFrame:
    """Core simulation orchestration logic."""
    init_year = simulation_params["initialize_year"]
    duration = simulation_params["lifecycle_duration"]
    num_lcs = simulation_params["num_lcs"]
    lam_target = simulation_params["lam_target"]
    min_sep = simulation_params["min_arrival_trop_days"]

    if columns is None:
        columns = [
            "location_id",
            "lifecycle",
            "stormevent_id",
            "year_offset",
            "year",
            "month",
            "day",
            "hour",
            "timestamp",
            "storm_id",
        ]

    all_dfs: List[pd.DataFrame] = []

    # One generator for the whole run, so the same seed reproduces every lifecycle.
    # No seed means an unseeded run.
    rng = np.random.default_rng(simulation_params.get("seed"))

    for lc in range(num_lcs):
        df = sampling.simulate_lifecycle(
            lifecycle_index=lc,
            init_year=init_year,
            duration_years=duration,
            lam=lam_target,
            min_sep_days=min_sep,
            prob_schedule=prob_schedule,
            storm_set=storm_set,
            show_progress=False,
            rng=rng,
        )

        if not df.empty:
            df["location_id"] = location_id
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame(columns=columns)

    combined_df = pd.concat(all_dfs, ignore_index=True)
    combined_df.insert(1, "stormevent_id", range(1, len(combined_df) + 1))

    final_cols = [c for c in columns if c in combined_df.columns]
    return combined_df[final_cols]

def run_lc_generator(
    config: Dict[str, Any], 
    is_lambda: bool = False,
    storage_context: Optional[StorageContext] = None
) -> Dict[str, Any]:
    """
    Standard entry point for Lifecycle Generation.
    Replaces duplicated wrappers in API and CLI scripts.
    """
    # Initialize StorageContext if not provided
    ctx = storage_context or StorageContext(config, is_lambda=is_lambda)
    s3_config = ctx.s3_config
    
    # 1. Load Data
    prob_schedule = load.load_relative_probabilities(
        ctx.get_input_path("rel_prob_file"),
        use_duckdb=config["inputs"].get("use_duckdb", False),
        s3_config=s3_config
    )
    storm_set = load.load_storm_id_cdf(
        ctx.get_input_path("storm_id_prob_file"),
        use_duckdb=config["inputs"].get("use_duckdb", False),
        s3_config=s3_config
    )

    # 2. Run Simulation. Pick a seed when none is given and report it, so any run
    # can be repeated.
    simulation_params = dict(config["simulation_params"])
    if simulation_params.get("seed") is None:
        simulation_params["seed"] = int(np.random.default_rng().integers(2**63))
    seed = int(simulation_params["seed"])
    print(f"Lifecycle generation seed: {seed}")
    data = run_simulation(
        prob_schedule=prob_schedule,
        storm_set=storm_set,
        simulation_params=simulation_params,
        location_id=config.get("location_id", "unknown_location")
    )

    # 3. Handle Output
    output_target = ctx.get_output_path()
    storage_options = ctx.get_pandas_storage_options()

    print(f"Writing output to {output_target}...")
    data.to_csv(output_target, index=False, storage_options=storage_options)

    # 4. Validation
    if config.get("runtime", {}).get("validate_lambda", False):
        if not data.empty:
            counts = validation.compute_storm_counts(data)
            validation.verify_lambda(counts, config["simulation_params"]["lam_target"])
        else:
            print("[warn] No data generated; skipping validation.")

    return {"status": "success", "output": output_target, "seed": seed}
