from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from roi.acquisition_state import AcquisitionState
from roi.alarm_settings import ROIAlarmCondition, ROIAlarmSettings
from roi.configuration import ROIConfiguration
from roi.geometry import (
    Rectangle1ROI,
    Rectangle2ROI,
    CircleROI,
    EllipseROI,
    PolygonROI,
)
from roi.recording_settings import ROIRecordingSettings
from roi.style import ROIStyle
from roi.persistence import (
    JSONROIRepository,
    ProjectRepository,
    configuration_to_dict,
    dict_to_configuration,
    state_file_to_dict,
    dict_to_state_file,
    geometry_to_dict,
    dict_to_geometry,
    acquisition_state_to_dict,
    dict_to_acquisition_state,
    export_file_content,
    parse_file_content,
    project_to_dict,
    dict_to_project,
    migrate,
    CURRENT_SCHEMA_VERSION,
    SchemaVersionError,
    ValidationError,
    MissingFieldError,
    DuplicateROIError,
    FileNotFoundError,
    CorruptedFileError,
)
from roi.persistence.project import CameraReference, Project
from roi.persistence.schema import validate_roi_values


# ==============================================================
# Test data
# ==============================================================

_STATE = AcquisitionState(camera_id="cam_1", pan=0.0, tilt=0.0, zoom=0.0, focus=0.0)

_ALL_GEOMETRIES = [
    Rectangle1ROI(row1=100.0, col1=50.0, row2=200.0, col2=300.0),
    Rectangle2ROI(row=150.0, col=200.0, phi=0.0, length1=50.0, length2=30.0),
    CircleROI(row=100.0, col=100.0, radius=25.0),
    EllipseROI(row=100.0, col=100.0, phi=0.0, radius1=40.0, radius2=20.0),
    PolygonROI(points=((50.0, 50.0), (150.0, 50.0), (150.0, 150.0), (50.0, 150.0))),
]


def _make_config(
    roi_id: str = "test_001",
    name: str = "Test ROI",
    geometry: Rectangle1ROI | Rectangle2ROI | CircleROI | EllipseROI | PolygonROI = Rectangle1ROI(10.0, 10.0, 100.0, 100.0),
    metadata: dict | None = None,
    state: AcquisitionState | None = None,
) -> ROIConfiguration:
    return ROIConfiguration(
        roi_id=roi_id,
        name=name,
        acquisition_state=state if state is not None else _STATE,
        geometry=geometry,
        style=ROIStyle(
            color="#FF0000", selected_color="#00FF00", alarm_color="#0000FF",
            line_width=3, label_visible=False, label_size=12,
        ),
        alarm=ROIAlarmSettings(
            enabled=True,
            condition=ROIAlarmCondition.HIGH,
            value=85.0,
            hysteresis=2.0,
            delay_ms=500,
        ),
        recording=ROIRecordingSettings(
            enabled=True,
            duration_seconds=30,
            pre_trigger_seconds=5,
            post_trigger_seconds=10,
            save_images=True,
            save_video=False,
        ),
        enabled=True,
        visible=False,
        description="Test ROI description",
        metadata=metadata if metadata is not None else {"created_by": "test", "version": 1},
    )


# ==============================================================
# Tests: AcquisitionState serialization
# ==============================================================

class TestAcquisitionStateSerialization:
    def test_round_trip(self):
        state = AcquisitionState(camera_id="cam_2", pan=45.0, tilt=10.0, zoom=3.0, focus=500.0)
        d = acquisition_state_to_dict(state)
        restored = dict_to_acquisition_state(d)
        assert restored == state

    def test_defaults(self):
        state = AcquisitionState(camera_id="cam_1")
        d = acquisition_state_to_dict(state)
        assert d["pan"] == 0.0
        assert d["tilt"] == 0.0
        assert d["zoom"] == 0.0
        assert d["focus"] == 0.0


# ==============================================================
# Tests: Geometry serialization (all 5 types)
# ==============================================================

