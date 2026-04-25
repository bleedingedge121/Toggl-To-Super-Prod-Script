#!/usr/bin/env python3
import argparse
import csv
import json
import os
import random
import string
import sys
import time
from collections import defaultdict
from datetime import datetime



# ID generation

_ID_CHARS = string.ascii_letters + string.digits + "_-"

def new_id(length: int = 22) -> str:
    return "".join(random.choices(_ID_CHARS, k=length))



# Time helpers

def parse_toggl_datetime(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str.strip()} {time_str.strip()}", "%Y-%m-%d %H:%M:%S")

def to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)

def duration_to_ms(dur_str: str) -> int:
    parts = dur_str.strip().split(":")
    if len(parts) != 3:
        return 0
    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    return (h * 3600 + m * 60 + s) * 1000


 
# CSV loading
 

def load_csv(filepath: str) -> list:
    rows = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("Start date", "").strip():
                continue
            rows.append(row)
    print(f"  Loaded {len(rows)} entries from {os.path.basename(filepath)}")
    return rows


 
# SP entity factories — field-for-field match with real backup schema
 

_PROJECT_THEME = {
    "isAutoContrast": True, "isDisableBackgroundTint": False,
    "primary": "#26c6da", "huePrimary": "500",
    "accent": "#ff4081", "hueAccent": "500",
    "warn": "#e11826", "hueWarn": "500",
    "backgroundImageDark": None, "backgroundImageLight": None,
    "backgroundOverlayOpacity": 20
}
_WORKLOG_CFG = {
    "cols": ["DATE", "START", "END", "TIME_CLOCK", "TITLES_INCLUDING_SUB"],
    "roundWorkTimeTo": None, "roundStartTimeTo": None, "roundEndTimeTo": None,
    "separateTasksBy": " | ", "groupBy": "DATE"
}
_ADVANCED_CFG = {"worklogExportSettings": _WORKLOG_CFG}

_TAG_THEME = {
    "isAutoContrast": True, "isDisableBackgroundTint": True,
    "primary": "#6495ED", "huePrimary": "400",
    "accent": "#ff4081", "hueAccent": "500",
    "warn": "#e11826", "hueWarn": "500",
    "backgroundImageDark": "", "backgroundImageLight": None,
    "backgroundOverlayOpacity": 20
}


def make_project(pid, title, task_ids):
    return {
        "isHiddenFromMenu": False, "isArchived": False, "isEnableBacklog": False,
        "backlogTaskIds": [], "noteIds": [], "advancedCfg": _ADVANCED_CFG,
        "theme": _PROJECT_THEME, "taskIds": task_ids,
        "icon": None, "id": pid, "title": title
    }

def make_tag(tid, title, task_ids, created_ms):
    return {
        "color": None, "created": created_ms, "advancedCfg": _ADVANCED_CFG,
        "theme": _TAG_THEME, "taskIds": task_ids,
        "icon": None, "id": tid, "title": title
    }

def make_archive_task(task_id, title, project_id, tag_ids,
                      time_spent_on_day, time_spent, created_ms, done_on_ms):
    return {
        "id": task_id, "subTaskIds": [], "timeSpentOnDay": time_spent_on_day,
        "timeSpent": time_spent, "timeEstimate": 0, "isDone": True,
        "title": title, "tagIds": tag_ids, "created": created_ms,
        "attachments": [], "projectId": project_id,
        "doneOn": done_on_ms, "modified": done_on_ms, "subTasks": []
    }


 
# Migration
 

