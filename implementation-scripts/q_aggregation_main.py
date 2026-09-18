import argparse
from stormsim.eurotop import run_aggregate_q


def main():
    parser = argparse.ArgumentParser(description="Aggregate overtopping rates across transects.")
    parser.add_argument(
        "transect_sim_path",
        type=str,
        help="Path to the directory containing transect subfolders.",
    )
    parser.add_argument(
        "--stage-vol-file",
        type=str,
        default=None,
        help="Stage-volume table; supplying it adds the reach-level stage column.",
    )
    args = parser.parse_args()
    run_aggregate_q({
        "inputs": {
            "transect_sim_path": args.transect_sim_path,
            "stage_vol_file": args.stage_vol_file,
        }
    })


if __name__ == "__main__":
    main()
