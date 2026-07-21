# CODING.md

# Thermal Monitoring System v2
## Coding Standards & Architecture Rules

---

# Core Principles

The project is an industrial real-time thermal monitoring system.

Priorities:

1. Reliability
2. Readability
3. Maintainability
4. Performance

Never sacrifice correctness for shorter code.

---

# Architecture

Always follow the existing architecture.
GUI
↓
Application Controller
↓
Backend Services
↓
Processing Pipeline
↓
Camera Layer
↓
HALCON
Never bypass layers.
GUI must never communicate directly with hardware.
HALCON calls belong only inside the camera layer.

---

# Single Responsibility

Each class should have one responsibility.

Bad
Camera class performs:
Camera acquisition
Calibration
ROI processing
Alarm generation
Database
GUI updates

Good
TV46LCamera
↓
CalibrationProcessor
↓
ROIProcessor
↓
AlarmProcessor
↓
Recorder
↓
Database

---

# Dependency Direction

Dependencies should always point downward.
GUI
↓
Controller
↓
Services
↓
Models
Never import GUI inside backend.
Never import hardware inside processing.

---

# Data Flow

Always preserve the processing pipeline.
RawFrame
↓
CalibrationProcessor
↓
ProcessedFrame
↓
ROIProcessor
↓
AlarmProcessor
↓
FrameResult
Never bypass stages.

---

# Raw Data

Raw thermal data is immutable.
Never modify RawFrame.image.
Generate new objects instead.

---

# Camera Layer

Camera layer responsibilities only:
Camera discovery
Connection
Streaming
Parameter access
Health monitoring
Manual NUC

Never perform:
Calibration
ROI
Alarms
Database
GUI rendering

---

# Threading

Camera acquisition must run in dedicated threads.
GUI thread must never block.

Never perform:
Network IO
Disk IO
HALCON calls
Heavy processing
inside GUI thread.

---

# Logging

Never use print().
Always use:
logger.debug()
logger.info()
logger.warning()
logger.error()
logger.exception()
Exceptions should always include useful context.

---

# Error Handling

Never silently ignore exceptions.
Bad
except:
    pass
Good
except Exception:
    logger.exception(...)
If an error can be recovered:
Handle it.
Otherwise:
Raise it.

---

# Type Hints

All public functions require type hints.
Example
def connect() -> None
def grab_frame() -> RawFrame
Avoid Any unless unavoidable.

---

# Docstrings

Public classes
Public methods
Complex private methods
must include docstrings.
Keep them concise.

---

# Naming

Classes
PascalCase
Functions
snake_case
Variables
snake_case
Constants
UPPER_CASE
Private members
_prefix

Example
_frame_counter
_latest_frame

---

# Dataclasses

Use dataclasses for models.
Prefer:
slots=True
frozen=True
when appropriate.

---

# Configuration

Never hardcode:
Paths
Thresholds
Ports
Timeouts
Use configuration/settings.py.

---

# Imports

Standard Library
↓
Third Party
↓
Project Imports
Separate groups with one blank line.
Avoid wildcard imports.

---

# Models

Models should contain data only.
No business logic.
No hardware access.
No GUI code.

---

# Services

Services contain business logic.
Services should not depend on GUI.

---

# GUI

GUI responsibilities:
Display data
Collect user input
Forward commands

GUI must never:
Access HALCON
Process thermal data
Perform ROI calculations
Access database directly

---

# Performance

Avoid unnecessary copies.
Avoid unnecessary allocations.
Avoid repeated conversions.
Prefer incremental updates.
Never optimize before correctness.

---

# Memory

Avoid large temporary objects.
Reuse buffers where possible.
Large images should not be copied unnecessarily.

---

# Camera Identity

Always identify cameras using:
Serial Number
IP addresses are configuration only.
Never use IP as the primary identifier.

---

# Testing

Every feature should be tested.
Hardware code:
Use dedicated hardware tests.
Processing:
Use pytest.
GUI:
Test manually if automated tests are unavailable.
Never assume code works.

---

# Verification

Before completing work:
Lint
Type Check
Run Tests
Verify Build
If verification cannot be completed:
State exactly why.
Never claim code works without verification.

---

# Refactoring

Prefer improving existing code over rewriting.
Avoid introducing unnecessary abstractions.
Keep changes incremental.

---

# Comments

Explain WHY.
Do not explain obvious code.
Bad
i += 1

# Increment i
Good

# Skip first invalid calibration frame.

---

# Magic Numbers

Avoid magic numbers.
Use named constants.
Bad
timeout = 5
Good
timeout = Settings.CONNECTION_TIMEOUT

---

# Public API

Keep public interfaces stable.
Avoid breaking existing APIs unless required.

---

# SOLID

Prefer SOLID principles.
Avoid inheritance unless it provides clear value.
Prefer composition.

---

# Industrial Software Guidelines

Software should continue operating whenever safely possible.
Recover from transient failures.
Fail gracefully.
Log useful diagnostic information.
Avoid unnecessary crashes.

---

# AI Agent Rules

When generating code:
Follow the existing architecture.
Do not invent new patterns unless requested.
Reuse existing models and services.
Prefer consistency over cleverness.
Keep implementations simple.
Generate production-quality code.
Assume future maintainers will read every line.