toggl_to_sp.py — Migrate Toggl Track CSV exports into Super Productivity backup JSON.

Usage:
    python3 toggl_to_sp.py --backup backup.json --csvs toggl1.csv toggl2.csv --output out.json

Design:
  - Every unique (project, description, date) combo → one archive task (isDone=True)
  - Multiple Toggl entries with same project+description+date are MERGED (time accumulates)
  - All tasks go into archiveYoung (history, not live work view)
  - data.timeTracking.project is NOT modified — it tracks live timer sessions, not history
  - Existing SP data (tasks, projects, tags) is preserved
  - IDs are 22-char alphanumeric strings matching SP's own pattern