class TestGeometrySerialization:
    @pytest.mark.parametrize("geom", _ALL_GEOMETRIES, ids=lambda g: type(g).__name__)
    def test_round_trip(self, geom):
        d = geometry_to_dict(geom)
        restored = dict_to_geometry(d)
        assert type(restored) is type(geom)
        assert restored == geom

    def test_rectangle1(self):
        g = Rectangle1ROI(row1=0.0, col1=0.0, row2=479.0, col2=639.0)
        d = geometry_to_dict(g)
        assert d == {"type": "rectangle1", "row1": 0.0, "col1": 0.0, "row2": 479.0, "col2": 639.0}
        restored = dict_to_geometry(d)
        assert restored == g

    def test_polygon_points(self):
        g = PolygonROI(points=((10.5, 20.5), (30.5, 40.5), (50.5, 60.5)))
        d = geometry_to_dict(g)
        assert d["type"] == "polygon"
        assert d["points"] == [[10.5, 20.5], [30.5, 40.5], [50.5, 60.5]]
        restored = dict_to_geometry(d)
        assert restored == g

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown geometry type"):
            dict_to_geometry({"type": "unknown"})


# ==============================================================
# Tests: Full ROIConfiguration serialization
# ==============================================================

class TestROIConfigurationSerialization:
    def test_round_trip_all_fields(self):
        cfg = _make_config()
        d = configuration_to_dict(cfg)
        restored = dict_to_configuration(d, _STATE)
        assert restored.roi_id == cfg.roi_id
        assert restored.name == cfg.name
        assert restored.enabled == cfg.enabled
        assert restored.visible == cfg.visible
        assert restored.description == cfg.description
        assert restored.metadata == cfg.metadata
        assert type(restored.geometry) is type(cfg.geometry)
        assert restored.geometry == cfg.geometry
        assert restored.style == cfg.style
        assert restored.alarm == cfg.alarm
        assert restored.recording == cfg.recording
        assert restored.acquisition_state == cfg.acquisition_state

    def test_round_trip_with_acquisition_state(self):
        cfg = _make_config()
        file_data = state_file_to_dict(_STATE, [cfg])
        assert file_data["schema_version"] == 1
        assert file_data["camera_id"] == "cam_1"

        restored_state, restored_rois = dict_to_state_file(file_data)
        assert restored_state == _STATE
        assert len(restored_rois) == 1
        assert restored_rois[0].roi_id == cfg.roi_id
        assert restored_rois[0].geometry == cfg.geometry

    def test_round_trip_all_geometries(self):
        for geom in _ALL_GEOMETRIES:
            cfg = _make_config(roi_id=f"geom_{type(geom).__name__}", geometry=geom)
            d = configuration_to_dict(cfg)
            restored = dict_to_configuration(d, _STATE)
            assert type(restored.geometry) is type(geom)
            assert restored.geometry == geom

    def test_empty_roi_list(self):
        file_data = state_file_to_dict(_STATE, [])
        assert file_data["rois"] == []
        state, rois = dict_to_state_file(file_data)
        assert rois == []

    def test_metadata_preserved(self):
        cfg = _make_config(metadata={"key": "value", "nested": {"a": 1}})
        d = configuration_to_dict(cfg)
        restored = dict_to_configuration(d, _STATE)
        assert restored.metadata == {"key": "value", "nested": {"a": 1}}

    def test_export_parse_round_trip(self):
        rois = [_make_config()]
        content = export_file_content(_STATE, rois)
        state, restored_rois = parse_file_content(content)
        assert state == _STATE
        assert len(restored_rois) == 1
        assert restored_rois[0].roi_id == rois[0].roi_id

    def test_json_is_deterministic(self):
        rois = [_make_config()]
        c1 = export_file_content(_STATE, rois)
        c2 = export_file_content(_STATE, rois)
        j1 = json.loads(c1)
        j2 = json.loads(c2)
        assert j1 == j2


# ==============================================================
# Tests: Schema validation
# ==============================================================

