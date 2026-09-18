"""
The committed configs in config-files/ must stay in the shape the library
actually reads.

These drifted once already: both files still had their paths at the top level
after the pipeline moved to StorageContext, which reads them from `inputs`.
The hydrograph manipulator then died with "'list' object has no attribute
'get'", and eurotop resolved every path to "" and died on
FileNotFoundError: ''. Nothing caught it, because nothing loaded these files
outside a manual run.
"""
import json
from pathlib import Path

import pytest

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config-files"

# config file -> input keys the library resolves via ctx.get_input_path()
EXPECTED_INPUTS = {
    "eurotop_run_config.json": {"pse_geometry", "lc_data", "stage_vol_file"},
    "hydroManipulator_config.json": {"node_data_path", "lc_path", "tide_config"},
}


def _load(name):
    payload = json.loads((CONFIG_DIR / name).read_text())
    # both entry scripts index [0]; keep the files in one shape
    assert isinstance(payload, list) and len(payload) == 1, (
        f"{name} must be a list of one dict, as both entry scripts index [0]"
    )
    return payload[0]


@pytest.mark.parametrize("name,expected", sorted(EXPECTED_INPUTS.items()))
def test_config_puts_paths_under_inputs(name, expected):
    config = _load(name)
    assert expected <= set(config.get("inputs", {})), (
        f"{name} is missing {expected - set(config.get('inputs', {}))} under 'inputs'; "
        "StorageContext reads paths from there, not the top level"
    )
    # a stale top-level path is the exact shape of the original bug
    assert not expected & set(config), (
        f"{name} still has input paths at the top level: {expected & set(config)}"
    )


@pytest.mark.parametrize("name", sorted(EXPECTED_INPUTS))
def test_config_declares_an_output_directory(name):
    outputs = _load(name).get("outputs", {})
    assert outputs.get("local_directory"), (
        f"{name} needs outputs.local_directory; get_output_path() builds the "
        "destination from it"
    )
    assert "outpath" not in _load(name), f"{name} still uses the old outpath key"


@pytest.mark.parametrize("name", sorted(EXPECTED_INPUTS))
def test_config_paths_exist(name):
    """The referenced inputs are committed, so a fresh clone can run the pipeline."""
    repo_root = CONFIG_DIR.parent
    config = _load(name)
    for key, value in config["inputs"].items():
        path = repo_root / value
        # outputs of an earlier pipeline stage are generated, not committed
        if "outputs" in value:
            continue
        assert path.exists(), f"{name}: inputs.{key} -> {value} does not exist"
