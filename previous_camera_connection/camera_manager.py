"""
camera_manager.py

Discovers all GigE Vision cameras connected to the PC.

Author : Shubham
"""

import halcon as ha

from models import CameraInfo


class CameraManager:

    def __init__(self):

        self.cameras = []

    # ----------------------------------------------------------
    # Scan for cameras
    # ----------------------------------------------------------

    def scan(self):

        self.cameras.clear()

        info, boards = ha.info_framegrabber(
            "GigEVision2",
            "info_boards"
        )

        #
        # HALCON returns one long string for each device.
        #

        for board in boards:

            camera = self.parse_board(board)

            if camera is not None:

                self.cameras.append(camera)

        return self.cameras

    # ----------------------------------------------------------
    # Parse HALCON info string
    # ----------------------------------------------------------

    def parse_board(self, board_string):

        #
        # Example:
        #
        # device:xxxx |
        # unique_name:xxxx |
        # vendor:Fluke |
        # model:TV46L |
        #

        fields = {}

        for item in board_string.split("|"):

            item = item.strip()

            if ":" not in item:

                continue

            key, value = item.split(":", 1)

            fields[key.strip()] = value.strip()

        return CameraInfo(

            device=fields.get("device", ""),

            serial=fields.get("device_sn", ""),

            model=fields.get("model", ""),

            vendor=fields.get("vendor", ""),

            ip=fields.get("device_ip", ""),

            interface=fields.get("interface", ""),

            status=fields.get("status", "")
        )

    # ----------------------------------------------------------
    # Number of cameras
    # ----------------------------------------------------------

    def count(self):

        return len(self.cameras)

    # ----------------------------------------------------------
    # Get one camera
    # ----------------------------------------------------------

    def get(self, index):

        return self.cameras[index]

    # ----------------------------------------------------------
    # Find camera by serial number
    # ----------------------------------------------------------

    def find_by_serial(self, serial):

        for camera in self.cameras:

            if camera.serial == serial:

                return camera

        return None

    # ----------------------------------------------------------
    # Print camera list
    # ----------------------------------------------------------

    def print_summary(self):

        print()

        print("=" * 70)
        print("Detected Cameras")
        print("=" * 70)

        if not self.cameras:

            print("No cameras found.")
            return

        for i, camera in enumerate(self.cameras):

            print(f"[{i}]")

            print(f"Model      : {camera.model}")
            print(f"Serial     : {camera.serial}")
            print(f"Vendor     : {camera.vendor}")
            print(f"IP Address : {camera.ip}")
            print(f"Status     : {camera.status}")
            print()