# Development Setup

> **Recommended flow**: run `python setup_environment.py` from the repository
> root. It creates a self-contained `.venv`, installs all dependencies, checks
> the HALCON runtime and verifies imports — no global packages required.
> The global-package instructions below describe the legacy setup and are kept
> for reference.

How to set up, repair, and verify the development environment for the Thermal
Monitoring System v2.

---

## Required software

| Component | Version | Notes |
|---|---|---|
| Python | 3.10.x (3.10.7) | 64-bit. The project pins Python 3.10 — do not use 3.11+ or 3.9. |
| HALCON runtime | 24.11 (Progress Steady) | Installed at `C:\Program Files\MVTec\HALCON-24.11-Progress-Steady` |
| HALCON Python interface | `mvtec-halcon==24113` | Global installation, see below |

> **Pin Python**: keep every developer on Python 3.10.x. The venv is created
> from the global Python 3.10 and the global HALCON bindings were built for it.

---

## HALCON (global dependency — do NOT touch)

The HALCON Python bindings (`mvtec-halcon`) are available only in the global
Python installation and are used from there on purpose. This project does not
install HALCON inside the virtual environment.

Global Python: `C:\Users\admin\AppData\Local\Programs\Python\Python310\python.exe`

Required global packages (installed in the global Python, not the venv):

- `mvtec-halcon` (24113 recommended; matches HALCON runtime 24.11.3)
- `numpy` (2.2.6)
- `opencv-python` (4.13.0)
- `PyQt5` (5.15.11) — GUI framework of the main application
- `harvesters`, `genicam` — GigE Vision camera access

Check the HALCON version match:

```
C:\Users\admin\AppData\Local\Programs\Python\Python310\python.exe -c "import halcon"
```

If you see `Wrong interface package version`, upgrade the global interface
package to match the installed runtime:

```
C:\Users\admin\AppData\Local\Programs\Python\Python310\python.exe -m pip install --upgrade mvtec-halcon==24113
```

---

## Why system site packages are enabled

The virtual environment is created with `--system-site-packages`, and
`.venv\pyvenv.cfg` contains `include-system-site-packages = true`.

Reason: HALCON, NumPy, OpenCV, and PyQt5 are supplied by the global
installation. HALCON must not be duplicated inside the venv.

The venv itself only contains development tooling and test GUI packages:
PyQt6, pytest, ruff, debugpy, psutil.

---

## Creating the venv (first time or full rebuild)

```
python -m venv --system-site-packages .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Important:

- The `--system-site-packages` flag is required. Without it HALCON, NumPy,
  OpenCV, and PyQt5 will not be importable from the venv.
- Do not install `mvtec-halcon` into the venv.

---

## Repairing the environment

Symptoms:

- `python -m pip` fails with `ModuleNotFoundError: No module named 'pip._vendor...'`
  → the venv-local pip is corrupted. Fix:

```
Remove-Item -Recurse -Force .venv\Lib\site-packages\pip
.venv\Scripts\python.exe -m pip install --upgrade pip
```

- `KeyboardInterrupt` traceback inside `pydevd_cython` when starting a VS Code
  debug session while importing NumPy → debugpy is missing or stale. Fix:

```
.venv\Scripts\python.exe -m pip install --upgrade debugpy
```

- If the venv is beyond repair, delete it and recreate it (see above). The
  global installation is never modified by the repair.

---

## Verifying the installation

Run the environment check script:

```
.venv\Scripts\python.exe tools\check_environment.py
```

Expected output: `ALL CHECKS PASSED`, exit code 0. The script verifies:

- interpreter (venv, system site packages enabled)
- halcon, numpy, cv2, PyQt5, PyQt6, debugpy, pytest, ruff imports and versions
- pip and mvtec-halcon distribution versions

Additionally, sanity-check the application imports:

```
.venv\Scripts\python.exe -c "import app.application"
```

---

## VS Code setup

`.vscode\settings.json` selects the venv interpreter:

```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe"
}
```

`.vscode\launch.json` provides the debug configuration:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Thermal Monitoring System (venv)",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/main.py",
            "console": "integratedTerminal",
            "justMyCode": true,
            "python": "${workspaceFolder}/.venv/Scripts/python.exe"
        }
    ]
}
```

The debugger uses the venv-local `debugpy` (installed via
`requirements-dev.txt`). If VS Code still uses a bundled debugger, run
`Python: Select Interpreter` and pick
`.venv\Scripts\python.exe` for the workspace.

---

## Notes

- `PySide6` is installed in the venv but not used by any project code — it can
  be uninstalled (`pip uninstall PySide6`) to save space.
- The old `docs\requirements.txt` is superseded by `requirements-dev.txt`;
  it listed packages that are no longer required (PySide6, pydantic, scipy).
