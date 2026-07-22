from calibration_loader import CalibrationLoader


loader = CalibrationLoader(
    "../Data/calibration/calibration_blob.txt"
)

blob = loader.load()

loader.print_summary(blob)