@dataclass(slots=True)
class ThermalImage:
    image: np.ndarray
    width: int
    height: int


@dataclass(slots=True)
class VisibleImage:
    image: np.ndarray
    width: int
    height: int


@dataclass(slots=True)
class TemperatureMatrix:
    data: np.ndarray