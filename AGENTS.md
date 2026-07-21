# AGENTS.md

# Response Guidelines
Keep responses concise and to the point unless the user requests more detail.

# Planning Mode
Always ask clarifying questions before planning.
Never assume:
Design
Technology stack
Features
Use deep-dive sub-agents for research.
Use deep-dive sub-agents to review different aspects of the plan before presenting it.

# Change / Edit Mode
Prefer using sub-agents instead of implementing features directly.
Act as a coordinator when using sub-agents.
Identify work that can be done in parallel and assign it to different sub-agents.
Use:
Premium models for complex tasks (e.g., coding)
Mid-tier models for simpler tasks (e.g., documentation)

# Code Quality
After completing any feature (large or small), always run:
Lint
Type check
Build (next build)
Verify that the project passes all checks before considering the task complete.

# Database Schema Changes
Whenever modifying the database schema:
Required:
Run drizzle generate
Run database migrations
Never:
Run drizzle push

# Testing
Always test changes.
Never assume changes work without verification.
Use any testing tools, libraries, scripts, MCP tools, or skills available in the project.
If the project has no testing infrastructure, ask the user whether testing should be skipped.

# UI Design
Always follow the project's design system when creating or reviewing UI.
Design system reference:
@DESIGN.md

# Coding Standards
Always follow the project's coding standards and architecture guidelines defined in:
@CODING.md


# Halcon Standarde
Whenever dealing with Halcon use the parameters in: 
Halcon_Parameters.md

# Change History

After every code modification, update `CHANGELOG.md` in the project root.
For each change, add a new entry using this format:

## YYYY-MM-DD HH:MM
### What changed
- Brief, user-friendly summary of the changes.
- Mention affected files or modules.
### Why
- Explain the reason for the change.
- Mention the bug fixed, feature added, refactor, or performance improvement.
### Notes
- Mention anything important for future debugging.
- Include side effects, assumptions, or things that should be tested.
### Files Changed
- src/roi_manager.py
- src/main_window.py
- src/camera_stream.py

Rules:
- Keep entries concise (3-10 lines).
- Write for a future developer who is unfamiliar with the recent work.
- Avoid technical jargon when a simpler explanation is sufficient.
- Never remove previous entries.
- Update this file after every completed task that modifies code.



## Setup And Commands
- Use Python 3.10.7 if possible; `InfoBook.md` lists the original setup target.
- `requirements.txt` is empty. Install runtime/test deps manually before verification: `python -m pip install numpy opencv-python PyQt5 pydantic scipy pytest` plus the MVTec HALCON Python package if touching camera hardware code.
- Run the desktop app with `python main.py`; the real bootstrap is `main.py -> app.application.Application`.
- Run focused tests with `python -m pytest tests/test_calibration.py` or another file under `tests/`; `python -m pytest tests` is the broad suite.
- Current checked-in `.venv` may not have `pytest`; verify with `python -m pytest ...` after installing deps.
- Root `test_tv46l_camera.py` is a real hardware/OpenCV window test for a Fluke TV46L; do not run it unless a camera and HALCON GigEVision2 setup are available.

## Architecture Boundaries
- GUI must talk to backend through `app.application_controller.ApplicationController`; keep camera hardware access out of `gui/`.
- HALCON calls should stay in the camera layer, especially `camera/services/halcon_driver.py`; processing code should operate on raw frame/data models only.
- `CameraFactory` wires one camera runtime: `CameraModel`, `TV46LCamera`, `CalibrationManager`, `ProcessingPipeline`, `ROIProcessor`, `AlarmProcessor`, and `PositionManager` into `CameraContext`.
- Processing flow is `RawFrame -> CalibrationProcessor -> ProcessedFrame -> ROIProcessor -> AlarmProcessor -> FrameResult` in `processing/pipeline/processing_pipeline.py`.
- Raw thermal frames are intended to remain immutable; generate display/temperature images separately.

## Repo Gotchas
- Trust executable code over roadmap prose: `README.md` and `PROJECT_STATUS.md` still contain early-phase/stale status details.
- Code currently imports `PyQt5` in `app/application.py`; `InfoBook.md` says `PySide6`, but the executable source uses PyQt5.
- Calibration defaults to `assets/calibration/calibration_blob.txt` via `configuration/settings.py`; calibration and processing tests depend on that file.
- Camera identity is serial-number centric in docs/models; IP address is network config, not the stable logical identity.
- `logs/` is gitignored, but importing `utilities.logger` creates `logs/application.log` when logging is enabled.
