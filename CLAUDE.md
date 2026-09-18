# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**StormSim** is a modular Python library for coastal storm lifecycle simulation,
used as the upstream hazard source for the CHART Screening Tool. It models
synthetic storm timelines and their physical impacts on coastal structures.

## Commands

```bash
# Install dependencies
uv sync

# Run lifecycle generation locally
uv run implementation-scripts/lc_generator_main.py --config data/lcgen/config_local.json

# Run hydrograph manipulation
uv run implementation-scripts/hydro_manipulator_main.py --config config-files/hydroManipulator_config.json

# Run EurOtop structure response
uv run implementation-scripts/eurotop_main.py --config config-files/eurotop_run_config.json

# Aggregate overtopping rates across transects
uv run implementation-scripts/q_aggregation_main.py <transect_sim_path>

# Run all tests
uv run pytest tests/

# Run a single test file
uv run pytest tests/hazard_curves/test_jpm.py -v

# Install as a dependency in another project
uv add "stormsim @ git+https://github.com/ERDC-CHART/stormsim.git"
```

## Pipeline Architecture

The simulation runs as a linear pipeline:

```
lcgen (lifecycle generation)
  → hydrograph_manipulator (surge/wave time-series)
    → eurotop (wave runup / overtopping volumes)
          ↓
  eurotop.aggregate_q (aggregate overtopping across transects)
```

Parallel modules handle downstream analysis:

```
hazard_curves (JPM / PST-POT extreme-value statistics)
stage_volume  (DEM-based stage-volume relationships)
```

## Package Structure

Source lives in `src/stormsim/`:

```
src/stormsim/
├── lcgen/                  # Lifecycle generation (Poisson storm arrivals)
│   ├── simulation.py       # run_lc_generator — top-level orchestrator
│   ├── sampling.py         # simulate_lifecycle + rejection sampling
│   ├── load.py             # Load CHS/parquet inputs via DuckDB
│   └── validation.py       # Config + output validation
├── hydrograph_manipulator/ # Surge/wave time-series construction
│   └── HydroManipulator.py # Class with SLR + bias correction methods
├── eurotop/                # Wave runup and overtopping (EurOtop 2018)
│   ├── simulation.py       # run_eurotop — top-level orchestrator
│   ├── processing.py       # Per-file processing loop
│   ├── responses.py        # Structure response calculations
│   ├── runup_and_ot_eurotop_2018.py
│   └── aggregation.py      # aggregate_q — sum overtopping across transects
├── hazard_curves/
│   ├── common.py           # Shared utilities, AEF/AEP grid values
│   ├── jpm/                # Joint Probability Method
│   │   ├── core.py         # Options (pydantic), IntegrationEnum/UncertaintyEnum/TideEnum
│   │   ├── compute.py      # compute() — pure pipeline (no I/O)
│   │   ├── engine.py       # Integration and interpolation internals
│   │   ├── simulation.py   # run_jpm() — config-driven entry point with I/O
│   │   └── plot.py         # PlotOptions
│   └── pst/                # Peaks-over-Threshold (PST/POT)
│       ├── core.py         # ResponseData, PSTOptions (pydantic)
│       ├── cleaner.py      # POT sample cleaning (flag removal, deduplication)
│       ├── fit.py          # fit_hazard_curve — bootstrap ECDF + GPD tail
│       ├── mrl.py          # fit_mrl — mean residual life threshold selection
│       ├── compute.py      # compute() — pure pipeline (no I/O)
│       └── simulation.py   # run_pst() — config-driven entry point with I/O
├── stage_volume/           # DEM-based stage-volume relationships
│   └── processing.py       # StageVolumeConfig, StageVolumeCalculator, run_stage_volume
├── sea_level_rise/         # SLR scenario generation and trend analysis
├── noaa_py/                # NOAA tidal gauge data access
└── utilities/
    ├── storage.py          # StorageContext — local/S3 I/O abstraction
    └── chs_utils.py        # CHS HDF5 file utilities
```

Implementation entry points are in `implementation-scripts/`. Config templates
are in `config-files/` and `data/lcgen/`.

## Key Patterns

### StorageContext

`StorageContext` (`utilities/storage.py`) transparently resolves local vs. S3
paths for all pipeline stages. In Lambda, IAM role credentials are used
automatically — never pass `access_key`/`secret_key` explicitly:

```python
from stormsim.utilities.storage import StorageContext

ctx = StorageContext(config, is_lambda=True)
input_path  = ctx.get_input_path("rel_prob_file")  # resolves to s3:// or local
output_path = ctx.get_output_path()
opts        = ctx.get_pandas_storage_options()     # None for local
```

For SAM local testing with local files, set `LCGEN_USE_LOCAL_INPUTS=true`.

### Entry Point Pattern

Every module exposes two levels:

- **`run_*(config, is_lambda, storage_context)`** — config-driven, handles all
  file I/O via StorageContext, returns a status dict.
- **`compute(data, opts)`** — pure function, no I/O; takes arrays/dataclasses,
  returns arrays. Use this for embedding in larger pipelines.

### Pipeline Entry Points

```python
from stormsim.lcgen import run_lc_generator
from stormsim.hydrograph_manipulator import run_hydro_manipulator
from stormsim.eurotop import run_eurotop, run_aggregate_q
from stormsim.stage_volume import run_stage_volume

run_lc_generator(config)
run_hydro_manipulator(config)
run_eurotop(config)
run_aggregate_q(config)   # config keys: inputs.transect_sim_path
run_stage_volume(config)
```

All `run_*` functions share the same signature:
```python
run_*(config: dict, is_lambda: bool = False, storage_context: StorageContext | None = None)
# returns: {"status": "success", "output": "<output path>"}
```

