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

## Codebase Memory MCP

Before reading source files:

1. Use the codebase-memory MCP to understand the repository structure.
2. Use dependency and call graph queries to locate relevant code.
3. Read only the files required for the task.
4. After modifying code, re-query the graph if additional dependencies may be affected.

Prefer graph queries over full-project searches whenever possible.
