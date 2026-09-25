import sys
import json
import os

def main():
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        input_data = {}

    # Read kanban-data.json if exists
    workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    kanban_json_path = os.path.join(workspace_dir, "docs", "dashboard", "kanban-data.json")

    reason = ""
    should_continue = False

    if os.path.exists(kanban_json_path):
        try:
            with open(kanban_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Check if any ticket is mid-flight in validating without review/ship
            validating_tickets = [t["id"] for t in data.get("tickets", []) if t.get("status") == "validating"]
            if validating_tickets:
                should_continue = True
                reason = f"Ticket(s) {', '.join(validating_tickets)} are in validating status. Complete validation and review before stopping."
        except Exception:
            pass

    if should_continue:
        response = {
            "decision": "continue",
            "reason": reason
        }
    else:
        response = {
            "decision": "allow"
        }

    json.dump(response, sys.stdout)

if __name__ == "__main__":
    main()
