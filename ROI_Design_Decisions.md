# ROI Design Decisions

> **Project:** Thermal Monitoring System
>
> **Version:** 1.0
>
> This document records the architectural decisions made during the design of the ROI subsystem.
>
> These decisions should not be changed without a clear technical justification, as they directly affect scalability, maintainability, and performance.

---

# Purpose

This document explains **why** specific design decisions were made.

It is **not** an implementation guide.

It is **not** an API reference.

It exists so future developers and AI coding agents understand the reasoning behind the architecture.

---

# Design Goals

The ROI subsystem must be:

- Scalable
- Modular
- Thread-safe
- Easy to maintain
- Easy to extend
- Independent of the GUI whenever possible

The target system supports:

- 8 Cameras
- ~200 Positions per Camera
- ~100 ROIs per Position

This represents approximately:

```
160,000 configured ROIs
```

The architecture must comfortably support this scale.

---

# Decision 1
## Use HALCON Drawing Objects

### Decision

Interactive ROI editing will use HALCON Drawing Objects.

Examples:

- create_drawing_object_rectangle1
- create_drawing_object_rectangle2
- create_drawing_object_circle
- create_drawing_object_ellipse
- create_drawing_object_line
- create_drawing_object_xld

---

### Reason

HALCON Drawing Objects already provide:

- Interactive editing
- Mouse handling
- Selection
- Rotation
- Resize
- Move
- Callbacks

Reimplementing this functionality would duplicate existing HALCON capabilities.

---

### Consequences

The application does **not** implement custom mouse interaction.

HALCON manages all ROI interaction.

---

# Decision 2
## Never Use Blocking draw_* Operators

### Decision

The following operators are prohibited.

```
draw_rectangle1
draw_rectangle2
draw_circle
draw_ellipse
draw_region
```

---

### Reason

These operators block the calling thread.

They are intended primarily for HDevelop examples and simple scripts.

Production GUI applications should instead use Drawing Objects.

---

### Consequences

All interactive editing must use Drawing Objects.

---

# Decision 3
## Drawing Objects Exist Only During Editing

### Decision

Drawing Objects are **temporary editor objects**.

They are **not** permanent runtime objects.

---

### Reason

The operator only edits one camera at a time.

Keeping thousands of drawing objects alive wastes memory and GUI resources.

Drawing Objects are only useful while the operator is interacting with an ROI.

---

### Workflow

```
ROI Metadata

↓

Create Drawing Objects

↓

Edit

↓

Update Geometry

↓

Destroy Drawing Objects
```

---

### Consequences

The runtime processing engine never depends on Drawing Objects.

---

# Decision 4
## Separate ROI Definition from ROI Editor

### Decision

The ROI subsystem consists of separate logical layers.

```
Persistent ROI Definition

↓

Runtime ROI Cache

↓

ROI Editor
```

---

### Reason

Editing and processing are fundamentally different operations.

Separating them simplifies the architecture.

---

### Consequences

The Processing Pipeline never communicates directly with the editor.

---

# Decision 5
## Runtime Processing Uses Cached HRegions

### Decision

Runtime processing operates on cached HALCON Regions.

Not Drawing Objects.

---

### Workflow

```
Geometry

↓

gen_rectangle2()

↓

HRegion

↓

Cached

↓

Processing
```

---

### Reason

Creating Regions every frame is unnecessary.

Caching reduces CPU usage.

---

### Consequences

Regions are regenerated only when:

- ROI changes
- Position changes
- Configuration reloads

---

# Decision 6
## Geometry is Stored as Plain Data

### Decision

Persistent storage contains only geometry values.

Example:

Rectangle2

```
row
column
phi
length1
length2
```

Circle

```
row
column
radius
```

Polygon

```
rows[]
columns[]
```

---

### Reason

HALCON Handles cannot be serialized.

Plain data is portable and future-proof.

---

### Consequences

Drawing Objects are recreated when editing starts.

---

# Decision 7
## Never Store HALCON Handles

### Decision

The following must never be written to disk:

- Drawing Object Handles
- Window Handles
- HALCON Runtime Objects

---

### Reason

Handles are valid only during the current application session.

---

### Consequences

Only numeric geometry is serialized.

---

# Decision 8
## HALCON is the Source of Truth During Editing

### Decision

While editing:

HALCON owns the geometry.

Geometry changes are read using:

```
get_drawing_object_params()
```

---

### Reason

Avoid maintaining two independent copies of geometry.

---

### Workflow

```
Drawing Object

↓

Move

↓

Resize

↓

Read Parameters

↓

Update ROI Definition
```

