import json
import pandas as pd
import os
import warnings
from typing import Dict, Any, Optional, List

from .processing import process_lc_file
from .aggregation import aggregate_q
from ..utilities.storage import StorageContext

def run_eurotop(config: Dict[str, Any], is_lambda: bool = False, storage_context: Optional[StorageContext] = None) -> Dict[str, Any]:
    """
    Standard entry point for Eurotop processing.
    """
    warnings.filterwarnings("ignore")
    ctx = storage_context or StorageContext(config, is_lambda=is_lambda)
    
    lc_data_path = ctx.get_input_path("lc_data")
    pse_geometry_path = ctx.get_input_path("pse_geometry")
    stage_vol_file_path = ctx.get_input_path("stage_vol_file")
    outpath = ctx.get_output_path()

    # Load PSE config and Stage Vol file
    if pse_geometry_path.startswith("s3://"):
        import boto3
        from urllib.parse import urlparse
        parsed = urlparse(pse_geometry_path)
        body = boto3.client("s3").get_object(
            Bucket=parsed.netloc, Key=parsed.path.lstrip("/")
        )["Body"].read()
        pse_config = json.loads(body)
    else:
        with open(pse_geometry_path, "r") as f:
            pse_config = json.load(f)
    s_v_file = pd.read_csv(stage_vol_file_path)

    # Determine files to process
    if not lc_data_path.startswith("s3://") and os.path.isdir(lc_data_path):
        file_to_process = [
            os.path.join(lc_data_path, f)
            for f in os.listdir(lc_data_path)
            if f.lower().endswith(".parquet")
        ]
        config["single_file"] = False
    else:
        file_to_process = [lc_data_path]
        config["single_file"] = True

    print(f"Files to process: {len(file_to_process)}")
    print(f"Output folder: {outpath}")

    # Assuming 1 Savepoint Per Reach
    # All transects will use the same forcing data for now
    for lc_file in file_to_process:
        for pse_xsec in pse_config:
            # Make Sure Each Transect Has Its Own Folder
            transect_outpath = os.path.join(outpath, pse_xsec["name"])
            if not transect_outpath.startswith("s3://"):
                os.makedirs(transect_outpath, exist_ok=True)
            
            # process_lc_file might need storage_options for S3 - 
            # for now passing the raw path which pandas can handle if s3://
            process_lc_file(lc_file, config, pse_xsec, s_v_file, transect_outpath)

    # Aggregation is a post-processing step; preserve the completed transect
    # outputs when it cannot run, but do not call the run a success. A caller
    # that only reads status would otherwise record a finished job for a run
    # that produced no aggregate at all.
    try:
        aggregation_result = aggregate_q(outpath, s_v_file)
    except Exception as error:
        print(f"Warning: Response aggregation failed: {error}")
        return {
            "status": "partial",
            "output": outpath,
            "aggregated": 0,
            "aggregation_error": str(error),
        }

    return {
        "status": "success",
        "output": outpath,
        "aggregated": aggregation_result["pairs_written"],
        "pairs_written": aggregation_result["pairs_written"],
        "output_paths": aggregation_result["output_paths"],
    }