class TestSchemaValidation:
    def test_valid_file_passes(self):
        data = state_file_to_dict(_STATE, [_make_config()])
        from roi.persistence.schema import validate_schema_version, validate_required_fields, validate_roi_ids
        validate_schema_version(data)
        validate_required_fields(data)
        validate_roi_ids(data)

    def test_missing_schema_version(self):
        with pytest.raises(MissingFieldError, match="schema_version"):
            from roi.persistence.schema import validate_schema_version
            validate_schema_version({})

    def test_future_schema_version(self, caplog):
        caplog.set_level("WARNING")
        from roi.persistence.schema import validate_schema_version
        validate_schema_version({"schema_version": 999})
        assert any("newer than supported" in msg for msg in caplog.messages)

    def test_missing_required_fields(self):
        with pytest.raises(MissingFieldError, match="rois"):
            from roi.persistence.schema import validate_required_fields
            validate_required_fields({"schema_version": 1, "camera_id": "x", "acquisition_state": {}})

    def test_duplicate_roi_ids(self):
        data = state_file_to_dict(_STATE, [_make_config("dup"), _make_config("dup")])
        with pytest.raises(DuplicateROIError, match="Duplicate ROI ID"):
            from roi.persistence.schema import validate_roi_ids
            validate_roi_ids(data)


# ==============================================================
# Tests: Migration
# ==============================================================

class TestMigration:
    def test_current_version_passthrough(self):
        data = {"schema_version": CURRENT_SCHEMA_VERSION, "data": "test"}
        result = migrate(data)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION
        assert result["data"] == "test"

    def test_missing_version_becomes_current(self):
        data = {"camera_id": "cam_1"}
        result = migrate(data)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_invalid_version_raises(self):
        with pytest.raises(SchemaVersionError, match="Invalid schema_version"):
            migrate({"schema_version": -1})

    def test_future_version_stays_unchanged(self):
        data = {"schema_version": 999}
        result = migrate(data)
        assert result["schema_version"] == 999


# ==============================================================
# Tests: JSONROIRepository
# ==============================================================

