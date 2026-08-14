#!/usr/bin/env python3
"""
setup_environment.py

One-command environment setup for the Thermal Monitoring System v2.

What this script does
---------------------
    Step A - Locate a 64-bit Python 3.10 interpreter (project requirement).
    Step B - Confirm the script is running from the project root.
    Step C - Create a self-contained virtual environment in ``.venv``.
    Step D - Upgrade pip inside the venv.
    Step E - Install runtime dependencies (requirements.txt).
    Step F - Install development dependencies (requirements-dev.txt).
    Step G - Check system dependencies that pip cannot install.
    Step H - Verify the critical libraries import inside the venv.
    Step I - Print a final report and activation instructions.

HALCON is deliberately split into two parts:
    * ``mvtec-halcon`` (pip package) -> installed inside .venv.
    * HALCON runtime + license       -> installed by the MVTec installer.
      This script only detects the runtime; it never installs it.

The script never installs packages into the global Python environment.

Usage
-----
    python setup_environment.py
    python setup_environment.py --recreate --yes
    python setup_environment.py --base-python C:\\Python310\\python.exe

Options
-------
    --recreate      Delete an existing .venv and create a fresh one.
    --yes           Answer yes to every confirmation prompt.
    --base-python   Path to a 64-bit Python 3.10 executable.
    --skip-dev      Do not install requirements-dev.txt.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent

REQUIRED_PYTHON = (3, 10)
VENV_DIR_NAME = ".venv"
VENV_PYTHON_REL = Path("Scripts") / "python.exe"
REQUIREMENTS_FILE = "requirements.txt"
REQUIREMENTS_DEV_FILE = "requirements-dev.txt"

HALCON_PYPI_VERSION = "24113"  # matches mvtec-halcon pinned in requirements.txt
HALCON_RUNTIME_VER = "24.11"   # HALCON runtime major.minor expected by the bindings
HALCON_INSTALL_HINT = (
    "Install the HALCON 24.11 runtime from MVTec "
    "(https://www.mvtec.com/products/halcon) with a valid license, "
    "then run this setup again."
)

# Modules checked during verification. The second element is an optional
# smoke-test expression executed right after the import.
RUNTIME_MODULES: Sequence[tuple[str, Optional[str]]] = [
    ("halcon", "m.gen_empty_obj()"),  # proves the runtime DLLs actually load
    ("numpy", None),
    ("cv2", None),
    ("PyQt5", None),
]
DEV_MODULES: Sequence[tuple[str, Optional[str]]] = [
    ("PyQt6", None),
    ("pytest", None),
    ("psutil", None),
    ("debugpy", None),
    ("pyodbc", None),
]


def say(message: str) -> None:
    """Print a plain status line."""
    print(message)


def step(message: str) -> None:
    """Print a step header."""
    print(f"\n==== {message} ====")


def warn(message: str) -> None:
    """Print a warning line."""
    print(f"[WARN] {message}")


def run(cmd: Sequence[Path | str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run a command with live output; return the CompletedProcess."""
    print("  $ " + " ".join(str(part) for part in cmd))
    return subprocess.run(
        [str(part) for part in cmd],
        cwd=str(cwd) if cwd else None,
    )


