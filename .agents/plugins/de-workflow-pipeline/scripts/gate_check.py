import sys
import json
import re

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    tool_call = data.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args", {})
    command_line = args.get("CommandLine", "")

    # Check for git push, gh pr create, or git commit
    if re.search(r'\b(git\s+push|gh\s+pr\s+create)\b', command_line, re.IGNORECASE):
        response = {
            "decision": "force_ask",
            "reason": "Ship Gate Checkpoint: Manual user confirmation required before pushing code or opening a PR."
        }
    else:
        response = {
            "decision": "allow"
        }

    json.dump(response, sys.stdout)

if __name__ == "__main__":
    main()
