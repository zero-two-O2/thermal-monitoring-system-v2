"""
Backend Integration Test

Run:

python tests/test_backend.py

This test verifies that all backend modules are correctly
connected and can be instantiated.
"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from camera.models.camera_model import CameraModel
from camera.models.position_model import PositionModel
from camera.manager.position_manager import PositionManager
from camera.manager.camera_manager import CameraManager
from camera.factory.camera_factory import CameraFactory
from calibration.calibration_manager import CalibrationManager
from processing.pipeline.processing_pipeline import ProcessingPipeline
from processing.roi_processor import ROIProcessor
from processing.alarm_processor import AlarmProcessor


def print_header(title: str):

    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def test_camera_model():

    print_header("Camera Model")

    camera = CameraModel(
        camera_id="CAM001",
        camera_name="Test Camera",
        ip_address="192.168.1.100",
    )

    print(camera)


def test_position_model():

    print_header("Position Model")

    position = PositionModel(
        position_id="POS001",
        camera_id="CAM001",
        camera_name="Position 1",
        sequence=1,
    )

    print(position)


def test_position_manager():

    print_header("Position Manager")

    manager = PositionManager()

    manager.add_position(
        PositionModel(
            position_id="P001",
            camera_id="CAM001",
            camera_name="Position 1",
            sequence=1,
        )
    )

    manager.add_position(
        PositionModel(
            position_id="P002",
            camera_id="CAM001",
            camera_name="Position 2",
            sequence=2,
        )
    )

    print("Position Count:", manager.position_count)

    print("Current:", manager.get_current_position())

    print("Next:", manager.next_position())


def test_processing():

    print_header("Processing")

    calibration = CalibrationManager()

    roi = ROIProcessor()

    alarm = AlarmProcessor()

    pipeline = ProcessingPipeline(
        calibration_manager=calibration,
        roi_processor=roi,
        alarm_processor=alarm,
    )

    print(pipeline)


def test_factory():

    print_header("Camera Factory")

    factory = CameraFactory()

    model = CameraModel(
        camera_id="CAM001",
        camera_name="Factory Camera",
        ip_address="192.168.1.100",
    )

    context = factory.create_camera(model)

    print(context)

    print("Camera ID:", context.camera_id)

    print("Positions:", context.position_count)


def test_camera_manager():

    print_header("Camera Manager")

    factory = CameraFactory()

    manager = CameraManager()

    for i in range(2):

        model = CameraModel(
            camera_id=f"CAM{i+1}",
            camera_name=f"Camera {i+1}",
            ip_address=f"192.168.1.10{i}",
        )

        manager.add_camera(
            factory.create_camera(model)
        )

    print("Camera Count:", manager.camera_count)

    print("All Cameras")

    for context in manager.get_all_cameras():

        print(context.camera_id)


def main():

    print("\n")
    print("=" * 60)
    print("THERMAL MONITORING SYSTEM")
    print("BACKEND INTEGRATION TEST")
    print("=" * 60)

    test_camera_model()

    test_position_model()

    test_position_manager()

    test_processing()

    test_factory()

    test_camera_manager()

    print("\n")
    print("=" * 60)
    print("BACKEND TEST COMPLETED")
    print("=" * 60)


if __name__ == "__main__":

    main()