import os
import pandas as pd
from stormsim.utilities.csv_utils import split_df_on_zero, merge_dicts
from stormsim.utilities.chs_utils import write_parquet
from stormsim.eurotop.responses import DEFAULT_SEED, compute_storm_response

OUTPUT_COL_ORDER = [
    "location_id", "date", "stormevent_id", "storm_id", "lifecycle", "runup", "overtopping_rate",
    "overtopping_volume", "stage"
]
STAGE_OUTPUT_COL_ORDER = [
    "location_id", "date", "stormevent_id", "storm_id", "lifecycle", "stage"
]

# ---------------------------------------------------------
# Process a single LC file (single storm or multi-storm)
# ---------------------------------------------------------
def process_lc_file(lc_file, config, pse_config, s_v_file, outfol):
    fname = os.path.basename(lc_file)
    print(f"\nREADING lc: {fname}")

    lc_data = pd.read_parquet(lc_file)
    args = pse_config.copy()

    base_outname = fname.replace(".parquet", "_responses.parquet").replace("EventDate_LC_", "")

    print("COMPUTING responses...")

    # "seed": null in the config opts back into an unseeded run
    seed = config.get("seed", DEFAULT_SEED)

    if config["single_file"]:
        stm_list = split_df_on_zero(lc_data, "hydro_tstp")
        results = [
            compute_storm_response(stm, args, pse_config, s_v_file, seed=seed)
            for stm in stm_list
        ]
        print(f"   {len(results)} storm segments processed")
    else:
        results = [compute_storm_response(lc_data, args, pse_config, s_v_file, seed=seed)]

    print("WRITING data...")
    _save_results(results, base_outname, outfol)
    print("PROCESSING FINISHED")

# ---------------------------------------------------------
# Save computation results to parquet files
# ---------------------------------------------------------
def _save_results(results, base_outname, outfol):
    """Saves computation results to parquet files, grouped by location and lifecycle."""
    if isinstance(results, list):
        results = merge_dicts(results)

    df_out = pd.DataFrame(results)

    for (loc_id, lc), group in df_out.groupby(["location_id", "lifecycle"]):
        group_dict = group.to_dict(orient="list")

        # Build location-specific base filename
        loc_base = base_outname.replace(".parquet", f"_loc_{loc_id}_lc_{lc}.parquet")

        # Save full responses
        full_results = {k: group_dict[k] for k in OUTPUT_COL_ORDER if k in group_dict}
        write_parquet(os.path.join(outfol, loc_base), full_results)

        # Save stage-only responses
        stage_results = {k: group_dict[k] for k in STAGE_OUTPUT_COL_ORDER if k in group_dict}
        write_parquet(os.path.join(outfol, "stage_" + loc_base), stage_results)

