"""
mouse.py

Mouse handling for multiple OpenCV windows.

Author : Shubham
"""

_mouse_positions = {}


def create_callback(window_name):

    def callback(event, x, y, flags, param):

        _mouse_positions[window_name] = (x, y)

    return callback


def get_mouse(window_name):

    return _mouse_positions.get(window_name, (0, 0))