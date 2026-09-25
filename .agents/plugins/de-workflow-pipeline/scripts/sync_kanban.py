import os
import re
import json
from datetime import datetime, timezone

def _find_workspace():
    # 1. Search up from current working directory
    cur = os.path.abspath(os.getcwd())
    for _ in range(6):
        if os.path.exists(os.path.join(cur, "docs")) or os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur: break
        cur = parent
    # 2. Search up from script directory
    cur = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        if os.path.exists(os.path.join(cur, "docs")) or os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur: break
        cur = parent
    return os.getcwd()

WORKSPACE_DIR = _find_workspace()
DOCS_DIR = os.path.join(WORKSPACE_DIR, "docs")
EXECUTION_PLAN_PATH = os.path.join(DOCS_DIR, "EXECUTION_PLAN.md")
PRD_PATH = os.path.join(WORKSPACE_DIR, "docs", "prd.md") if os.path.exists(os.path.join(WORKSPACE_DIR, "docs", "prd.md")) else os.path.join(WORKSPACE_DIR, "thin-web-app", "PRD_ARCHITECTURE_REALIGNMENT.md")
ADR_DIR = os.path.join(DOCS_DIR, "adr")
TICKETS_DIR = os.path.join(DOCS_DIR, "tickets")
PLANS_DIR = os.path.join(DOCS_DIR, "plans")
DASHBOARD_DIR = os.path.join(DOCS_DIR, "dashboard")
JSON_OUTPUT_PATH = os.path.join(DASHBOARD_DIR, "kanban-data.json")
HTML_OUTPUT_PATH = os.path.join(DASHBOARD_DIR, "index.html")

