from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class AggregationError(Exception):
    """Raised when overtopping-rate aggregation cannot proceed at all."""


def _join_storage_path(base: str, child: str) -> str:
    """Join a local path or S3 URI without corrupting the URI scheme."""
    if base.startswith("s3://"):
        return f"{base.rstrip('/')}/{child.lstrip('/')}"
    return str(Path(base) / child)


def _sanitize_header(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", name)
    return sanitized.strip("_")


def _load_stage_volume(stage_volume: Any) -> Optional[pd.DataFrame]:
    """Accept an already-loaded stage-volume table or a path to one."""
    if stage_volume is None or isinstance(stage_volume, pd.DataFrame):
        return stage_volume
    return pd.read_csv(stage_volume)


def _aggregate_stage(
    data_list: List[Tuple[str, pd.DataFrame]], stage_volume: pd.DataFrame
) -> Optional[np.ndarray]:
    """
    Reach-level water level from the total volume delivered behind the reach.

    Each transect's overtopping_volume is already cumulative within a storm and
    already carries that transect's own dt and protection_length (see
    eurotop.responses._compute_eurotop_response), so the reach total is a plain
    row-wise sum. The stage-volume curve then maps the pooled volume to one
    water level for the whole reach.

    Summing q_total and converting once would be wrong whenever transects have
    different protection lengths, which is why the volumes are summed instead.
    """
    if any("overtopping_volume" not in df.columns for _, df in data_list):
        print("Warning: overtopping_volume missing; cannot derive reach stage.")
        return None

    volume_total = np.sum(
        [df["overtopping_volume"].to_numpy(dtype=float) for _, df in data_list], axis=0
    )

    if np.nansum(volume_total) > 0:
        return np.interp(
            volume_total,
            stage_volume.iloc[:, 0].to_numpy(),
            stage_volume.iloc[:, 1].to_numpy(),
        )

    # ponytail: G2 transects (pse type 0) overtop nothing and carry a shoreline
    # water level instead of a pool level, so there is no volume to convert.
    # The reach value is then the highest level along it.
    stages = [df["stage"].to_numpy(dtype=float) for _, df in data_list if "stage" in df]
    if not stages:
        return None
    print("Warning: no overtopping volume; using max transect stage (G2 approach).")
    return np.maximum.reduce(stages)


def aggregate_q(
    transect_sim_path: str, stage_volume: Any = None
) -> Dict[str, Any]:
    """
    Aggregates overtopping rates (q) across multiple transects for each location
    and lifecycle. Writes one parquet per (location, lc) pair to
    <transect_sim_path>/aggregate_responses/.

    Pass stage_volume (the stage-volume table, or a path to it) to also write a
    reach-level `stage` column derived from the summed overtopping volume.
    Downstream consequence modelling consumes `stage`, so without it the
    aggregate cannot stand in for the per-transect responses.

    Input directory layout:
        <transect_sim_path>/
            <transect_name>/
                <lifecycle_filename>_responses_loc_<ID>_lc_<M>.parquet
                                                    # must contain overtopping_rate
                stage_*.parquet                      # ignored

    <ID> is the location_id as written by _save_results — an opaque string
    of letters, digits, and dashes (e.g. DE001). An id containing "_" is
    ambiguous against the _lc_ separator and is not supported.

    Returns a dict describing what was actually written:
        {"pairs_written": <int>, "output_paths": [<str>, ...]}

    Raises AggregationError when aggregation cannot proceed at all:
        - transect_sim_path is not a directory
        - no readable response files were found under it
        - transects disagree on row count for a (location, lc) pair,
          which indicates corrupt upstream output
    """
    stage_volume = _load_stage_volume(stage_volume)

    if transect_sim_path.startswith("s3://"):
        return _aggregate_q_s3(transect_sim_path, stage_volume)

    base_path = Path(transect_sim_path)
    if not base_path.is_dir():
        raise AggregationError(
            f"Aggregation input is not a directory: {transect_sim_path}"
        )

    aggregation_map: Dict[Tuple[str, int], List[Tuple[str, pd.DataFrame]]] = {}

    print(f"Scanning directory: {transect_sim_path}")
    subfolders = [d for d in base_path.iterdir() if d.is_dir()]
    print(f"Found {len(subfolders)} subfolders.")

    for transect_dir in subfolders:
        transect_name = transect_dir.name
        for file_path in transect_dir.glob("*.parquet"):
            if file_path.name.startswith("stage_"):
                continue
            match = re.search(r"loc_([A-Za-z0-9-]+)_lc_(\d+)", file_path.name)
            if not match:
                continue
            key = (match.group(1), int(match.group(2)))
            try:
                df = pd.read_parquet(file_path)
                if "overtopping_rate" not in df.columns:
                    print(f"Warning: Missing overtopping_rate column: {file_path}")
                    continue
                aggregation_map.setdefault(key, []).append((transect_name, df))
            except Exception as e:
                print(f"Warning: Failed to read {file_path}: {e}")

    if not aggregation_map:
        raise AggregationError(
            f"No readable response files found under {transect_sim_path}"
        )

    output_dir = base_path / "aggregate_responses"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Aggregating data for {len(aggregation_map)} unique (location, lc) pairs...")

    _response_cols = {"overtopping_rate", "runup", "overtopping_volume", "stage"}
    output_paths: List[str] = []

    for (location_id, lc_id), data_list in aggregation_map.items():
        # Sort so the reference frame and column order do not depend on
        # directory enumeration order.
        data_list.sort(key=lambda item: item[0])
        _, first_df = data_list[0]
        metadata_cols = [c for c in first_df.columns if c not in _response_cols]
        out_df = first_df[metadata_cols].copy()

        q_cols = []
        for transect_name, df in data_list:
            if len(df) != len(out_df):
                # Responses for one (location, lc) pair come from one run
                # and must agree; a mismatch means corrupt upstream output.
                # Skipping would write an under-summed q_total as if it
                # were the total.
                raise AggregationError(
                    f"Row count mismatch for {transect_name} at location "
                    f"{location_id}, LC {lc_id}: {len(df)} rows vs "
                    f"{len(out_df)} in {data_list[0][0]}"
                )
            col = f"q_{_sanitize_header(transect_name)}"
            out_df[col] = df["overtopping_rate"].values
            q_cols.append(col)

        out_df["q_total"] = out_df[q_cols].sum(axis=1)
        if stage_volume is not None:
            stage_values = _aggregate_stage(data_list, stage_volume)
            if stage_values is not None:
                out_df["stage"] = stage_values
        out_name = f"q_aggregate_loc_{location_id}_lc_{lc_id}.parquet"
        out_path = output_dir / out_name
        out_df.to_parquet(out_path)
        output_paths.append(str(out_path))
        print(f"  Saved: {out_name} (included {len(q_cols)} transects)")

    return {
        "pairs_written": len(output_paths),
        "output_paths": output_paths,
    }


def _aggregate_q_s3(
    transect_sim_path: str, stage_volume: Optional[pd.DataFrame] = None
) -> Dict[str, Any]:
    """Aggregate transect response parquet files stored under an S3 prefix."""
    from urllib.parse import urlparse

    import boto3

    parsed = urlparse(transect_sim_path)
    prefix = parsed.path.lstrip("/").rstrip("/") + "/"
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    aggregation_map: Dict[Tuple[str, int], List[Tuple[str, pd.DataFrame]]] = {}

    for page in paginator.paginate(Bucket=parsed.netloc, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            relative_key = key[len(prefix):]
            # Only depth-1 keys are transect responses. A nested key
            # (a backup or archive copy) would re-enter under the same
            # transect name and double-count that transect in q_total.
            parts = relative_key.split("/")
            if len(parts) != 2 or parts[0] == "aggregate_responses":
                continue
            filename = parts[1]
            if not filename.endswith(".parquet") or filename.startswith("stage_"):
                continue

            match = re.search(r"loc_([A-Za-z0-9-]+)_lc_(\d+)", filename)
            if not match:
                continue

            file_path = f"s3://{parsed.netloc}/{key}"
            try:
                df = pd.read_parquet(file_path)
                if "overtopping_rate" not in df.columns:
                    print(f"Warning: Missing overtopping_rate column: {file_path}")
                    continue
                key_pair = (match.group(1), int(match.group(2)))
                aggregation_map.setdefault(key_pair, []).append((parts[0], df))
            except Exception as e:
                print(f"Warning: Failed to read {file_path}: {e}")

    if not aggregation_map:
        raise AggregationError(
            f"No readable response files found under {transect_sim_path}"
        )

    output_prefix = _join_storage_path(transect_sim_path, "aggregate_responses")
    print(f"Aggregating data for {len(aggregation_map)} unique (location, lc) pairs...")
    response_cols = {"overtopping_rate", "runup", "overtopping_volume", "stage"}
    output_paths: List[str] = []

    for (location_id, lc_id), data_list in aggregation_map.items():
        # Sort so the reference frame and column order do not depend on
        # listing order.
        data_list.sort(key=lambda item: item[0])
        _, first_df = data_list[0]
        metadata_cols = [c for c in first_df.columns if c not in response_cols]
        out_df = first_df[metadata_cols].copy()

        q_cols = []
        for transect_name, df in data_list:
            if len(df) != len(out_df):
                # See the local branch: a mismatch is corrupt upstream
                # output, and skipping writes an under-summed q_total.
                raise AggregationError(
                    f"Row count mismatch for {transect_name} at location "
                    f"{location_id}, LC {lc_id}: {len(df)} rows vs "
                    f"{len(out_df)} in {data_list[0][0]}"
                )
            col = f"q_{_sanitize_header(transect_name)}"
            out_df[col] = df["overtopping_rate"].values
            q_cols.append(col)

        out_df["q_total"] = out_df[q_cols].sum(axis=1)
        if stage_volume is not None:
            stage_values = _aggregate_stage(data_list, stage_volume)
            if stage_values is not None:
                out_df["stage"] = stage_values
        out_name = f"q_aggregate_loc_{location_id}_lc_{lc_id}.parquet"
        output_path = _join_storage_path(output_prefix, out_name)
        out_df.to_parquet(output_path, index=False)
        output_paths.append(output_path)
        print(f"  Saved: {out_name} (included {len(q_cols)} transects)")

    return {
        "pairs_written": len(output_paths),
        "output_paths": output_paths,
    }


def run_aggregate_q(
    config: Dict[str, Any],
    is_lambda: bool = False,
    storage_context: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Standard entry point for overtopping aggregation.

    Config keys:
      inputs.transect_sim_path — directory containing per-transect eurotop output subfolders
      inputs.stage_vol_file — optional stage-volume table; supplying it adds the
        reach-level `stage` column that consequence modelling reads

    Output is written to <transect_sim_path>/aggregate_responses/.
    """
    from ..utilities.storage import StorageContext

    ctx = storage_context or StorageContext(config, is_lambda=is_lambda)
    transect_sim_path = ctx.get_input_path("transect_sim_path")
    stage_vol_file = ctx.get_input_path("stage_vol_file") or None
    aggregation_result = aggregate_q(transect_sim_path, stage_vol_file)
    output_dir = _join_storage_path(transect_sim_path, "aggregate_responses")
    return {
        "status": "success",
        "output": output_dir,
        "pairs_written": aggregation_result["pairs_written"],
        "output_paths": aggregation_result["output_paths"],
    }
