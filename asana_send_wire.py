"""
Every pay period: in the Asana project "Aliza Time Clock", find logged-hours tasks
in the "Open Hours" section whose "SNA Hourly Payment Status" is empty, and set it
to "Send Wire".

Setup: ASANA_PAT (your Asana token) and PROJECT_NAME (your project name) environment variables.
Run:   python asana_send_wire.py --dry-run   (shows what would change, changes nothing)
       python asana_send_wire.py             (makes the changes)
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

PROJECT_NAME = os.environ.get("PROJECT_NAME", "").strip()   # your time clock project, e.g. "Dana Time Clock"
SECTION_NAME = os.environ.get("SECTION_NAME") or "Open Hours"
FIELD_NAME_STARTS_WITH = os.environ.get("FIELD_NAME") or "SNA Hourly"   # matches "SNA Hourly Payment Status"
OPTION_NAME = os.environ.get("OPTION_NAME") or "Send Wire"
SKIP_TODAY_AND_LATER = True             # don't mark a day that's still being logged

API = "https://app.asana.com/api/1.0"
LOG_FILE = Path(__file__).with_name("asana_send_wire.log")


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def call(method, path, params=None, body=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps({"data": body}).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get_all(path, params=None):
    params = dict(params or {}, limit=100)
    out = []
    while True:
        resp = call("GET", path, params)
        out.extend(resp["data"])
        nxt = resp.get("next_page")
        if not nxt:
            return out
        params["offset"] = nxt["offset"]


def parse_date(name):
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return datetime.strptime(name.strip(), fmt).date()
        except ValueError:
            pass
    return None


def find_project():
    me = call("GET", "/users/me", {"opt_fields": "workspaces.name"})["data"]
    for ws in me["workspaces"]:
        for p in get_all("/projects", {"workspace": ws["gid"], "archived": "false"}):
            if p["name"].strip().lower() == PROJECT_NAME.lower():
                return p["gid"]
    sys.exit(f'Could not find project "{PROJECT_NAME}".')


def is_off_week():
    """The scheduler fires weekly; only act every other week counting from ANCHOR_DATE."""
    anchor = os.environ.get("ANCHOR_DATE")  # e.g. 2026-11-13, a payday
    if os.environ.get("FORCE_RUN") == "true":
        return False
    # GitHub only schedules in UTC, so it fires at two UTC hours; act only in the
    # one that is RUN_AT_HOUR local time (handles Israel's summer/winter clock change).
    hour = os.environ.get("RUN_AT_HOUR")
    if hour and datetime.now().hour != int(hour):
        return True
    if not anchor:
        return False
    weeks = (date.today() - date.fromisoformat(anchor)).days // 7
    return weeks % 2 != 0


def main():
    dry = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "true"
    if is_off_week():
        log("off week, nothing to do")
        return
    project = find_project()

    section = next((s for s in get_all(f"/projects/{project}/sections")
                    if s["name"].strip().lower() == SECTION_NAME.lower()), None)
    if not section:
        sys.exit(f'Could not find section "{SECTION_NAME}".')

    fields = "name,completed,custom_fields.name,custom_fields.enum_value.name," \
             "custom_fields.enum_options.name"
    tasks = get_all(f"/sections/{section['gid']}/tasks", {"opt_fields": fields})

    changed = 0
    for t in tasks:
        name = (t.get("name") or "").strip()
        if not name:
            continue  # blank placeholder row
        field = next((f for f in t.get("custom_fields", [])
                      if (f.get("name") or "").lower().startswith(FIELD_NAME_STARTS_WITH.lower())), None)
        if not field:
            sys.exit(f'Field starting with "{FIELD_NAME_STARTS_WITH}" not found on tasks.')
        if field.get("enum_value"):
            continue  # already has a status
        d = parse_date(name)
        if SKIP_TODAY_AND_LATER and d and d >= date.today():
            log(f"skip {name} (today or later, may still be logging)")
            continue
        option = next((o for o in field.get("enum_options", [])
                       if o["name"].strip().lower() == OPTION_NAME.lower()), None)
        if not option:
            sys.exit(f'Option "{OPTION_NAME}" not found in field "{field["name"]}".')

        if dry:
            log(f"[dry run] would set {name} -> {OPTION_NAME}")
        else:
            call("PUT", f"/tasks/{t['gid']}",
                 body={"custom_fields": {field["gid"]: option["gid"]}})
            log(f"set {name} -> {OPTION_NAME}")
        changed += 1

    log(f"done: {changed} task(s) {'would be ' if dry else ''}updated")


if __name__ == "__main__":
    TOKEN = os.environ.get("ASANA_PAT")
    if not TOKEN:
        sys.exit("Missing ASANA_PAT: add your Asana token as a repository secret named ASANA_PAT.")
    if not PROJECT_NAME:
        sys.exit("Missing PROJECT_NAME: add a repository variable named PROJECT_NAME "
                 "with your Asana project's exact name.")
    main()
