import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from roi.acquisition_state import AcquisitionState
from roi.configuration import ROIConfiguration
from roi.interfaces import ROIRepository
from roi.persistence.exceptions import (
    PersistenceError,
    FileNotFoundError,
    CorruptedFileError,
    ValidationError,
)
from roi.persistence.migration.migration_manager import migrate
from roi.persistence.project import CameraReference, Project
from roi.persistence.schema import (
    extract_extra_fields,
    validate_schema_version,
    validate_required_fields,
    validate_roi_ids,
)
from roi.persistence.serializer import (
    state_file_to_dict,
    export_file_content,
    project_to_dict,
    dict_to_project,
)

logger = logging.getLogger(__name__)


class JSONROIRepository(ROIRepository):
    def __init__(self, base_path: str = "config/roi") -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

        self._loaded: dict[str, list[ROIConfiguration]] = {}
        self._roi_index: dict[str, str] = {}
        self._extra_fields: dict[str, dict] = {}

    def load_all(self, acquisition_state: AcquisitionState) -> list[ROIConfiguration]:
        key = self._cache_key(acquisition_state)
        cached = self._loaded.get(key)
        if cached is not None:
            return list(cached)

        filepath = self._file_path(acquisition_state)
        if not filepath.exists():
            self._loaded[key] = []
            return []

        data = self._read_file(filepath)
        state, rois = self._deserialize_state_file(data)
        if state != acquisition_state:
            raise ValidationError(
                f"Acquisition state mismatch: file has {state}, "
                f"requested {acquisition_state}"
            )

        self._loaded[key] = rois
        for r in rois:
            self._roi_index[r.roi_id] = key

        return list(rois)

    def save(self, configuration: ROIConfiguration) -> None:
        key = self._cache_key(configuration.acquisition_state)
        existing = list(self._loaded.get(key, []))

        replaced = False
        for i, r in enumerate(existing):
            if r.roi_id == configuration.roi_id:
                existing[i] = configuration
                replaced = True
                break

        if not replaced:
            existing.append(configuration)

        self._save_all_for_state(configuration.acquisition_state, existing)

        self._loaded[key] = existing
        self._roi_index[configuration.roi_id] = key

    def save_all(self, configurations: list[ROIConfiguration]) -> None:
        if not configurations:
            return
        state = configurations[0].acquisition_state
        key = self._cache_key(state)

        for cfg in configurations:
            if cfg.acquisition_state != state:
                raise ValidationError(
                    "Cannot save_all: all configurations must share the same "
                    "acquisition_state"
                )

        self._save_all_for_state(state, configurations)
        self._loaded[key] = list(configurations)
        for cfg in configurations:
            self._roi_index[cfg.roi_id] = key

    def delete(self, roi_id: str) -> bool:
        cache_key = self._roi_index.get(roi_id)
        if cache_key is None:
            cache_key = self._find_key_by_roi_id(roi_id)

        if cache_key is None:
            return False

        configs = self._loaded.get(cache_key, [])
        filtered = [c for c in configs if c.roi_id != roi_id]

        if len(filtered) == len(configs):
            return False

        if cache_key in self._loaded:
            for cfg in configs:
                if cfg.roi_id == roi_id:
                    self._save_all_for_state(cfg.acquisition_state, filtered)
                    break

        self._loaded[cache_key] = filtered
        self._roi_index.pop(roi_id, None)
        return True

    def exists(self, roi_id: str) -> bool:
        if roi_id in self._roi_index:
            return True
        return self._find_key_by_roi_id(roi_id) is not None

    def export_state(
        self,
        acquisition_state: AcquisitionState,
        target_path: str,
    ) -> None:
        rois = self.load_all(acquisition_state)
        content = export_file_content(acquisition_state, rois)
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def import_state(self, source_path: str) -> AcquisitionState:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Import file not found: {source_path}")

        data = self._read_file(source)
        state, rois = self._deserialize_state_file(data)

        self.save_all(rois)
        return state

    def _save_all_for_state(
        self,
        state: AcquisitionState,
        rois: list[ROIConfiguration],
    ) -> None:
        filepath = self._file_path(state)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        data = state_file_to_dict(state, rois)

        path_str = str(filepath)
        extra = self._extra_fields.pop(path_str, None)
        if extra is None and filepath.exists():
            extra = self._read_extra_fields(filepath)
        if extra:
            data.update(extra)

        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

        self._write_file_atomically(filepath, content)

    def _read_extra_fields(self, path: Path) -> dict:
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                return extract_extra_fields(data)
        except Exception:
            pass
        return {}

    def _file_path(self, state: AcquisitionState) -> Path:
        return (
            self._base
            / state.camera_id
            / f"acquisition_state_{state.position_id}.json"
        )

    def _cache_key(self, state: AcquisitionState) -> str:
        return f"{state.camera_id}/{state.position_id}"

    def _read_file(self, path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(f"ROI file not found: {path}")

        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise CorruptedFileError(
                f"Invalid JSON in {path}: {e}"
            ) from e
        except OSError as e:
            raise PersistenceError(f"Failed to read {path}: {e}") from e

        if not isinstance(data, dict):
            raise CorruptedFileError(
                f"Expected a JSON object at root, got {type(data).__name__}"
            )

        data = migrate(data)

        validate_schema_version(data)
        validate_required_fields(data)
        validate_roi_ids(data)

        extra = extract_extra_fields(data)
        if extra:
            path_str = str(path)
            self._extra_fields[path_str] = extra

        return data

    def _deserialize_state_file(
        self,
        data: dict,
    ) -> tuple[AcquisitionState, list[ROIConfiguration]]:
        from roi.persistence.serializer import dict_to_state_file
        return dict_to_state_file(data)

    def _write_file_atomically(self, path: Path, content: str) -> None:
        self._backup_file(path)

        fd, tmp_path_str = tempfile.mkstemp(
            suffix=".tmp",
            prefix=f".{path.stem}_",
            dir=path.parent,
        )
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            fd = None

            shutil.move(tmp_path_str, str(path))
        except OSError as e:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(tmp_path_str)
            except OSError:
                pass
            raise PersistenceError(
                f"Atomic write failed for {path}: {e}"
            ) from e

    def _backup_file(self, path: Path) -> None:
        if not path.exists():
            return

        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(str(path), str(backup_path))
        except OSError as e:
            raise PersistenceError(
                f"Backup failed for {path}: {e}"
            ) from e

    def _find_key_by_roi_id(self, roi_id: str) -> str | None:
        for camera_dir in self._base.iterdir():
            if not camera_dir.is_dir():
                continue
            for filepath in camera_dir.glob("acquisition_state_*.json"):
                try:
                    data = self._read_file(filepath)
                    state, rois = self._deserialize_state_file(data)
                    key = self._cache_key(state)
                    self._loaded[key] = rois
                    for r in rois:
                        self._roi_index[r.roi_id] = key
                    if any(r.roi_id == roi_id for r in rois):
                        return key
                except Exception:
                    continue
        return None

    def clear_cache(self) -> None:
        self._loaded.clear()
        self._roi_index.clear()
        self._extra_fields.clear()


class ProjectRepository:
    def __init__(self, base_path: str = "config/roi") -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    def load(self) -> Project | None:
        project_file = self._base / "project.json"
        if not project_file.exists():
            return None

        data = self._read_json(project_file)
        validate_schema_version(data)
        return dict_to_project(data.get("project", {}))

    def save(self, project: Project) -> None:
        project_file = self._base / "project.json"
        content = {
            "schema_version": 1,
            "project": project_to_dict(project),
        }
        raw = json.dumps(content, indent=2, ensure_ascii=False) + "\n"
        self._write_atomic(project_file, raw)

    def list_cameras(self) -> list[str]:
        if not self._base.exists():
            return []
        return sorted(
            d.name for d in self._base.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def add_camera(self, camera: CameraReference) -> None:
        project = self.load() or Project(name="Default Project")
        for existing in project.cameras:
            if existing.camera_id == camera.camera_id:
                existing.name = camera.name
                existing.model = camera.model
                existing.metadata.update(camera.metadata)
                break
        else:
            project.cameras.append(camera)
        self.save(project)

    def remove_camera(self, camera_id: str) -> bool:
        project = self.load()
        if project is None:
            return False
        before = len(project.cameras)
        project.cameras = [c for c in project.cameras if c.camera_id != camera_id]
        if len(project.cameras) == before:
            return False
        self.save(project)
        return True

    def remove_camera_data(self, camera_id: str) -> bool:
        camera_dir = self._base / camera_id
        if not camera_dir.exists():
            return False
        shutil.rmtree(str(camera_dir))
        return True

    def project_exists(self) -> bool:
        return (self._base / "project.json").exists()

    def _read_json(self, path: Path) -> dict:
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise CorruptedFileError(
                f"Invalid JSON in {path}: {e}"
            ) from e
        except OSError as e:
            raise PersistenceError(f"Failed to read {path}: {e}") from e

        if not isinstance(data, dict):
            raise CorruptedFileError(
                f"Expected a JSON object at root, got {type(data).__name__}"
            )
        return data

    def _write_atomic(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path_str = tempfile.mkstemp(
            suffix=".tmp",
            prefix=f".{path.stem}_",
            dir=path.parent,
        )
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            fd = None
            shutil.move(tmp_path_str, str(path))
        except OSError as e:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(tmp_path_str)
            except OSError:
                pass
            raise PersistenceError(
                f"Atomic write failed for {path}: {e}"
            ) from e
