# Asana "Send Wire" automation

Every other Friday at 9am Israel time, this sets **SNA Hourly Payment Status** to
**Send Wire** on your logged hours in Asana (the **Open Hours** section) that are still empty.
It then moves every Send Wire task to the **Send Wire** section and assigns it to Barry.
It runs on GitHub's servers, so your computer can be off.

**To set up your own copy:** click the green **Use this template** button above, then follow
the setup guide your coworker shared with you.

Settings (in your copy: Settings → Secrets and variables → Actions):
- Secret `ASANA_PAT`: your Asana personal access token (required)
- Variable `PROJECT_NAME`: your Asana time clock project's exact name (required)
- Variable `ASSIGNEE`: who gets Send Wire tasks (optional, default Barry; full name or email if needed)
- Variable `ANCHOR_DATE`: a payday Friday as YYYY-MM-DD (optional, default 2026-11-13)
