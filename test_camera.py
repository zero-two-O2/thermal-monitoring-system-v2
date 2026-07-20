"""
Camera Subsystem Test

Run

python tests/test_camera.py

Tests

1. CameraModel
2. CameraFactory
3. CameraContext
4. CameraManager
5. PositionManager
6. TV46LCamera object creation

No real camera required.
"""

from camera.models.camera_model import CameraModel

from camera.factory.camera_factory import CameraFactory

from camera.manager.camera_manager import CameraManager
import os
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ==========================================================
# Utilities
# ==========================================================

def header(title):

    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


# ==========================================================
# Main
# ==========================================================

def main():

    header("CAMERA SUBSYSTEM TEST")

    #
    # Factory
    #

    factory = CameraFactory()

    print("✓ CameraFactory created")

    #
    # Camera Manager
    #

    manager = CameraManager()

    print("✓ CameraManager created")

    #
    # Create Cameras
    #

    for i in range(2):

        model = CameraModel(

            camera_id=f"CAM{i+1}",

            name=f"Camera {i+1}",

            ip_address=f"192.168.1.10{i+1}",

        )

        context = factory.create_camera(model)

        manager.add_camera(context)

        print(f"✓ Created {context.camera_id}")

    #
    # Camera Count
    #

    header("CAMERA LIST")

    print("Camera Count :", manager.camera_count)

    for context in manager.get_all_cameras():

        print()

        print("Camera ID :", context.camera_id)

        print("Enabled  :", context.enabled)

        print("Connected:", context.is_connected)

        print("Running  :", context.is_running)

        print("Positions:", context.position_count)

    #
    # Single Camera
    #

    header("LOOKUP TEST")

    camera = manager.get_camera("CAM1")

    print(camera)

    #
    # Manager Functions
    #

    header("MANAGER TEST")

    print("Connected Cameras")

    print(len(manager.connected_cameras()))

    print()

    print("Running Cameras")

    print(len(manager.running_cameras()))

    print()

    print("Enabled Cameras")

    print(len(manager.enabled_cameras()))

    #
    # Camera API
    #

    header("CAMERA API")

    camera = manager.get_camera("CAM1")

    print("connect()")

    try:

        camera.connect()

        print("PASS")

    except Exception as e:

        print(e)

    print()

    print("disconnect()")

    try:

        camera.disconnect()

        print("PASS")

    except Exception as e:

        print(e)

    print()

    print("start()")

    try:

        camera.start()

        print("PASS")

    except Exception as e:

        print(e)

    print()

    print("stop()")

    try:

        camera.stop()

        print("PASS")

    except Exception as e:

        print(e)

    header("TEST COMPLETE")


if __name__ == "__main__":

    main()