def parse_prd_criteria():
    criteria_by_story = {}
    if not os.path.exists(PRD_PATH):
        return criteria_by_story

    with open(PRD_PATH, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    sections = re.split(r'\n###\s+(US-[\d\.]+[^\n]+)', content)
    for i in range(1, len(sections), 2):
        header = sections[i].strip()
        body = sections[i + 1] if i + 1 < len(sections) else ""
        m_id = re.match(r'(US-[\d\.]+)', header)
        if not m_id:
            continue
        story_id = m_id.group(1)

        # Extract acceptance criteria bullets
        bullets = []
        ac_match = re.search(r'\*\*Acceptance criteria:\*\*(.*?)(?=\n\n|\n###|\Z)', body, re.DOTALL)
        if ac_match:
            lines = ac_match.group(1).strip().splitlines()
            for l in lines:
                l_s = l.strip()
                if l_s.startswith("- ") or l_s.startswith("* ") or re.match(r'^\d+\.', l_s):
                    bullets.append(re.sub(r'^[-*\d\.]+\s*', '', l_s))
        else:
            # Check for general bullets in story body
            for l in body.strip().splitlines():
                l_s = l.strip()
                if (l_s.startswith("- ") or l_s.startswith("* ")) and len(bullets) < 5:
                    bullets.append(re.sub(r'^[-*]\s*', '', l_s))

        criteria_by_story[story_id] = {
            "title": header,
            "criteria": bullets
        }
    return criteria_by_story

def parse_adrs():
    adrs = []
    if os.path.exists(ADR_DIR):
        for f in sorted(os.listdir(ADR_DIR)):
            if f.endswith(".md"):
                adr_path = os.path.join(ADR_DIR, f)
                with open(adr_path, "r", encoding="utf-8", errors="replace") as fp:
                    first_line = fp.readline().strip()
                title = re.sub(r'^#\s*', '', first_line) if first_line else f
                adrs.append({
                    "id": f.replace(".md", ""),
                    "title": title,
                    "filename": f,
                    "rel_path": f"docs/adr/{f}"
                })
    return adrs

def parse_execution_plan(criteria_map, adrs):
    if not os.path.exists(EXECUTION_PLAN_PATH):
        return []

    with open(EXECUTION_PLAN_PATH, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    lines = content.splitlines()
    tickets = []
    current_phase = "General"

    table_pattern = re.compile(r'\|\s*([^\s|]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|')

    for line in lines:
        if line.startswith("### Phase "):
            current_phase = line.replace("###", "").strip()
            continue

        m = table_pattern.match(line)
        if m:
            col0, story_raw, status_raw, blocked_raw, touches_raw = [c.strip() for c in m.groups()]
            if "Story" in story_raw or "---" in story_raw:
                continue

            id_match = re.search(r'(US-[\d\.]+)', story_raw)
            if not id_match:
                continue
            story_id = id_match.group(1)
            title = story_raw

            # Normalize status
            norm_status = "todo"
            status_clean = status_raw.upper()
            if "DONE" in status_clean:
                norm_status = "shipped"
            elif "NEXT" in status_clean or "IN PROGRESS" in status_clean:
                norm_status = "implementing"
            elif "BLOCKED" in status_clean:
                norm_status = "blocked_dep"
            elif "PLAN" in status_clean:
                norm_status = "planning"
            elif "VALIDAT" in status_clean:
                norm_status = "validating"
            elif "REVIEW" in status_clean:
                norm_status = "reviewing"
            else:
                norm_status = "todo"

            # Check for linked plan
            plan_file = os.path.join(PLANS_DIR, f"{story_id}-plan.md")
            has_plan = os.path.exists(plan_file)

            # Check for linked ticket doc
            ticket_file = os.path.join(TICKETS_DIR, f"{story_id}.md")
            has_ticket_doc = os.path.exists(ticket_file)

            # Criteria from PRD
            crit_info = criteria_map.get(story_id, {"criteria": []})

            # Blockers
            blockers = []
            if blocked_raw and blocked_raw not in ["—", "-", "None", ""]:
                blockers = [b.strip() for b in blocked_raw.split(",") if b.strip()]

            tickets.append({
                "id": story_id,
                "title": title,
                "phase": current_phase,
                "status": norm_status,
                "raw_status": status_raw,
                "blocked_on": blockers,
                "touches": touches_raw,
                "criteria": crit_info.get("criteria", []),
                "has_plan": has_plan,
                "has_ticket_doc": has_ticket_doc,
                "links": {
                    "spec": "thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md",
                    "plan": f"docs/plans/{story_id}-plan.md" if has_plan else None,
                    "ticket": f"docs/tickets/{story_id}.md" if has_ticket_doc else None,
                    "execution_plan": "docs/EXECUTION_PLAN.md"
                }
            })

    return tickets

def build_kanban_data():
    criteria_map = parse_prd_criteria()
    adrs = parse_adrs()
    tickets = parse_execution_plan(criteria_map, adrs)

    counts = {
        "total": len(tickets),
        "todo": 0,
        "planning": 0,
        "implementing": 0,
        "validating": 0,
        "reviewing": 0,
        "shipped": 0,
        "blocked": 0
    }

    for t in tickets:
        st = t["status"]
        if st in counts:
            counts[st] += 1
        elif "blocked" in st:
            counts["blocked"] += 1
        else:
            counts["todo"] += 1

    percent_done = round((counts["shipped"] / counts["total"] * 100), 1) if counts["total"] > 0 else 0

    data = {
        "project": {
            "name": "data-recon: Portal Architecture Realignment",
            "repo": "data-recon",
            "percent_done": percent_done,
            "metrics": counts,
            "updated_at": datetime.now(timezone.utc).isoformat()
        },
        "documents": [
            {"title": "PRD V2 (ACID Lakehouse & Semantic Layer)", "path": "docs/prd.md", "type": "prd"},
            {"title": "PRD Realignment (V1)", "path": "thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md", "type": "prd"},
            {"title": "Execution Plan", "path": "docs/EXECUTION_PLAN.md", "type": "plan"},
            {"title": "Replica Architecture Guide", "path": "docs/PBI_TO_DUCKLAKE_REPLICA_GUIDE.md", "type": "architecture"},
            {"title": "User Manual", "path": "docs/USER_MANUAL.md", "type": "manual"}
        ],
        "adrs": adrs,
        "tickets": tickets
    }
    return data

def main():
    os.makedirs(DASHBOARD_DIR, exist_ok=True)
    data = build_kanban_data()

    # 1. Write JSON
    with open(JSON_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[OK] Wrote Kanban data: {JSON_OUTPUT_PATH} ({len(data['tickets'])} tickets)", file=sys.stderr)

    # 2. Update inline seed in HTML if exists
    if os.path.exists(HTML_OUTPUT_PATH):
        with open(HTML_OUTPUT_PATH, "r", encoding="utf-8") as f:
            html = f.read()

        seed_json = json.dumps(data)
        replacement = f'<script id="kanban-seed">window.__KANBAN_DATA__ = {seed_json};</script>'
        pattern = re.compile(r'<script id="kanban-seed">.*?</script>', re.DOTALL)
        if pattern.search(html):
            new_html = pattern.sub(lambda m: replacement, html)
            with open(HTML_OUTPUT_PATH, "w", encoding="utf-8") as f:
                f.write(new_html)
            print(f"[OK] Updated inline snapshot in {HTML_OUTPUT_PATH}", file=sys.stderr)

    # Output empty JSON object for Antigravity PostToolUse hook contract
    json.dump({}, sys.stdout)

if __name__ == "__main__":
    main()