def migrate(backup_path, csv_paths, output_path):
    print(f"\nLoading base backup: {backup_path}")
    with open(backup_path, encoding="utf-8") as f:
        sp = json.load(f)

    d = sp["data"]
    now_ms = int(time.time() * 1000)

    # Ensure archiveYoung structure
    if "archiveYoung" not in d:
        d["archiveYoung"] = {
            "task": {"ids": [], "entities": {}},
            "timeTracking": {"project": {}, "tag": {}},
            "lastTimeTrackingFlush": 0, "lastFlush": 0
        }
    ay = d["archiveYoung"]
    if "task" not in ay:
        ay["task"] = {"ids": [], "entities": {}}


    all_rows = []
    for path in csv_paths:
        print(f"Reading CSV: {path}")
        all_rows.extend(load_csv(path))
    print(f"\nTotal Toggl entries: {len(all_rows)}")

    existing_projects = {}   # title.lower() → id
    for pid, proj in d["project"]["entities"].items():
        existing_projects[proj["title"].strip().lower()] = pid

    existing_tags = {}        # title.lower() → id
    for tid, tag in d["tag"]["entities"].items():
        existing_tags[tag["title"].strip().lower()] = tid

    # Aggregate rows: (project_lower, desc_lower, date_str) → merged entry
    agg = {}
    for row in all_rows:
        project_name = (row.get("Project") or "Inbox").strip() or "Inbox"
        description  = (row.get("Description") or row.get("Task") or "Untitled").strip() or "Untitled"
        start_date   = row.get("Start date", "").strip()
        start_time   = row.get("Start time", "").strip()
        end_date     = row.get("End date", "").strip()
        end_time     = row.get("End time", "").strip()
        duration_str = row.get("Duration", "0:00:00").strip()
        tags_raw     = row.get("Tags", "").strip()

        if not start_date:
            continue

        try:
            start_dt = parse_toggl_datetime(start_date, start_time)
            end_dt   = parse_toggl_datetime(end_date, end_time)
            start_ms = to_ms(start_dt)
            end_ms   = to_ms(end_dt)
        except Exception as e:
            print(f"  SKIP row (bad datetime): {e}", file=sys.stderr)
            continue

        dur_ms = duration_to_ms(duration_str)
        if dur_ms == 0:
            dur_ms = max(0, end_ms - start_ms)

        tags = {t.strip() for t in tags_raw.split(",") if t.strip()} if tags_raw else set()

        key = (project_name.lower(), description.lower(), start_date)
        if key not in agg:
            agg[key] = {
                "project_name": project_name,
                "description":  description,
                "date_str":     start_date,
                "start_ms":     start_ms,
                "end_ms":       end_ms,
                "duration_ms":  dur_ms,
                "tags":         tags,
                "created_ms":   start_ms,
            }
        else:
            agg[key]["duration_ms"] += dur_ms
            agg[key]["start_ms"]     = min(agg[key]["start_ms"], start_ms)
            agg[key]["end_ms"]       = max(agg[key]["end_ms"], end_ms)
            agg[key]["tags"].update(tags)

    print(f"Unique (project, description, date) combos after merge: {len(agg)}")

    # Lazy project/tag creators
    new_projects = {}   # name_lower → {id, title, task_ids:[]}
    new_tags     = {}   # name_lower → {id, title, task_ids:[], created_ms}

    def get_or_create_project_id(project_name):
        key = project_name.strip().lower()
        if key in existing_projects:
            return existing_projects[key]
        if key not in new_projects:
            new_projects[key] = {"id": new_id(), "title": project_name.strip(), "task_ids": []}
        return new_projects[key]["id"]

    def get_or_create_tag_id(tag_name, created_ms):
        key = tag_name.strip().lower()
        if key in existing_tags:
            return existing_tags[key]
        if key not in new_tags:
            new_tags[key] = {"id": new_id(), "title": tag_name.strip(), "task_ids": [], "created_ms": created_ms}
        return new_tags[key]["id"]

    # Build tasks — generate all IDs up front so tag/project registration is clean
    new_archive_tasks = []
    entry_to_task_id  = {}   # agg key → task_id (for use in inject phase)

    for key, entry in agg.items():
        project_name = entry["project_name"]
        description  = entry["description"]
        date_str     = entry["date_str"]
        dur_ms       = entry["duration_ms"]
        end_ms       = entry["end_ms"]
        created_ms   = entry["created_ms"]

        pid     = get_or_create_project_id(project_name)
        tag_ids = [get_or_create_tag_id(t, created_ms) for t in sorted(entry["tags"])]
        task_id = new_id()
        entry_to_task_id[key] = task_id

        # Register task_id in new_projects task list
        pkey = project_name.strip().lower()
        if pkey in new_projects:
            new_projects[pkey]["task_ids"].append(task_id)

        # Register task_id in new_tags task list
        for tid_tag in tag_ids:
            for k, v in new_tags.items():
                if v["id"] == tid_tag:
                    v["task_ids"].append(task_id)

        new_archive_tasks.append(
            make_archive_task(
                task_id=task_id, title=description, project_id=pid,
                tag_ids=tag_ids, time_spent_on_day={date_str: dur_ms},
                time_spent=dur_ms, created_ms=created_ms, done_on_ms=end_ms,
            )
        )

    print(f"Archive tasks to inject: {len(new_archive_tasks)}")

    # ---- Inject new projects ----
    for key, np in new_projects.items():
        pid = np["id"]
        d["project"]["entities"][pid] = make_project(pid, np["title"], np["task_ids"])
        if pid not in d["project"]["ids"]:
            d["project"]["ids"].append(pid)
        d["menuTree"]["projectTree"].append({"k": "p", "id": pid, "projectId": pid})
        print(f"  + Project: '{np['title']}' [{pid}]")

    # ---- Append task_ids to existing projects ----
    for key, entry in agg.items():
        pkey = entry["project_name"].strip().lower()
        if pkey in existing_projects:
            pid     = existing_projects[pkey]
            task_id = entry_to_task_id[key]
            d["project"]["entities"][pid]["taskIds"].append(task_id)

    # ---- Inject new tags ----
    for key, nt in new_tags.items():
        tid = nt["id"]
        d["tag"]["entities"][tid] = make_tag(tid, nt["title"], nt["task_ids"], nt["created_ms"])
        if tid not in d["tag"]["ids"]:
            d["tag"]["ids"].append(tid)
        print(f"  + Tag: '{nt['title']}' [{tid}]")

    # ---- Append task_ids to existing tags ----
    for key, entry in agg.items():
        task_id = entry_to_task_id[key]
        for tag_name in entry["tags"]:
            tkey = tag_name.strip().lower()
            if tkey in existing_tags:
                tid = existing_tags[tkey]
                if task_id not in d["tag"]["entities"][tid]["taskIds"]:
                    d["tag"]["entities"][tid]["taskIds"].append(task_id)

    # ---- Inject archive tasks ----
    for task in new_archive_tasks:
        ay["task"]["entities"][task["id"]] = task
        if task["id"] not in ay["task"]["ids"]:
            ay["task"]["ids"].append(task["id"])

    # NOTE: data.timeTracking.project is intentionally NOT modified.
    # That field stores live timer SESSION spans (wall-clock s/e) used by SP's
    # session tracker display. Injecting historical Toggl timestamps there
    # causes SP to show huge identical totals for every project (the span from
    # the earliest to latest Toggl entry covers months of epoch time).
    # SP computes project time totals by summing task.timeSpentOnDay across all
    # tasks with matching projectId — our archive tasks carry the correct values.

    sp["lastUpdate"] = now_ms
    sp["timestamp"]  = now_ms

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sp, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(output_path) / 1024
    print(f"\n Done! Output: {output_path} ({size_kb:.1f} KB)")
    print(f"   Projects injected : {len(new_projects)}")
    print(f"   Tags injected     : {len(new_tags)}")
    print(f"   Tasks (archive)   : {len(new_archive_tasks)}")


 
# CLI
 

def main():
    parser = argparse.ArgumentParser(
        description="Migrate Toggl Track CSV exports into a Super Productivity backup JSON."
    )
    parser.add_argument("--backup", required=True,
        help="Path to existing SP backup JSON (used as base)")
    parser.add_argument("--csvs", nargs="+", required=True,
        help="One or more Toggl Track CSV export files")
    parser.add_argument("--output", default="sp_migrated.json",
        help="Output file path (default: sp_migrated.json)")
    args = parser.parse_args()

    for f in [args.backup] + args.csvs:
        if not os.path.isfile(f):
            print(f"ERROR: File not found: {f}", file=sys.stderr)
            sys.exit(1)

    migrate(args.backup, args.csvs, args.output)

if __name__ == "__main__":
    main()
