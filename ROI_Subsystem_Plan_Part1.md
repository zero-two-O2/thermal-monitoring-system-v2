# ROI Subsystem Implementation Plan (Part 1)

## Objective

Design and implement a production-quality ROI subsystem for the Thermal Monitoring System.

This document focuses only on the ROI subsystem design.

Do NOT start implementing code immediately.

The first goal is to produce a complete design that integrates cleanly with the existing project architecture.

---

# Existing Project Status

The following components already exist:

- Camera Manager
- TV46L Camera
- Camera Discovery
- Calibration
- RawFrame
- ProcessedFrame
- Processing Pipeline
- Alarm Processor (basic)
- ROI Processor (placeholder)

The ROI subsystem must integrate with the existing Processing Pipeline.

Do not redesign the existing architecture.

---

# Target System Requirements

The final system will support:

- 8 cameras
- Approximately 200 positions per camera
- Approximately 100 ROIs per position
- Thermal image processing
- Alarm generation
- ROI editing
- Configuration persistence

This results in approximately:

8 × 200 × 100

≈160,000 configured ROIs.

The design must scale accordingly.

---

# Runtime Requirements

Each camera continuously acquires images.

Each camera has one active position at a time.

Processing must continue for every camera regardless of which camera is displayed.

Only one camera is displayed to the operator.

---

# Important Design Decision

HALCON Drawing Objects are ONLY used for editing.

They are NOT permanent runtime objects.

Drawing objects should exist only while editing the currently displayed camera.

When editing ends:

- destroy drawing objects
- keep ROI metadata

Processing must not depend on drawing objects.

---

# ROI Data Layers

The ROI subsystem shall be separated into three logical layers.

Layer 1

Persistent ROI Definition

Stored in JSON.

Contains:

- ROI ID
- Name
- Camera
- Position
- Geometry
- Alarm settings
- Recording settings
- Display settings

No HALCON handles.

---

Layer 2

Runtime ROI Cache

Created when a camera changes position.

Contains:

- ROI metadata
- Cached HRegion
- Current statistics
- Alarm state

No Drawing Objects.

---

Layer 3

ROI Editor

Created only while editing.

Contains:

HALCON Drawing Objects

These synchronize geometry back to the ROI Definition.

Destroy them after editing.

---

# Geometry Storage

Store geometry only as numeric values.

Example:

Rectangle2

row

column

phi

length1

length2

Circle

row

column

radius

Polygon

rows[]

columns[]

Do not serialize HALCON handles.

---

# Region Generation

At runtime:

Geometry

↓

HALCON Region

using:

gen_rectangle1

gen_rectangle2

gen_circle

gen_ellipse

gen_region_polygon

These regions should be cached.

Do not regenerate them every frame.

Only regenerate when:

- ROI changes
- Position changes
- Configuration reloads

---

# Drawing Objects

Only use Drawing Objects inside the ROI Editor.

Supported operators:

create_drawing_object_rectangle1

create_drawing_object_rectangle2

create_drawing_object_circle

create_drawing_object_ellipse

create_drawing_object_line

create_drawing_object_xld

Never use draw_rectangle*

Never use draw_circle*

Never use blocking draw operators.

---

# ROI Editing

When editing starts:

Create Drawing Objects

↓

Attach to Window

↓

User edits

↓

Read Geometry

↓

Update ROI Definition

↓

Regenerate Cached Region

↓

Destroy Drawing Objects when editor closes

---

# Callbacks

Use:

on_attach

on_detach

on_drag

on_resize

on_select

Callbacks should never perform display operations.

Callbacks should only notify the ROI Manager.

---

# Synchronization

HALCON is the source of truth while editing.

ROI Definition is the source of truth after editing.

Never maintain two independent copies of geometry.

---

# Deliverables (Phase 1)

Before writing code, produce:

1.

ROI class diagram

2.

Runtime object diagram

3.

Sequence diagram for ROI editing

4.

Sequence diagram for runtime processing

5.

Package structure

6.

Responsibilities of every class

Wait for approval before implementation.