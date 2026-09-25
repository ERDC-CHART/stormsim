import json
import os

from stormsim.eurotop import simulation


class _StorageContext:
    def __init__(self, paths):
        self.paths = paths

    def get_input_path(self, key):
        return self.paths[key]

    def get_output_path(self):
        return self.paths["output"]


def _config(tmp_path):
    lc_data = tmp_path / "lifecycles"
    lc_data.mkdir()
    pse_geometry = tmp_path / "geometry.json"
    pse_geometry.write_text(json.dumps([]))
    stage_volume = tmp_path / "stage_volume.csv"
    stage_volume.write_text("stage,volume\n0,0\n")

    return {
        "lc_data": str(lc_data),
        "pse_geometry": str(pse_geometry),
        "stage_vol_file": str(stage_volume),
        "output": str(tmp_path / "output"),
    }


def test_run_eurotop_reports_aggregation_failure_as_partial_success(tmp_path, monkeypatch):
    paths = _config(tmp_path)
    monkeypatch.setattr(simulation, "StorageContext", lambda *_args, **_kwargs: _StorageContext(paths))

    def fail_aggregation(_outpath, _stage_volume=None, labels=None):
        raise OSError("S3 write denied")

    monkeypatch.setattr(simulation, "aggregate_q", fail_aggregation)

    result = simulation.run_eurotop({})

    # not "success": the transect outputs survive, but a caller that reads
    # only status must not record this as a finished run
    assert result == {
        "status": "partial",
        "output": paths["output"],
        "aggregated": 0,
        "aggregation_error": "S3 write denied",
    }


def test_run_eurotop_reports_aggregation_results(tmp_path, monkeypatch):
    paths = _config(tmp_path)
    monkeypatch.setattr(simulation, "StorageContext", lambda *_args, **_kwargs: _StorageContext(paths))
    seen = {}

    def record_aggregation(_outpath, stage_volume=None, labels=None):
        seen["stage_volume"] = stage_volume
        return {
            "pairs_written": 2,
            "output_paths": ["aggregate_responses/q_aggregate_loc_1_lc_2.parquet"],
        }

    monkeypatch.setattr(simulation, "aggregate_q", record_aggregation)

    result = simulation.run_eurotop({})

    # the stage-volume table has to reach aggregation, or the aggregate cannot
    # carry the stage column consequence modelling reads
    assert seen["stage_volume"] is not None

    assert result == {
        "status": "success",
        "output": paths["output"],
        "aggregated": 2,
        "pairs_written": 2,
        "output_paths": ["aggregate_responses/q_aggregate_loc_1_lc_2.parquet"],
    }


def test_run_eurotop_gives_each_pse_its_own_folder(tmp_path, monkeypatch):
    paths = _config(tmp_path)
    (tmp_path / "lifecycles" / "lc.parquet").write_bytes(b"")
    pses = [
        {"id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "name": "Sea Wall 1"},
        {"name": "Sea Wall 1"},
        {"name": "Sea-Wall 1"},
        {"name": "***"},
    ]
    (tmp_path / "geometry.json").write_text(json.dumps(pses))
    monkeypatch.setattr(simulation, "StorageContext", lambda *_args, **_kwargs: _StorageContext(paths))
    folders = []
    monkeypatch.setattr(
        simulation, "process_lc_file",
        lambda _lc, _config, _pse, _sv, outfol: folders.append(os.path.basename(outfol)),
    )
    seen_labels = {}

    def record_labels(_outpath, _stage_volume=None, labels=None):
        seen_labels.update(labels or {})
        return {"pairs_written": 0, "output_paths": []}

    monkeypatch.setattr(simulation, "aggregate_q", record_labels)

    simulation.run_eurotop({})

    # the id when the API sends one; otherwise names that sanitize alike, or
    # to nothing, must still land in distinct, non-empty folders
    assert folders == ["3fa85f64-5717-4562-b3fc-2c963f66afa6", "01_Sea_Wall_1", "02_Sea_Wall_1", "03"]
    # aggregation learns which name each id folder stands for
    assert seen_labels == {"3fa85f64-5717-4562-b3fc-2c963f66afa6": "Sea Wall 1"}