def run_capture(cmd: Sequence[Path | str], timeout: int = 60) -> str:
    """Run a command and return its stdout; empty string on any failure."""
    try:
        proc = subprocess.run(
            [str(part) for part in cmd],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        return (proc.stdout or "").strip()
    except (subprocess.SubprocessError, OSError):
        return ""


# ---------------------------------------------------------------------------
# Python interpreter detection
# ---------------------------------------------------------------------------


def python_version_info(exe: Path) -> Optional[tuple[int, int, int]]:
    """Return (major, minor, micro) of the interpreter, or None."""
    out = run_capture(
        [exe, "-c", "import sys; print(sys.version_info.major, sys.version_info.minor, sys.version_info.micro)"]
    )
    parts = out.split()
    if len(parts) != 3:
        return None
    try:
        major, minor, micro = (int(part) for part in parts)
    except ValueError:
        return None
    return major, minor, micro


def is_64_bit(exe: Path) -> bool:
    """Return whether the interpreter is 64-bit (required by HALCON)."""
    return run_capture([exe, "-c", "import struct; print(struct.calcsize('P') * 8)"]) == "64"


def find_base_python(explicit: Optional[Path]) -> Optional[Path]:
    """
    Locate a 64-bit Python 3.10 interpreter.

    Search order: explicit --base-python, the underlying base interpreter
    of the running venv, the running interpreter (if 3.10), the ``py``
    launcher, common install paths, then ``python3.10`` on PATH.
    """
    candidates: list[Path] = []

    if explicit is not None:
        candidates.append(explicit)

    if sys.version_info[:2] == REQUIRED_PYTHON:
        # If we are already inside a venv, prefer its base interpreter so
        # that recreating .venv never deletes the interpreter in use.
        if getattr(sys, "base_prefix", None) and sys.base_prefix != sys.prefix:
            base_exec = getattr(sys, "_base_executable", None)
            if base_exec:
                candidates.append(Path(base_exec))
        candidates.append(Path(sys.executable))

    launcher = shutil.which("py") or shutil.which("py.exe")
    if launcher:
        tag = f"{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}"
        exe = run_capture([launcher, f"-{tag}", "-c", "import sys; print(sys.executable)"])
        if exe:
            candidates.append(Path(exe.splitlines()[0]))

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates.extend(
        [
            Path(local_app_data)
            / "Programs"
            / "Python"
            / f"Python{REQUIRED_PYTHON[0]}{REQUIRED_PYTHON[1]}"
            / "python.exe",
            Path(f"C:\\Python{REQUIRED_PYTHON[0]}{REQUIRED_PYTHON[1]}\\python.exe"),
            Path(f"C:\\Program Files\\Python{REQUIRED_PYTHON[0]}{REQUIRED_PYTHON[1]}\\python.exe"),
        ]
    )

    which_310 = shutil.which(f"python{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}")
    if which_310:
        candidates.append(Path(which_310))

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if not candidate.exists():
            continue
        version = python_version_info(candidate)
        if version and version[:2] == REQUIRED_PYTHON and is_64_bit(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Virtual environment management
# ---------------------------------------------------------------------------


def venv_dir() -> Path:
    """Return the path of the virtual environment."""
    return PROJECT_ROOT / VENV_DIR_NAME


def venv_python() -> Path:
    """Return the venv interpreter path."""
    return venv_dir() / VENV_PYTHON_REL


def is_running_inside_venv() -> bool:
    """Return whether this script is currently executed from inside .venv."""
    exe = Path(sys.executable).resolve()
    try:
        return venv_dir().resolve() in exe.parents
    except OSError:
        return False


def read_system_site_packages() -> bool:
    """Return whether the existing venv exposes global site-packages."""
    cfg = venv_dir() / "pyvenv.cfg"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("include-system-site-packages"):
                return line.split("=", 1)[1].strip().casefold() == "true"
    except OSError:
        pass
    return False


def venv_state() -> str:
    """
    Classify the existing venv: 'missing', 'ok', 'broken' or 'legacy'.

    'legacy' means usable but created with --system-site-packages, i.e. it
    depends on global packages and is therefore not self-contained.
    """
    if not venv_dir().exists() or not venv_python().exists():
        return "missing"
    probe = run_capture([venv_python(), "-m", "pip", "--version"], timeout=120)
    if not probe or "pip" not in probe:
        return "broken"
    if read_system_site_packages():
        return "legacy"
    return "ok"


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    """Ask the user a yes/no question; return the answer."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            answer = input(f"{prompt} {suffix}: ").strip().casefold()
        except EOFError:
            return default
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def create_venv_dir(base_python: Path) -> bool:
    """Create the virtual environment (caller removed any old .venv)."""
    if not base_python.exists():
        print(f"[FAIL] Base Python no longer exists: {base_python}")
        print("Pass a valid 64-bit Python 3.10 with --base-python and re-run.")
        return False
    print(f"Creating {VENV_DIR_NAME} from {base_python} ...")
    proc = run([base_python, "-m", "venv", venv_dir()])
    if proc.returncode != 0 or not venv_python().exists():
        print("[FAIL] Failed to create the virtual environment.")
        return False
    return True


# ---------------------------------------------------------------------------
# HALCON runtime detection (system dependency)
# ---------------------------------------------------------------------------


def _registry_halcon_roots() -> list[Path]:
    """Return HALCON install roots registered in the Windows registry."""
    roots: list[Path] = []
    try:
        import winreg
    except ImportError:
        return roots
    locations = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\MVTec\HALCON"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\MVTec\HALCON"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\MVTec\HALCON"),
    ]
    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, index)
                        index += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(key, name) as sub:
                            value, _ = winreg.QueryValueEx(sub, "Installation Directory")
                            roots.append(Path(str(value)))
                    except OSError:
                        continue
        except OSError:
            continue
    return roots


def detect_halcon_runtime() -> dict:
    """
    Detect the HALCON runtime installation.

    Returns a dict with keys 'root' (Path), 'version' (str), 'dll' (Path)
    and 'on_path' (str); each is None when not found.
    """
    info: dict = {"root": None, "version": None, "dll": None, "on_path": None}

    candidates: list[Path] = []
    env_root = os.environ.get("HALCONROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend(_registry_halcon_roots())
    for base in (Path(r"C:\Program Files\MVTec"), Path(r"C:\Program Files (x86)\MVTec")):
        if base.is_dir():
            candidates.extend(sorted(p for p in base.glob("HALCON-*") if p.is_dir()))

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        dll = candidate / "bin" / "x64-win64" / "halcon.dll"
        if dll.exists():
            info["root"] = candidate
            info["dll"] = dll
            match = re.search(r"HALCON-(\d{2}\.\d{2})", candidate.name)
            info["version"] = match.group(1) if match else None
            break

    for path in os.environ.get("PATH", "").split(os.pathsep):
        if path and (Path(path) / "halcon.dll").exists():
            info["on_path"] = path
            break

    return info


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def build_verify_snippet(modules: Sequence[tuple[str, Optional[str]]]) -> str:
    """Build a python snippet that imports modules and prints [OK]/[FAIL]."""
    lines = ["import sys", "import importlib", "", "failed = []", ""]
    for name, extra in modules:
        lines.append("try:")
        lines.append(f"    m = importlib.import_module({name!r})")
        if extra:
            lines.append(f"    {extra}")
        lines.append(f"    print(f'[OK] {name}')")
        lines.append("except Exception as exc:")
        lines.append(f"    print(f'[FAIL] {name}')")
        lines.append("    print(f'  Reason: {exc}')")
        lines.append(f"    failed.append({name!r})")
        lines.append("")
    lines.append("sys.exit(1 if failed else 0)")
    return "\n".join(lines)


def run_verify(
    modules: Sequence[tuple[str, Optional[str]]], label: str
) -> tuple[bool, list[str]]:
    """Run the import verification with the venv python; return (ok, failed)."""
    snippet = build_verify_snippet(modules)
    fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="tms_verify_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(snippet)
        print(f"  $ <venv python> run {label} import checks")
        proc = subprocess.run(
            [str(venv_python()), tmp_path],
            capture_output=True,
            text=True,
            errors="replace",
            cwd=str(PROJECT_ROOT),
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    output = (proc.stdout or "") + (proc.stderr or "")
    print(output.rstrip())

    failed = [name for name, _ in modules if f"[FAIL] {name}" in output]
    return proc.returncode == 0 and not failed, failed


def run_app_import_check() -> bool:
    """Import the application package as an end-to-end sanity check."""
    print('  $ <venv python> -c "import app.application"')
    proc = subprocess.run(
        [str(venv_python()), "-c", "import app.application; print('app.application imported OK')"],
        capture_output=True,
        text=True,
        errors="replace",
        cwd=str(PROJECT_ROOT),
    )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    print(output)
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Set up the Thermal Monitoring System v2 development environment."
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete an existing .venv and create a fresh one.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Answer yes to every confirmation prompt.",
    )
    parser.add_argument(
        "--base-python",
        type=Path,
        default=None,
        help="Path to a 64-bit Python 3.10 executable.",
    )
    parser.add_argument(
        "--skip-dev",
        action="store_true",
        help="Do not install requirements-dev.txt.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the full environment setup."""
    args = parse_args()

    print("=" * 60)
    print("Thermal Monitoring System v2 - Environment Setup")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Step A - Python
    # ------------------------------------------------------------------
    step("Step A - Check Python")
    print(f"Python version: {sys.version.split()[0]} (running interpreter)")
    print(f"Python executable: {sys.executable}")

    base_python = find_base_python(args.base_python)
    if base_python is None:
        print("[FAIL] A 64-bit Python 3.10 interpreter was not found.")
        print("This project requires Python 3.10 (64-bit).")
        print("Download it from https://www.python.org/downloads/release/python-3107/")
        print("During installation enable 'Add python.exe to PATH', then run this setup again.")
        return 1

    base_version = python_version_info(base_python)
    version_str = ".".join(str(part) for part in base_version) if base_version else "unknown"
    print(f"Using Python {version_str} (64-bit): {base_python}")

    # ------------------------------------------------------------------
    # Step B - Project directory
    # ------------------------------------------------------------------
    step("Step B - Check project directory")
    if not (PROJECT_ROOT / "main.py").exists():
        print("[FAIL] main.py not found next to setup_environment.py.")
        print("Run this script from the repository root.")
        return 1
    print(f"Project root: {PROJECT_ROOT}")
    if Path.cwd().resolve() != PROJECT_ROOT:
        warn(f"Current directory is {Path.cwd()}, working from project root instead.")

    # ------------------------------------------------------------------
    # Step C - Virtual environment
    # ------------------------------------------------------------------
    step("Step C - Create virtual environment")
    state = venv_state()
    need_create = state == "missing"
    if args.recreate:
        need_create = True
    elif state in ("broken", "legacy"):
        prompt = (
            "Existing .venv is broken or incomplete. Recreate it?"
            if state == "broken"
            else "Existing .venv depends on global packages "
            "(system-site-packages=true). Recreate it as self-contained?"
        )
        need_create = args.yes or ask_yes_no(prompt)

    if need_create:
        if is_running_inside_venv():
            print("[FAIL] Cannot recreate .venv while it is the active interpreter.")
            print("You are running setup_environment.py from inside .venv.")
            print("Run it with the base Python instead, for example:")
            print(f"  {Path(sys._base_executable)} setup_environment.py --recreate")
            print("or exit this shell and run `python setup_environment.py` again.")
            return 1
        if venv_dir().exists():
            print(f"Removing existing {VENV_DIR_NAME} ...")
            shutil.rmtree(venv_dir())
        if not create_venv_dir(base_python):
            return 1
    else:
        print(f"{VENV_DIR_NAME} already exists and is usable - reusing it.")

    # ------------------------------------------------------------------
    # Step D - Upgrade pip
    # ------------------------------------------------------------------
    step("Step D - Upgrade pip")
    proc = run([venv_python(), "-m", "pip", "install", "--upgrade", "pip"])
    if proc.returncode != 0:
        warn("pip upgrade failed; continuing with the bundled pip.")

    # ------------------------------------------------------------------
    # Step E - Runtime dependencies
    # ------------------------------------------------------------------
    step("Step E - Install runtime dependencies")
    requirements = PROJECT_ROOT / REQUIREMENTS_FILE
    if not requirements.exists():
        print(f"[FAIL] Missing {REQUIREMENTS_FILE}.")
        return 1
    proc = run([venv_python(), "-m", "pip", "install", "-r", requirements])
    if proc.returncode != 0:
        print("[FAIL] Runtime dependency installation failed.")
        return 1

    # ------------------------------------------------------------------
    # Step F - Development dependencies
    # ------------------------------------------------------------------
    step("Step F - Install development dependencies")
    dev_requirements = PROJECT_ROOT / REQUIREMENTS_DEV_FILE
    if not dev_requirements.exists():
        print("No requirements-dev.txt found - skipping.")
    elif args.skip_dev:
        print("Skipped (--skip-dev).")
    else:
        proc = run([venv_python(), "-m", "pip", "install", "-r", dev_requirements])
        if proc.returncode != 0:
            print("[FAIL] Development dependency installation failed.")
            return 1

    # ------------------------------------------------------------------
    # Step G - Global / system dependencies
    # ------------------------------------------------------------------
    step("Step G - Check global / system dependencies")
    halcon_info = detect_halcon_runtime()
    if halcon_info["dll"] is None:
        print(f"[FAIL] HALCON runtime (version {HALCON_RUNTIME_VER}) not found.")
    else:
        runtime_version = halcon_info["version"] or "unknown"
        print(f"[OK] HALCON runtime detected: {halcon_info['root']}")
        print(f"     Version: {runtime_version}")
        if runtime_version != HALCON_RUNTIME_VER:
            warn(
                f"HALCON runtime is {runtime_version} but "
                f"mvtec-halcon=={HALCON_PYPI_VERSION} expects {HALCON_RUNTIME_VER}."
            )
        if halcon_info["on_path"]:
            print(f"     halcon.dll on PATH: {halcon_info['on_path']}")
        else:
            warn(
                "halcon.dll is not on PATH. Add "
                "<HALCON root>\\bin\\x64-win64 to PATH (the MVTec installer "
                "usually does this), otherwise importing halcon will fail."
            )
    print("Note: no pip packages are installed globally - everything lives in .venv.")

    # ------------------------------------------------------------------
    # Step H - Verify imports
    # ------------------------------------------------------------------
    step("Step H - Verify imports")
    runtime_ok, runtime_failed = run_verify(RUNTIME_MODULES, "runtime")
    if args.skip_dev or not dev_requirements.exists():
        dev_ok, dev_failed = True, []
    else:
        dev_ok, dev_failed = run_verify(DEV_MODULES, "development")
    app_ok = run_app_import_check()

    verification_ok = runtime_ok and dev_ok
    halcon_runtime_present = halcon_info["dll"] is not None
    complete = verification_ok and halcon_runtime_present and app_ok

    # ------------------------------------------------------------------
    # Step I - Final report
    # ------------------------------------------------------------------
    step("Final report")
    print("=" * 60)
    if complete:
        print("Environment setup completed")
    else:
        print("SETUP INCOMPLETE")
    print("=" * 60)
    print(f"Python:                   {version_str} (64-bit)")
    print(f"Virtual environment:      {venv_dir()}")
    print(f"Runtime dependencies:     {REQUIREMENTS_FILE}")
    print(f"Development dependencies: {REQUIREMENTS_DEV_FILE}")
    halcon_line = (
        f"HALCON:                   runtime {halcon_info['version'] or 'not found'} "
        f"at {halcon_info['root'] or 'N/A'} / bindings mvtec-halcon=={HALCON_PYPI_VERSION}"
    )
    print(halcon_line)
    print(f"Verification:             {'passed' if verification_ok else 'failed - see [FAIL] above'}")
    print()
    print("To activate:")
    print("  PowerShell:")
    print("    .venv\\Scripts\\Activate.ps1")
    print("  CMD:")
    print("    .venv\\Scripts\\activate.bat")

    if not complete:
        print()
        print("SETUP INCOMPLETE")
        print()
        print("Missing:")
        if not halcon_runtime_present:
            print(f"- HALCON runtime (version {HALCON_RUNTIME_VER})")
        for name in runtime_failed:
            print(f"- runtime module: {name}")
        for name in dev_failed:
            print(f"- development module: {name}")
        if not app_ok:
            print("- application package import: app.application")
        print()
        print("Action required:")
        if not halcon_runtime_present:
            print(f"  - {HALCON_INSTALL_HINT}")
        if runtime_failed or not app_ok:
            print("  - Resolve the [FAIL] entries above, then run this setup again.")
        print()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())