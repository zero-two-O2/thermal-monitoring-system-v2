# DESIGN.md

# Thermal Monitoring System v2
## UI / UX Design System

---

# Core Principles

The application is an industrial monitoring system.
The UI must prioritize:

- Reliability
- Readability
- Speed
- Consistency

Do NOT design the application like a consumer application.
Avoid unnecessary animations, gradients, rounded cards, decorative effects, or excessive whitespace.
Every pixel should provide useful information.

---

# General Layout

The application uses a desktop style interface.

Preferred layout:
----------------------------------------------------------
Toolbar
----------------------------------------------------------

Navigation Panel (optional)
Camera Area
Information Panel
Status Bar

----------------------------------------------------------

Navigation remains fixed.
Camera display occupies most of the screen.
Panels should be resizable.

---

# Theme

Default:
Dark Theme
Background:
#1E1E1E
Panels:
#252526
Borders:
#3C3C3C
Text:
#FFFFFF
Secondary Text:
#C8C8C8
Never use bright backgrounds.

---

# Fonts

Use default system fonts.
Preferred:
Segoe UI
Font Sizes
Title:
18
Section Heading:
14
Normal:
10-11
Status Bar:
9
Do not use decorative fonts.

---

# Buttons

Buttons should be rectangular.
Rounded corners:
Maximum 4 px.
Avoid oversized buttons.
Preferred heights:
28-34 px
Primary actions:
Blue
Danger:
Red
Success:
Green
Disabled:
Gray

---

# Icons

Use simple outline icons.
Do not use colorful icons.
Icons should always have labels.

Example
✔ Save
✖ Delete
⚙ Settings

---

# Tables

Use alternating row colors.

Support:
Sorting
Filtering
Resizable columns
Selection highlighting
Tables should fill available space.

---

# Camera View

The camera view is the highest priority component.

Requirements:
Maintain aspect ratio.
Never stretch images.
Support smooth refresh.
Support fullscreen mode.
Support zoom.
Support pan.
Support mouse position.
Support overlays.

---

# Thermal Image

Never modify raw thermal data.
Display images are generated separately.
Color palette should be configurable.

Examples:
Iron
Rainbow
Gray
White Hot
Black Hot
Palette changes must never modify raw data.

---

# ROI Display

ROI outlines only.
Do not fill ROI regions.
Default color:
Yellow
Selected:
Gree
Alarm:
Red
ROI labels should remain readable.
Support hundreds of ROIs.

---

# Alarm Display
Alarm ROIs:
Red outline
Blinking is acceptable.
Alarm list:
Newest alarms at top.
Each alarm shows:
Time
Camera
ROI
Temperature
Threshold
Status

---

# Navigation

Maximum three levels.
Avoid deeply nested menus.
Frequently used actions should be visible.
Do not hide critical functions.

---

# Dialogs
Dialogs should be minimal.
Avoid wizard interfaces.
Confirmation required for:
Delete
Reset
Calibration overwrite
Configuration import

---

# Status Bar
Always visible.
Display:
Connection status
Camera count
FPS
Current user
Current time
System health
Recording status

---

# Logging
Errors should never appear only in console.
Critical errors:
Popup + Log
Warnings:
Status bar + Log
Information:
Status bar

---

# Colors
Normal
Green
Warning
Orange
Alarm
Red
Disconnected
Gray
Selection
Blue
Do not use colors as the only indicator.
Always include text or icons.

---

# Spacing

Margins:
8 px
Panel spacing:
8 px
Control spacing:
4 px
Maintain consistent alignment.

---

# Performance
UI must remain responsive.
Camera rendering must never block UI.
Long-running operations must execute in background threads.
No blocking operations in the GUI thread.

---

# Multi-Camera

Support up to 8 cameras.

Layouts:
1
2
4
6
8
Switching layouts should not interrupt acquisition.

---

# Accessibility

Minimum text contrast:
WCAG AA equivalent.
Support keyboard navigation.
Tooltips required for complex controls.

---

# Configuration
Users should not edit configuration files manually.
Provide configuration dialogs.
Validate all user input.

---

# Error Handling

Always provide actionable messages.
Bad:
Connection Failed
Good:
Camera 3 connection failed.
Verify Ethernet connection and camera power.

---

# Industrial Focus
The operator should understand system status within five seconds of looking at the screen.
Information density is preferred over decorative design.
Consistency is more important than creativity.
When uncertain, prefer the simpler and more functional interface.

---

# AI Agent Rules

When creating or modifying UI:
Follow this document.
Do not introduce new visual styles without updating this design document.
Reuse existing widgets whenever possible.
Maintain consistent spacing, colors, fonts, and interaction patterns.
Favor functionality and clarity over aesthetics.
Never sacrifice performance for visual effects.