---

# Decision 9
## ROI Definition is the Source of Truth Outside Editing

### Decision

After editing finishes:

ROI Definition becomes the authoritative source.

---

### Reason

Drawing Objects no longer exist.

---

### Consequences

The runtime system reads only the ROI Definition.

---

# Decision 10
## Processing Must Not Depend on the GUI

### Decision

The Processing Pipeline must never reference:

- Drawing Objects
- Windows
- Mouse Events

---

### Reason

Processing continues even when:

- GUI is hidden
- Another camera is displayed
- Operator is not editing

---

### Consequences

GUI and Processing are fully decoupled.

---

# Decision 11
## Every Camera Processes Independently

### Decision

Each camera processes its current position independently.

The displayed camera does not affect background processing.

---

### Example

```
Camera 1 → Position 52

Camera 2 → Position 18

Camera 3 → Position 91
```

All continue processing simultaneously.

---

### Consequences

Displaying Camera 1 must not pause processing of Cameras 2–8.

---

# Decision 12
## Processing Uses Only Current Position

### Decision

Each camera loads only the ROIs for its current position.

---

### Reason

Processing all 200 positions simultaneously would waste memory and CPU time.

---

### Workflow

```
Camera

↓

Current Position

↓

Load Runtime ROIs

↓

Process

↓

Position Changes

↓

Unload

↓

Load Next Position
```

---

# Decision 13
## Cached Regions are Updated Only When Required

### Decision

Cached HRegions are regenerated only when necessary.

---

### Events

- ROI modified
- Position changed
- Configuration loaded

---

### Reason

Avoid unnecessary Region creation.

---

# Decision 14
## HALCON Performs Image Processing

### Decision

HALCON operators are preferred over custom NumPy implementations.

Examples:

```
intensity()

min_max_gray()

gray_features()

gray_histo()

reduce_domain()
```

---

### Reason

HALCON is optimized for image processing.

Using HALCON provides:

- Better performance
- Cleaner code
- Easier maintenance

---

### Consequences

Avoid implementing duplicate algorithms unless absolutely necessary.

---

# Decision 15
## Separate Responsibilities

### Decision

Each subsystem has one responsibility.

Example

```
ROI Manager

↓

Configuration

↓

Runtime Cache

↓

ROI Processor

↓

Alarm Processor

↓

Recorder

↓

GUI
```

---

### Reason

Single Responsibility Principle.

---

### Consequences

Avoid large classes.

Avoid mixing GUI and processing logic.

---

# Decision 16
## Callbacks Should Be Lightweight

### Decision

Drawing Object callbacks should only notify the ROI Manager.

---

### Reason

HALCON documentation warns against calling display operators inside callbacks.

---

### Consequences

Callbacks should:

- Read geometry
- Notify listeners
- Return immediately

---

# Decision 17
## Configuration is Persistent

### Decision

All ROI configuration must be stored independently of HALCON.

---

### Stored Data

- Geometry
- Thresholds
- Colors
- Alarm settings
- Recording settings
- Visibility
- Enabled state

---

### Not Stored

- Drawing Objects
- HRegions
- Runtime Statistics

---

# Decision 18
## Runtime Objects Are Temporary

### Decision

Runtime caches are recreated when required.

---

### Contents

- Cached Region
- Current Statistics
- Alarm State
- Timestamp

---

### Reason

Runtime information should never be serialized.

---

# Decision 19
## Future Expansion

The architecture should support future additions without redesign.

Possible future features include:

- Polygon ROIs
- Multi-region ROIs
- ROI templates
- ROI groups
- ROI inheritance
- Dynamic thresholds
- AI-based ROIs
- ROI analytics
- Trend graphs
- Heat maps
- ROI versioning

No architectural changes should be required to support these features.

---

# Final Architecture

```
                 ROI Definition
                (Persistent JSON)
                        │
                        │
                        ▼
                Runtime ROI Cache
         (Cached HRegion + Statistics)
                        │
                        │
                        ▼
                 ROI Processor
                        │
                        ▼
                Alarm Processor
                        │
                        ▼
                   Recorder
                        │
                        ▼
                      GUI

                 ▲
                 │
         Only While Editing
                 │
      HALCON Drawing Objects
```

---

# Summary

The ROI subsystem is designed around three key principles:

1. **Drawing Objects are editor-only tools.**

2. **Runtime processing uses cached HALCON Regions.**

3. **GUI and processing remain completely independent.**

These principles provide a scalable foundation capable of supporting large multi-camera thermal monitoring systems while remaining maintainable and extensible.
