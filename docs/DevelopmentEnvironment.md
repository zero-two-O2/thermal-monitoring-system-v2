# Development Environment Audit

Audit date: 2026-08-03
Scope: Global Python installation and project virtual environment.

---

## Summary

The project runs on Python 3.10.7. The virtual environment uses
`include-system-site-packages = true` (a project constraint — HALCON Python
bindings exist only in the global installation). The environment was unhealthy
(corrupted pip, missing debugpy, no VS Code debug configuration) and has been
repaired. One known issue remains: the HALCON interface package is one patch
release behind the installed HALCON runtime.

---

## Versions

| Component | Version | Location |
|---|---|---|
| Python | 3.10.7 (64-bit) | Global + venv |
| Global Python executable | `C:\Users\admin\AppData\Local\Programs\Python\Python310\python.exe` | Global |
| Project venv executable | `D:\Projects\Thermal_Monitoring_System_v2\.venv\Scripts\python.exe` | venv |
| HALCON runtime | 24.11.3 (24.11.3.0) | `C:\Program Files\MVTec\HALCON-24.11-Progress-Steady` |
| HALCON Python interface | 24113.0.0 | Global (`mvtec-halcon`) |
| NumPy | 2.2.6 | Global |
| OpenCV | 4.13.0 | Global |
| PyQt5 | 5.15.11 | Global (used by the main application) |
| PyQt6 | 6.11.0 | venv (used by test tools) |
| PySide6 | 6.11.1 | venv (installed, currently unused) |
| debugpy | 1.8.21 | venv |
| pip | 26.2 | venv |
| pytest | 9.1.1 | venv |
| ruff | 0.15.22 | venv |
| psutil | 7.2.2 | venv |
| harvesters | 1.4.3 | Global |
| genicam | 1.5.1 | Global |

---

## Global vs. venv package split

Global installation provides (via `include-system-site-packages`):

- `mvtec-halcon` (HALCON Python interface)
- `numpy`
- `opencv-python`
- `PyQt5` — the GUI framework of the main application
- `harvesters`, `genicam` (GigE Vision camera access)

Virtual environment provides:

- `PyQt6` — used by `tests/` and `tests/pipeline_analyzer/`
- `pytest`, `ruff`, `psutil`
- `debugpy`
- `pip`

---

## Issues found and resolved

1. **Corrupted pip inside the venv**
   - Symptom: `ModuleNotFoundError: No module named 'pip._vendor.rich._null_file'`;
     `python -m pip` failed completely.
   - Cause: the venv-local pip directory was incomplete (missing
     `pip-*.dist-info` and vendored files).
   - Fix: removed the broken `.venv\Lib\site-packages\pip` directory and
     reinstalled: `python -m pip install --upgrade pip` (now pip 26.2,
     venv-local).
2. **debugpy not installed in the venv**
   - Symptom: VS Code used the extension-bundled debugger; debugging crashed
     with a `KeyboardInterrupt` inside pydevd tracing hooks while importing
     NumPy.
   - Fix: `python -m pip install debugpy` (now 1.8.21, venv-local). VS Code
     now uses the venv debugger.
3. **No VS Code debug configuration**
   - Fix: created `.vscode\launch.json` and `.vscode\settings.json` pointing
     at the venv interpreter.
4. **Dependencies not documented**
   - Fix: created `requirements-dev.txt` and `docs\Development_Setup.md`.

---

## Resolved: HALCON interface/runtime version mismatch

Previously the installed HALCON interface package (`mvtec-halcon` 24112.0.0)
was one patch release behind the installed runtime (24.11.3), and every import
emitted a version-mismatch warning.

Resolved on 2026-08-03 by upgrading the global interface package (global
Python only, venv untouched, HALCON runtime not reinstalled):

```
C:\Users\admin\AppData\Local\Programs\Python\Python310\python.exe -m pip install --upgrade mvtec-halcon==24113
```

Result:

- Interface package: `mvtec-halcon` 24113.0.0 (matches runtime 24.11.3)
- Runtime: unchanged, still 24.11.3
- `import halcon` succeeds without warnings from both the global Python and
  the project venv (which inherits HALCON via system site packages)

---

## Verification

Run the environment check script:

```
.venv\Scripts\python.exe tools\check_environment.py
```

Expected result: `ALL CHECKS PASSED`, exit code 0.