### Hazard Curves — JPM

```python
from stormsim.hazard_curves import jpm
# or: from stormsim.hazard_curves.jpm import run_jpm, compute, InputData, Options

# Config-driven (reads parquet, writes hc_plot.parquet + hc_table.parquet)
jpm.run_jpm(config)
# config keys: inputs.data_file, outputs,
#              jpm_params: {flag_value, slc}
#              jpm_options: {ua, ur, tide_std, integration_mode, uncertainty_mode,
#                            tide_mode, percentiles, use_aep, return_table}

# Pure compute
input_data = jpm.InputData(
    data=arr,            # N×4: [timestamp, response, skew_tides, DSW]
    flag_value=[],       # sentinel values to exclude
    slc=0.0,             # sea level change (metres)
)
opts = jpm.Options(
    ua=0.37, ur=0.58,
    integration_mode="ITCS",     # int, "ITCS"/"ATCS", or IntegrationEnum
    uncertainty_mode="combined",  # int, string, or UncertaintyEnum
    tide_mode="none",             # int, string, or TideEnum
    percentiles=[16, 84],
    use_aep=False,
    return_table=True,
)
results = jpm.compute(input_data, opts)
# returns: [("plot", array (n_plt, 1+n_prc)), ("table", array (n_tbl, 1+n_prc))]
```

### Hazard Curves — PST

```python
from stormsim.hazard_curves import pst
# or: from stormsim.hazard_curves.pst import run_pst, compute, ResponseData, PSTOptions

# Config-driven (reads parquet, writes hc_plot.parquet, hc_emp.parquet,
#               gpd_params.parquet, mrl_selection.json, mrl_summary.parquet)
pst.run_pst(config)
# config keys: inputs.data_file, outputs,
#              pst_params: {flag_value, n_years, slc, data_type, gpr_mdl}
#              pst_options: {gpd_criterion, percentiles, apply_gpd, bootstrap_sims, use_aep}

# Pure compute — data is N×3 array: [timestamp, response_no_tides, response_with_tides]
response = pst.ResponseData(
    data=arr,
    data_type="POT",     # "POT" or "Timeseries"
    n_years=75.0,        # POT: supply explicitly; Timeseries: inferred from timestamps
    flag_value=[],
    slc=0.0,
)
opts = pst.PSTOptions(
    gpd_criterion=1,     # 1=sample-intensity (λ), 2=min-WMSE
    percentiles=[16, 84],
    apply_gpd=False,
    bootstrap_sims=100,
    use_aep=False,
)
hc_output, mrl_output = pst.compute(response, opts)
```

`PSTOptions` boolean fields (`apply_skew`, `apply_gpd`, `use_aep`) accept `bool`;
pydantic coerces `0`/`1` for backward compatibility.

### Stage-Volume

```python
from stormsim.stage_volume import run_stage_volume, StageVolumeCalculator, StageVolumeConfig

# Config-driven (reads DEM + model area GeoPackage, writes stage_volume.parquet)
run_stage_volume(config)
# config keys: inputs.dem_file, inputs.model_area_file, outputs,
#              stage_volume_params.{stage_units, dem_vertical_units, start, stop, n, volume_to_stage}

# Pure compute
config = StageVolumeConfig(stage_units="feet", dem_vertical_units="meters")
calc = StageVolumeCalculator(dem_data, nodata, cell_area_m2, config)
pairs = calc.get_relationship(start=0.0, stop=10.0, n=100)
# returns list of {"stage": float, "volume": float}
# set volume_to_stage=True to invert (target volume → stage)
```

### DuckDB for Data Loading

`lcgen/load.py` uses DuckDB to read tabular inputs, enabling seamless switching
between local CSV/parquet files and S3 objects. Enable via
`config["inputs"]["use_duckdb"] = True`.

## Tests

Tests live in `tests/`. They use standard pytest `def test_*` functions.

```
tests/
├── conftest.py                    # shared fixtures
├── hazard_curves/
│   ├── conftest.py
│   ├── jpm/test_integration.py
│   ├── pst/test_integration.py, test_components.py, test_data_cleaning.py, test_mrl_stats.py
│   ├── test_jpm.py, test_jpm_units.py
│   └── tools.py
└── stage_volume/
```

**Before running JPM tests for the first time**, generate the parquet input
files from the MATLAB source data:

```bash
cd tests/hazard_curves && uv run --project ../.. python matlab2parquet.py
```

`tests/hazard_curves/pst/` tests require `tables` (PyTables/HDF5):

```bash
uv add --dev tables
```

## Configuration Schema (lcgen)

```json
{
  "simulation_params": {
    "initialize_year": 2000,
    "lifecycle_duration": 100,
    "num_lcs": 50,
    "lam_target": 3.5,
    "min_arrival_trop_days": 2
  },
  "inputs": {
    "use_s3": false,
    "use_duckdb": false,
    "rel_prob_file": "data/lcgen/Relative_probability_bins_Atlantic 4.csv",
    "storm_id_prob_file": "..."
  },
  "outputs": {
    "storage_type": "local",
    "local_directory": "data/outputs/lcgen",
    "filename": "lifecycle_output.csv"
  }
}
```

Local config template: `data/lcgen/config_local.json`
S3 config template: `data/lcgen/config_s3.json`

## Releasing New Versions

1. Bump `version` in `pyproject.toml`
2. Commit and push
3. `git tag v0.1.x && git push origin v0.1.x`
4. GitHub Actions (`.github/workflows/publish.yml`) builds and creates a
   GitHub Release automatically on any `v*` tag push
