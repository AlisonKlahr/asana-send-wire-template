"""
Every pay period: in your Asana time clock project (PROJECT_NAME), find logged-hours tasks
in the "Open Hours" section whose "SNA Hourly Payment Status" is empty, set it
to "Send Wire", then move every "Send Wire" task to the "Send Wire" section and
assign it to Barry.

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
WIRE_SECTION_NAME = os.environ.get("WIRE_SECTION") or "Send Wire"   # where Send Wire tasks are moved
ASSIGNEE = (os.environ.get("ASSIGNEE") or "Barry").strip()          # first name, full name or email
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
                return p["gid"], ws["gid"]
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


def find_section(sections, name):
    sec = next((s for s in sections if s["name"].strip().lower() == name.lower()), None)
    if not sec:
        sys.exit(f'Could not find section "{name}".')
    return sec


def find_assignee(workspace):
    want = ASSIGNEE.lower()
    users = get_all(f"/workspaces/{workspace}/users", {"opt_fields": "name,email"})
    if "@" in want:
        matches = [u for u in users if (u.get("email") or "").lower() == want]
    else:
        matches = [u for u in users if (u.get("name") or "").strip().lower() == want] or                   [u for u in users if (u.get("name") or "").strip().lower().split(" ")[0] == want]
    if len(matches) != 1:
        names = ", ".join(u["name"] for u in matches) or "nobody"
        sys.exit(f'ASSIGNEE "{ASSIGNEE}" matched {names}. Set the ASSIGNEE variable '
                 f"to that person's full name or email.")
    return matches[0]


def main():
    dry = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "true"
    if is_off_week():
        log("off week, nothing to do")
        return
    project, workspace = find_project()

    sections = get_all(f"/projects/{project}/sections")
    section = find_section(sections, SECTION_NAME)
    wire_section = find_section(sections, WIRE_SECTION_NAME)
    assignee = find_assignee(workspace)

    fields = "name,completed,assignee.name,custom_fields.name,custom_fields.enum_value.name,"              "custom_fields.enum_options.name"
    tasks = get_all(f"/sections/{section['gid']}/tasks", {"opt_fields": fields})

    marked = moved = 0
    for t in tasks:
        name = (t.get("name") or "").strip()
        if not name:
            continue  # blank placeholder row
        field = next((f for f in t.get("custom_fields", [])
                      if (f.get("name") or "").lower().startswith(FIELD_NAME_STARTS_WITH.lower())), None)
        if not field:
            sys.exit(f'Field starting with "{FIELD_NAME_STARTS_WITH}" not found on tasks.')
        status = (field.get("enum_value") or {}).get("name", "")

        if not status:
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
            marked += 1
            status = OPTION_NAME

        if status.strip().lower() != OPTION_NAME.lower():
            continue  # some other status (e.g. already paid): leave it
        if dry:
            log(f'[dry run] would move {name} to "{wire_section["name"]}" '
                f'and assign to {assignee["name"]}')
        else:
            call("POST", f"/sections/{wire_section['gid']}/addTask", body={"task": t["gid"]})
            call("PUT", f"/tasks/{t['gid']}", body={"assignee": assignee["gid"]})
            log(f'moved {name} to "{wire_section["name"]}", assigned to {assignee["name"]}')
        moved += 1

    w = "would be " if dry else ""
    log(f"done: {marked} task(s) {w}marked {OPTION_NAME}, {moved} {w}moved and assigned")


if __name__ == "__main__":
    TOKEN = os.environ.get("ASANA_PAT")
    if not TOKEN:
        sys.exit("Missing ASANA_PAT: add your Asana token as a repository secret named ASANA_PAT.")
    if not PROJECT_NAME:
        sys.exit("Missing PROJECT_NAME: add a repository variable named PROJECT_NAME "
                 "with your Asana project's exact name.")
    main()
