"""
check_environment.py

Verifies the development environment for the Thermal Monitoring System.

Checks:
    - Interpreter (venv vs. global)
    - Required importable packages
    - Installed versions

Usage:
    python tools/check_environment.py

Exit code 0 means all checks passed.
Exit code 1 means at least one check failed.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import sys
import types
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModuleCheck:
    """Describes one importable module and how to read its version."""

    name: str
    version_attr: str | None = None
    version_attr_chain: tuple[str, str] | None = None


CHECKS: tuple[ModuleCheck, ...] = (
    ModuleCheck("halcon", version_attr_chain=("halcon", "__version__")),
    ModuleCheck("numpy", version_attr="__version__"),
    ModuleCheck("cv2", version_attr="__version__"),
    ModuleCheck("PyQt5", version_attr_chain=("PyQt5.QtCore", "PYQT_VERSION_STR")),
    ModuleCheck("PyQt6", version_attr_chain=("PyQt6.QtCore", "PYQT_VERSION_STR")),
    ModuleCheck("debugpy", version_attr="__version__"),
    ModuleCheck("pytest", version_attr="__version__"),
    ModuleCheck("ruff", version_attr="__version__"),
)

# Distributions whose version is read from package metadata instead of the module.
METADATA_VERSION: tuple[str, ...] = ("pip", "mvtec-halcon", "ruff")

# Modules whose reported version falls back to distribution metadata.
METADATA_FALLBACK: dict[str, str] = {"halcon": "mvtec-halcon", "ruff": "ruff"}


def read_version(module: types.ModuleType, check: ModuleCheck) -> str:
    """Return the module version string, or 'unknown'."""
    target = module
    if check.version_attr_chain is not None:
        target = importlib.import_module(check.version_attr_chain[0])
        version = getattr(target, check.version_attr_chain[1], None)
    elif check.version_attr is not None:
        version = getattr(target, check.version_attr, None)
    else:
        version = None
    if version is not None:
        return str(version)
    return read_dist_version(METADATA_FALLBACK.get(check.name, check.name))


def check_module(check: ModuleCheck) -> tuple[bool, str]:
    """Import the module and return (ok, version)."""
    try:
        module = importlib.import_module(check.name)
    except Exception as exc:
        return False, f"IMPORT FAILED: {exc}"
    return True, read_version(module, check)


def read_dist_version(dist_name: str) -> str:
    """Return the installed distribution version, or 'not installed'."""
    try:
        return importlib.metadata.version(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def read_pyvenv_cfg() -> str:
    """Return whether the venv includes system site packages."""
    try:
        with open(sys.prefix + "/pyvenv.cfg", encoding="utf-8") as cfg:
            for line in cfg:
                if line.strip().startswith("include-system-site-packages"):
                    return line.strip().split("=", 1)[1].strip()
    except OSError:
        return "unknown"
    return "unknown"


def main() -> int:
    """Run all checks and print the report."""
    print("Thermal Monitoring System - Environment Check")
    print("=" * 60)
    print(f"Interpreter : {sys.executable}")
    print(f"Python      : {sys.version.split()[0]} ({sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})")
    print(f"Architecture: {sys.maxsize > 2**32 and '64-bit' or '32-bit'}")
    print(f"Venv        : {sys.prefix}")
    print(f"System pkgs : {read_pyvenv_cfg()}")
    print("-" * 60)

    failed = False
    for check in CHECKS:
        ok, detail = check_module(check)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {check.name:<8} {detail}")
        failed = failed or not ok

    for dist in METADATA_VERSION:
        print(f"[----] {dist:<8} {read_dist_version(dist)}")

    print("-" * 60)
    print("RESULT:", "ALL CHECKS PASSED" if not failed else "AT LEAST ONE CHECK FAILED")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
