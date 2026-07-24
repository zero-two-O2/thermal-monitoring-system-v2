# ROI Subsystem Implementation Plan (Part 2)

## Processing Requirements

Processing must operate independently from the GUI.

The Processing Pipeline must never reference Drawing Objects.

Processing uses only cached HRegions.

---

# Processing Pipeline

For every acquired frame:

Temperature Image

↓

Current Position

↓

Runtime ROI Cache

↓

ROI Processor

↓

Alarm Processor

↓

Recorder

↓

GUI

The ROI Processor must not know whether an ROI originated from a Drawing Object.

---

# HALCON Operators

Use the project file:

halcon_operators.md

as the primary HALCON API reference.

Do not use undocumented operators.

Preferred operators include:

Drawing Objects

- create_drawing_object_rectangle2
- attach_drawing_object_to_window
- get_drawing_object_params
- set_drawing_object_params
- get_drawing_object_iconic

Region Generation

- gen_rectangle1
- gen_rectangle2
- gen_circle
- gen_ellipse
- gen_region_polygon

Processing

- reduce_domain
- intensity
- min_max_gray
- gray_features
- gray_histo

Morphology

- gray_opening
- gray_closing
- gray_dilation
- gray_erosion

Only introduce additional HALCON operators if required.

---

# ROI Statistics

Every Runtime ROI should expose:

Current Mean Temperature

Minimum Temperature

Maximum Temperature

Temperature Range

Standard Deviation

Timestamp

Alarm State

Future fields should be easy to add.

---

# Performance Goals

The system must be designed for:

8 Cameras

200 Positions

100 ROIs

The architecture must avoid:

Repeated allocation

Repeated region generation

Repeated object construction

Drawing Objects outside editing

Blocking HALCON operators

Unnecessary image copies

---

# Persistence

Design a JSON format.

Do not implement serialization yet.

The design must support:

Projects

Camera configurations

Position configurations

ROI configurations

Future compatibility.

---

# GUI Requirements

The GUI must support:

Create ROI

Delete ROI

Rename ROI

Duplicate ROI

Move ROI

Resize ROI

Rotate ROI

Enable/Disable ROI

Change Color

Change Thresholds

Show Current Temperature

Show Alarm State

Do not implement the GUI yet.

Only design the interfaces.

---

# Deliverables (Phase 2)

Produce:

Class diagram

Package diagram

Sequence diagrams

State diagram

JSON schema

Configuration schema

Thread interaction diagram

Processing flow diagram

GUI interaction diagram

---

# Coding Rules

Do not write large classes.

Prefer composition over inheritance.

Single Responsibility Principle.

Avoid global state.

Avoid circular dependencies.

Keep HALCON code isolated inside dedicated modules.

The rest of the project should not directly depend on HALCON whenever possible.

---

# Final Goal

After completing the design:

Present the proposed architecture.

Explain every class.

Explain every interaction.

Identify potential bottlenecks.

Only after design approval should implementation begin.

No production code should be written before the design is reviewed and accepted.