class TestJSONROIRepository:
    @pytest.fixture
    def repo(self, tmp_path: Path) -> JSONROIRepository:
        base = tmp_path / "roi_configs"
        return JSONROIRepository(str(base))

    def test_load_empty_state_returns_empty_list(self, repo):
        rois = repo.load_all(_STATE)
        assert rois == []

    def test_save_and_load_single_roi(self, repo):
        cfg = _make_config()
        repo.save(cfg)
        rois = repo.load_all(_STATE)
        assert len(rois) == 1
        assert rois[0].roi_id == cfg.roi_id
        assert rois[0].geometry == cfg.geometry
        assert rois[0].style == cfg.style
        assert rois[0].alarm == cfg.alarm
        assert rois[0].recording == cfg.recording

    def test_round_trip_all_geometries(self, repo):
        for geom in _ALL_GEOMETRIES:
            cfg = _make_config(roi_id=f"geom_{type(geom).__name__}", geometry=geom)
            repo.save(cfg)

        rois = repo.load_all(_STATE)
        assert len(rois) == len(_ALL_GEOMETRIES)
        for cfg in rois:
            assert cfg.geometry in _ALL_GEOMETRIES

    def test_save_updates_existing(self, repo):
        cfg = _make_config(roi_id="r1", name="Original")
        repo.save(cfg)

        updated = _make_config(roi_id="r1", name="Updated")
        repo.save(updated)

        rois = repo.load_all(_STATE)
        assert len(rois) == 1
        assert rois[0].name == "Updated"

    def test_delete_existing_roi(self, repo):
        repo.save(_make_config(roi_id="r1"))
        repo.save(_make_config(roi_id="r2"))

        assert repo.delete("r1") is True
        rois = repo.load_all(_STATE)
        assert len(rois) == 1
        assert rois[0].roi_id == "r2"

    def test_delete_nonexistent_returns_false(self, repo):
        assert repo.delete("nonexistent") is False

    def test_exists(self, repo):
        assert repo.exists("r1") is False
        repo.save(_make_config(roi_id="r1"))
        assert repo.exists("r1") is True

    def test_load_all_is_idempotent(self, repo):
        repo.save(_make_config(roi_id="r1"))
        r1 = repo.load_all(_STATE)
        r2 = repo.load_all(_STATE)
        assert r1 == r2

    def test_atomic_save_does_not_corrupt(self, repo):
        cfg = _make_config(roi_id="r1")
        repo.save(cfg)

        filepath = repo._file_path(_STATE)
        content = filepath.read_text()
        data = json.loads(content)
        assert len(data["rois"]) == 1

    def test_backup_created_on_save(self, repo):
        cfg = _make_config(roi_id="r1")
        repo.save(cfg)

        cfg2 = _make_config(roi_id="r2", name="Second")
        repo.save(cfg2)

        backup_path = repo._file_path(_STATE).with_suffix(".json.bak")
        assert backup_path.exists()


    def test_export_import_round_trip(self, repo, tmp_path):
        repo.save(_make_config(roi_id="r1"))
        export_path = tmp_path / "exported.json"

        repo.export_state(_STATE, str(export_path))
        assert export_path.exists()

        repo.clear_cache()
        repo2 = JSONROIRepository(str(tmp_path / "imported"))
        imported_state = repo2.import_state(str(export_path))
        assert imported_state == _STATE

        rois = repo2.load_all(_STATE)
        assert len(rois) == 1
        assert rois[0].roi_id == "r1"

    def test_lazy_loading_multiple_cameras(self, repo):
        state1 = AcquisitionState(camera_id="cam_1", pan=0.0)
        state2 = AcquisitionState(camera_id="cam_2", pan=0.0)

        repo.save(_make_config(roi_id="c1_r1", name="Cam1 ROI"))

        cfg_c2_a = _make_config(roi_id="c2_r1", name="Cam2 ROI A", geometry=CircleROI(50, 50, 25), state=state2)
        cfg_c2_b = _make_config(roi_id="c2_r2", name="Cam2 ROI B", state=state2)

        repo2 = JSONROIRepository(str(repo._base))
        repo2.save(cfg_c2_a)
        repo2.save(cfg_c2_b)

        cam1_rois = repo.load_all(state1)
        assert len(cam1_rois) == 1  # only c1_r1

        cam2_rois = repo.load_all(state2)
        assert len(cam2_rois) == 2  # c2_r1 + c2_r2

    def test_save_all_replaces_existing(self, repo):
        repo.save(_make_config(roi_id="r1"))
        new_configs = [
            _make_config(roi_id="r2", name="Replacement A"),
            _make_config(roi_id="r3", name="Replacement B"),
        ]
        repo.save_all(new_configs)

        rois = repo.load_all(_STATE)
        roi_ids = {r.roi_id for r in rois}
        assert roi_ids == {"r2", "r3"}

    def test_delete_reloads_from_disk(self, repo):
        repo.save(_make_config(roi_id="r1"))
        repo.save(_make_config(roi_id="r2"))
        repo.clear_cache()

        assert repo.delete("r1") is True
        rois = repo.load_all(_STATE)
        roi_ids = {r.roi_id for r in rois}
        assert roi_ids == {"r2"}

    def test_large_roi_collection(self, repo):
        count = 500
        for i in range(count):
            cfg = _make_config(roi_id=f"roi_{i:04d}", name=f"ROI {i}")
            repo.save(cfg)

        rois = repo.load_all(_STATE)
        assert len(rois) == count

        repo.clear_cache()
        rois2 = repo.load_all(_STATE)
        assert len(rois2) == count


# ==============================================================
# Tests: Error handling
# ==============================================================

