# Thermal Monitoring System v2

A modular industrial thermal monitoring system designed for continuous real-time monitoring using GigE Vision thermal cameras.

This project is a complete redesign of the previous prototype. The primary goal is to build a scalable, maintainable, and hardware-independent architecture from the beginning rather than continuously modifying an existing codebase.

---

# Project Goals

The system shall support:

- Up to 8 thermal cameras
- Approximately 200 monitoring positions per camera
- Multiple ROIs per position
- Real-time temperature monitoring
- Alarm generation
- Image and video recording
- Camera calibration
- Database-driven configuration
- Multi-camera operation
- Future support for additional camera models

---

# Design Philosophy

This project follows several strict architectural rules.

## 1. Single Responsibility

Every class is responsible for one task only.

Examples:

- CameraWorker acquires images.
- ProcessingPipeline processes images.
- AlarmEngine evaluates alarms.
- Recorder stores images and videos.
- GUI displays information.

No class should perform multiple unrelated tasks.

---

## 2. Separation of Hardware and Processing

Only the camera layer communicates with the camera hardware.

All other modules work with data objects and remain independent of the camera vendor.

---

## 3. Processing Independence

Image processing must not depend on:

- Camera model
- Camera SDK
- GigE implementation
- GUI

The processing pipeline only accepts image data and returns processed results.

---

## 4. GUI is a Consumer

The GUI never communicates directly with camera hardware.

It only displays processed information produced by the backend.

---

## 5. Raw Data is Immutable

Raw thermal frames are never modified.

Display images are generated separately.

This guarantees that original thermal information is always preserved.

---

## 6. Loose Coupling

Modules communicate only through well-defined interfaces and shared data models.

No module should directly depend on the internal implementation of another module.

---

# High-Level Architecture

```
Camera Discovery
        │
        ▼
Camera Manager
        │
        ▼
Camera Worker
        │
        ▼
Raw Frame
        │
        ▼
Processing Pipeline
        │
        ▼
Frame Result
        │
 ┌──────┼──────────────┐
 ▼      ▼              ▼
GUI   Alarm Engine   Recorder
```

---

# Project Structure

```
app/
camera/
processing/
roi/
alarms/
recorder/
database/
gui/
configuration/
utilities/
core/
assets/
docs/
tests/
logs/
```

Each directory has one clearly defined responsibility.

---

# Camera Information

Current camera:

- Fluke ThermoView TV46L

Interface:

- GigE Vision

Camera discovery:

- HALCON GigEVision2

Camera identification:

- Serial Number

Camera connection:

- HALCON Device Identifier

Raw image format:

- 16-bit grayscale thermal image

---

# Important Technical Decisions

## Camera Identification

Every camera is identified by its serial number.

IP addresses are treated as network configuration only and are never used as the primary identifier.

---

## Camera Connection

The camera is opened using the HALCON device identifier returned during camera discovery.

The device identifier is considered the only reliable identifier for establishing a GigE Vision connection.

---

## Processing Flow

The processing pipeline always receives raw image data.

The pipeline is responsible for producing:

- Display image
- Temperature matrix
- ROI measurements
- Alarm information

---

## Threading Model

Each camera owns an independent acquisition thread.

Image processing is independent of image acquisition.

The GUI must never block camera acquisition.

---

# Development Roadmap

## Phase 1

Foundation

- Project structure
- Core models
- Configuration
- Logging

---

## Phase 2

Camera Layer

- Camera discovery
- Camera manager
- Camera worker
- Continuous acquisition

---

## Phase 3

Processing

- Processing pipeline
- Temperature conversion
- Image generation
- FrameResult

---

## Phase 4

Database

- Camera configuration
- Position management
- ROI storage
- Calibration data

---

## Phase 5

GUI

- Observer window
- Calibration window
- Camera dashboard

---

## Phase 6

ROI System

- ROI editor
- ROI measurements
- ROI persistence

---

## Phase 7

Alarm Engine

- Warning
- Critical
- Emergency
- Alarm history

---

## Phase 8

Recorder

- Image capture
- Video recording
- Alarm recording

---

## Phase 9

System Integration

- Performance optimization
- Multi-camera validation
- Production testing

---

# Current Status

Current Phase:

Phase 1 — Foundation

Completed:

- Repository created
- Project structure finalized

In Progress:

- Core architecture

Not Started:

- Camera discovery
- Camera manager
- Camera worker
- Processing pipeline
- GUI
- Database integration

---

# Guiding Principle

Architecture decisions are made before implementation.

The objective is to minimize future refactoring by establishing stable module boundaries and clear responsibilities from the beginning.



fetch('https://openrouter.ai/api/v1/chat/completions', {
  method: 'POST',
  headers: {
    Authorization: 'Bearer <OPENROUTER_API_KEY>',
    'HTTP-Referer': '<YOUR_SITE_URL>',
    'X-Title': '<YOUR_SITE_NAME>',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'openai/gpt-4o',
    messages: [
      {
        role: 'user',
        content: 'What is the meaning of life?',
      },
    ],
  }),
});


