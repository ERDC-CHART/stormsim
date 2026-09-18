# StormSim: Coastal Storm Simulation Workflow

StormSim is a modular Python library for coastal storm lifecycle simulation and physical impact modeling, used as the upstream hazard source for the CHART Screening Tool.

## Workflow Overview

The system operates as a linear pipeline:

**Lifecycle Generator** → **Hydrograph Manipulator** → **Eurotop Structure Response** → **Q Aggregation**

Parallel modules handle downstream analysis:

**Hazard Curves (JPM / PST)** | **Stage-Volume**

### 1. Lifecycle Generation (`lcgen`)
Simulates synthetic timelines of storm events based on historical recurrence rates (λ) and seasonal probability distributions. Uses Poisson sampling and rejection sampling to ensure realistic storm arrival patterns and minimum temporal separation.

### 2. Hydrograph Manipulation
Constructs detailed time-series forcing (surge and wave characteristics) for each simulated storm, with SLR and bias correction methods.

### 3. Eurotop (Structure Response)
Calculates wave runup, overtopping rates, and flood volumes for specific coastal geometries per transect.

### 4. Q Aggregation
Sums overtopping rates across all transects to produce aggregate structure response.

### 5. Hazard Curves (JPM & PST)
Calculates extreme-value statistics and hazard curves using:
- **JPM** (Joint Probability Method) — integrates joint storm parameter distributions
- **PST** (Probabilistic Simulation Technique / POT) — bootstrapped empirical hazard curve with GPD tail extension

### 6. Stage-Volume
Computes stage-volume relationships from a DEM clipped to a model area polygon.

---

## Getting Started

### Installation

**As a developer (editable):**
```bash
git clone https://github.com/ERDC-CHART/stormsim.git
cd stormsim
uv sync
```

**As a library:**
```bash
uv add "stormsim @ git+https://github.com/ERDC-CHART/stormsim.git"
```

### Running Scripts

Standalone entry points are in `implementation-scripts/`:
```bash
uv run implementation-scripts/lc_generator_main.py --config data/lcgen/config_local.json
uv run implementation-scripts/hydro_manipulator_main.py --config config-files/hydroManipulator_config.json
uv run implementation-scripts/eurotop_main.py --config config-files/eurotop_run_config.json
uv run implementation-scripts/q_aggregation_main.py <transect_sim_path>
```

---

## Library Usage

All `run_*` entry points share the same signature:
```python
run_*(config: dict, is_lambda: bool = False, storage_context: StorageContext | None = None)
```

### Pipeline stages

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

### JPM Hazard Curves

```python
from stormsim.hazard_curves import jpm

# Config-driven (reads parquet, writes hc_plot.parquet + hc_table.parquet)
# config keys: inputs.data_file, outputs,
#              jpm_params: {flag_value, slc}
#              jpm_options: {ua, ur, integration_mode, uncertainty_mode, tide_mode, ...}
jpm.run_jpm(config)

# Pure compute
input_data = jpm.InputData(
    data=arr,            # N×4: [timestamp, response, skew_tides, DSW]
    flag_value=[],
    slc=0.0,
)
opts = jpm.Options(
    ua=0.37, ur=0.58,
    integration_mode="ITCS",     # or "ATCS"; accepts int, string, or enum
    uncertainty_mode="combined",  # "absolute", "relative", or "combined"
    tide_mode="none",             # "none", "combined", or "preprocess"
    percentiles=[16, 84],
    use_aep=False,
    return_table=True,
)
results = jpm.compute(input_data, opts)
# returns: [("plot", array (n_plt, 1+n_prc)), ("table", array (n_tbl, 1+n_prc))]
```

### PST Hazard Curves

```python
from stormsim.hazard_curves import pst

# Config-driven (reads parquet, writes hc_plot.parquet, hc_emp.parquet,
#               gpd_params.parquet, mrl_selection.json, mrl_summary.parquet)
# config keys: inputs.data_file, outputs,
#              pst_params: {flag_value, n_years, slc, data_type, gpr_mdl}
#              pst_options: {gpd_criterion, percentiles, apply_gpd, bootstrap_sims, use_aep}
pst.run_pst(config)

# Pure compute — data is N×3 array: [timestamp, response_no_tides, response_with_tides]
response = pst.ResponseData(
    data=arr,
    data_type="POT",    # "POT" or "Timeseries"
    n_years=75.0,       # POT: supply explicitly; Timeseries: inferred from timestamps
    flag_value=[],
    slc=0.0,
)
opts = pst.PSTOptions(
    gpd_criterion=1,    # 1=sample-intensity (λ), 2=min-WMSE
    percentiles=[16, 84],
    apply_gpd=False,
    bootstrap_sims=100,
    use_aep=False,
)
hc_output, mrl_output = pst.compute(response, opts)
```

### Stage-Volume

```python
from stormsim.stage_volume import run_stage_volume, StageVolumeCalculator, StageVolumeConfig

# Config-driven (reads DEM + model area GeoPackage, writes stage_volume.parquet)
run_stage_volume(config)

# Pure compute
cfg = StageVolumeConfig(stage_units="feet", dem_vertical_units="meters")
calc = StageVolumeCalculator(dem_data, nodata, cell_area_m2, cfg)
pairs = calc.get_relationship(start=0.0, stop=10.0, n=100)
# returns list of {"stage": float, "volume": float}
# set volume_to_stage=True to invert (target volumes → stages)
```

### StorageContext

`StorageContext` resolves local vs. S3 paths transparently. In Lambda, IAM role credentials are used automatically — never pass `access_key`/`secret_key` explicitly:

```python
from stormsim.utilities.storage import StorageContext

ctx = StorageContext(config, is_lambda=True)
input_path = ctx.get_input_path("rel_prob_file")   # resolves to s3:// or local
output_path = ctx.get_output_path()
```

---

## Releasing New Versions

1. Update `version` in `pyproject.toml`.
2. Commit and push.
3. Create and push a version tag:
   ```bash
   git tag v0.1.x
   git push origin v0.1.x
   ```
4. The **Release** workflow automatically builds the package and creates a GitHub Release.

---

## Project Structure

```
src/stormsim/
├── lcgen/                  # Lifecycle generation
├── hydrograph_manipulator/ # Surge/wave time-series construction
├── eurotop/                # Wave runup and overtopping (EurOtop 2018)
├── hazard_curves/
│   ├── jpm/                # Joint Probability Method
│   └── pst/                # Peaks-over-Threshold
├── stage_volume/           # DEM-based stage-volume relationships
├── sea_level_rise/         # SLR scenario generation
├── noaa_py/                # NOAA tidal gauge data access
└── utilities/              # StorageContext, CHS HDF5 utilities
implementation-scripts/     # CLI drivers for each pipeline stage
config-files/               # Shared JSON configuration templates
tests/                      # pytest test suite
```