class TestErrorHandling:
    @pytest.fixture
    def repo(self, tmp_path: Path) -> JSONROIRepository:
        return JSONROIRepository(str(tmp_path / "roi_error_tests"))

    def test_missing_file_raises(self, repo):
        with pytest.raises(FileNotFoundError, match="ROI file not found"):
            repo._read_file(Path("nonexistent.json"))

    def test_invalid_json_raises(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json}", encoding="utf-8")
        repo = JSONROIRepository(str(tmp_path))
        with pytest.raises(CorruptedFileError, match="Invalid JSON"):
            repo._read_file(bad_file)

    def test_import_nonexistent_file(self, repo):
        with pytest.raises(FileNotFoundError, match="Import file not found"):
            repo.import_state("nonexistent.json")

    def test_save_all_different_states_raises(self, repo):
        state2 = AcquisitionState(camera_id="cam_2", pan=0.0)
        cfg1 = _make_config(roi_id="r1")
        cfg2 = _make_config(roi_id="r2")
        cfg2.acquisition_state = state2

        with pytest.raises(ValidationError, match="same acquisition_state"):
            repo.save_all([cfg1, cfg2])


class TestProjectSerialization:
    def test_round_trip_minimal(self):
        p = Project(name="Test")
        d = project_to_dict(p)
        restored = dict_to_project(d)
        assert restored.name == "Test"
        assert restored.description == ""
        assert restored.author == ""
        assert restored.cameras == []

    def test_round_trip_full(self):
        from datetime import datetime
        p = Project(
            name="Full Project",
            description="A test project",
            author="Tester",
            application_version="2.0.0",
            created_at=datetime(2024, 6, 15, 10, 30, 0),
            updated_at=datetime(2024, 6, 15, 12, 0, 0),
            cameras=[
                CameraReference(camera_id="cam_1", name="Left Camera", model="TV46L"),
                CameraReference(camera_id="cam_2", name="Right Camera", model="TV46L"),
            ],
            metadata={"key": "value"},
        )
        d = project_to_dict(p)
        restored = dict_to_project(d)
        assert restored.name == "Full Project"
        assert restored.description == "A test project"
        assert restored.author == "Tester"
        assert restored.application_version == "2.0.0"
        assert restored.created_at == datetime(2024, 6, 15, 10, 30, 0)
        assert len(restored.cameras) == 2
        assert restored.cameras[0].camera_id == "cam_1"
        assert restored.cameras[0].name == "Left Camera"
        assert restored.cameras[1].model == "TV46L"
        assert restored.metadata["key"] == "value"

    def test_defaults(self):
        d = project_to_dict(Project(name="X"))
        assert d["application_version"] == "1.0.0"
        assert d["created_at"] == ""
        assert d["updated_at"] == ""

    def test_dict_to_project_missing_fields(self):
        restored = dict_to_project({})
        assert restored.name == ""
        assert restored.cameras == []

    def test_camera_ref_metadata(self):
        cam = CameraReference(camera_id="cam_1", metadata={"ip": "192.168.1.10"})
        d = project_to_dict(Project(name="P", cameras=[cam]))
        restored = dict_to_project(d)
        assert restored.cameras[0].metadata["ip"] == "192.168.1.10"

    def test_serialized_json_is_valid(self):
        import json
        p = Project(name="JSON Test", cameras=[
            CameraReference(camera_id="cam_1"),
        ])
        d = {"schema_version": 1, "project": project_to_dict(p)}
        raw = json.dumps(d, indent=2)
        parsed = json.loads(raw)
        restored = dict_to_project(parsed["project"])
        assert restored.name == "JSON Test"


class TestProjectRepository:
    def test_load_nonexistent(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        assert repo.load() is None

    def test_save_and_load(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        p = Project(name="My Project", author="Me")
        repo.save(p)
        loaded = repo.load()
        assert loaded is not None
        assert loaded.name == "My Project"
        assert loaded.author == "Me"

    def test_save_and_load_with_cameras(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        p = Project(
            name="Multi Cam",
            cameras=[CameraReference(camera_id="cam_1", name="Left")],
        )
        repo.save(p)
        loaded = repo.load()
        assert loaded is not None
        assert len(loaded.cameras) == 1
        assert loaded.cameras[0].camera_id == "cam_1"

    def test_save_updates_existing(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        repo.save(Project(name="v1"))
        repo.save(Project(name="v2"))
        loaded = repo.load()
        assert loaded is not None
        assert loaded.name == "v2"

    def test_list_cameras_empty(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        assert repo.list_cameras() == []

    def test_list_cameras(self, tmp_path):
        (tmp_path / "cam_1").mkdir()
        (tmp_path / "cam_2").mkdir()
        (tmp_path / "ignore.txt").write_text("x")
        repo = ProjectRepository(str(tmp_path))
        cams = repo.list_cameras()
        assert cams == ["cam_1", "cam_2"]

    def test_add_camera_creates_project(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        repo.add_camera(CameraReference(camera_id="cam_1", name="Left"))
        loaded = repo.load()
        assert loaded is not None
        assert len(loaded.cameras) == 1
        assert loaded.cameras[0].camera_id == "cam_1"

    def test_add_camera_updates_existing(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        repo.add_camera(CameraReference(camera_id="cam_1", name="Left"))
        repo.add_camera(CameraReference(camera_id="cam_1", name="Left Updated"))
        loaded = repo.load()
        assert loaded is not None
        assert len(loaded.cameras) == 1
        assert loaded.cameras[0].name == "Left Updated"

    def test_remove_camera(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        repo.add_camera(CameraReference(camera_id="cam_1"))
        repo.add_camera(CameraReference(camera_id="cam_2"))
        result = repo.remove_camera("cam_1")
        assert result is True
        loaded = repo.load()
        assert loaded is not None
        assert [c.camera_id for c in loaded.cameras] == ["cam_2"]

    def test_remove_camera_nonexistent(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        repo.add_camera(CameraReference(camera_id="cam_1"))
        result = repo.remove_camera("cam_nonexistent")
        assert result is False

    def test_remove_camera_no_project(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        result = repo.remove_camera("cam_1")
        assert result is False

    def test_remove_camera_data(self, tmp_path):
        cam_dir = tmp_path / "cam_1"
        cam_dir.mkdir()
        (cam_dir / "test.json").write_text("{}")
        repo = ProjectRepository(str(tmp_path))
        result = repo.remove_camera_data("cam_1")
        assert result is True
        assert not cam_dir.exists()

    def test_project_exists(self, tmp_path):
        repo = ProjectRepository(str(tmp_path))
        assert not repo.project_exists()
        repo.save(Project(name="X"))
        assert repo.project_exists()


class TestForwardCompat:
    def test_extra_fields_preserved_round_trip(self, tmp_path):
        repo = JSONROIRepository(str(tmp_path))
        state = AcquisitionState(camera_id="cam_fwd", pan=0.0, tilt=0.0, zoom=0.0, focus=0.0)
        cfg = _make_config(roi_id="fwd_001", state=state)
        repo.save(cfg)

        filepath = tmp_path / "cam_fwd" / "acquisition_state_0.json"
        data = json.loads(filepath.read_text(encoding="utf-8"))
        data["custom_field"] = "future_value"
        data["unknown_block"] = {"nested": True}
        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

        repo.clear_cache()
        loaded = repo.load_all(state)
        assert len(loaded) == 1
        assert loaded[0].roi_id == "fwd_001"

        repo.save(cfg)
        data2 = json.loads(filepath.read_text(encoding="utf-8"))
        assert data2.get("custom_field") == "future_value"
        assert data2.get("unknown_block") == {"nested": True}

    def test_extra_fields_preserved_on_save_all(self, tmp_path):
        repo = JSONROIRepository(str(tmp_path))
        state = AcquisitionState(camera_id="cam_fwd2", pan=0.0, tilt=0.0, zoom=0.0, focus=0.0)
        cfg = _make_config(roi_id="fwd_002", state=state)
        repo.save(cfg)

        filepath = tmp_path / "cam_fwd2" / "acquisition_state_0.json"
        data = json.loads(filepath.read_text(encoding="utf-8"))
        data["extra"] = "preserved"
        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

        repo.clear_cache()
        repo.save_all([cfg])
        data2 = json.loads(filepath.read_text(encoding="utf-8"))
        assert data2.get("extra") == "preserved"

    def test_extra_fields_preserved_even_with_cache_clear(self, tmp_path):
        repo = JSONROIRepository(str(tmp_path))
        state = AcquisitionState(camera_id="cam_clr", pan=0.0, tilt=0.0, zoom=0.0, focus=0.0)
        cfg = _make_config(roi_id="clr_001", state=state)
        repo.save(cfg)

        filepath = tmp_path / "cam_clr" / "acquisition_state_0.json"
        data = json.loads(filepath.read_text(encoding="utf-8"))
        data["extra"] = "preserved_across_clear"
        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

        repo.clear_cache()
        repo.load_all(state)
        repo.clear_cache()
        repo.save(cfg)
        data2 = json.loads(filepath.read_text(encoding="utf-8"))
        assert data2.get("extra") == "preserved_across_clear"

    def test_future_version_warns_not_raises(self, caplog, tmp_path):
        caplog.set_level("WARNING")
        repo = JSONROIRepository(str(tmp_path))
        state = AcquisitionState(camera_id="cam_fv", pan=0.0, tilt=0.0, zoom=0.0, focus=0.0)
        cfg = _make_config(roi_id="fv_001", state=state)
        repo.save(cfg)

        filepath = tmp_path / "cam_fv" / "acquisition_state_0.json"
        data = json.loads(filepath.read_text(encoding="utf-8"))
        data["schema_version"] = 999
        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

        repo.clear_cache()
        loaded = repo.load_all(state)
        assert len(loaded) == 1
        assert any("newer than supported" in msg for msg in caplog.messages)


class TestValidation:
    def test_valid_roi_passes(self):
        data = {
            "rois": [{
                "roi_id": "r1",
                "name": "Test",
                "geometry": {"type": "rectangle1", "row1": 0, "col1": 0, "row2": 100, "col2": 200},
                "style": {"color": "#FF0000", "selected_color": "#00FF00"},
                "alarm": {"condition": "HIGH"},
            }],
        }
        validate_roi_values(data)

    def test_invalid_color_raises(self):
        data = {
            "rois": [{
                "roi_id": "r1",
                "name": "Test",
                "geometry": {"type": "rectangle1", "row1": 0, "col1": 0, "row2": 100, "col2": 200},
                "style": {"color": "red"},
            }],
        }
        with pytest.raises(ValidationError, match="invalid style color"):
            validate_roi_values(data)

    def test_invalid_alarm_condition_raises(self):
        data = {
            "rois": [{
                "roi_id": "r1",
                "name": "Test",
                "geometry": {"type": "rectangle1", "row1": 0, "col1": 0, "row2": 100, "col2": 200},
                "alarm": {"condition": "INVALID"},
            }],
        }
        with pytest.raises(ValidationError, match="invalid alarm condition"):
            validate_roi_values(data)

    def test_rectangle1_row2_gt_row1(self):
        data = {
            "rois": [{
                "roi_id": "r1",
                "name": "Test",
                "geometry": {"type": "rectangle1", "row1": 100, "col1": 0, "row2": 50, "col2": 200},
            }],
        }
        with pytest.raises(ValidationError, match="must be greater than"):
            validate_roi_values(data)

    def test_circle_radius_positive(self):
        data = {
            "rois": [{
                "roi_id": "r1",
                "name": "Test",
                "geometry": {"type": "circle", "row": 100, "col": 100, "radius": -5},
            }],
        }
        with pytest.raises(ValidationError, match="positive number"):
            validate_roi_values(data)

    def test_no_style_or_alarm_skips_validation(self):
        data = {
            "rois": [{
                "roi_id": "r1",
                "name": "Test",
                "geometry": {"type": "rectangle1", "row1": 0, "col1": 0, "row2": 100, "col2": 200},
            }],
        }
        validate_roi_values(data)

    def test_empty_rois_pass(self):
        validate_roi_values({"rois": []})
