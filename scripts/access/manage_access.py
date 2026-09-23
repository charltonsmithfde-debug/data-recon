#!/usr/bin/env python3
"""Add, remove and inspect the people in `thin-web-app/role_assignments.json`.

WHY THIS EXISTS
---------------
The roster is the single answer to two separate questions that were previously answered in two
separate places:

  * "what may this person SEE?"   -> `role` + `can_view_pii`, read per request by
                                     server.py:load_role_assignments / resolve_identity.
  * "what may this person REACH?" -> `groups`, read by scripts/blocked/09_apply_access.sh,
                                     which turns them into GCP IAM bindings.

server.py ignores `groups` and `note` -- it only ever reads `role` and `can_view_pii` -- so the
two consumers cannot drift apart the way a roster file plus a separate IAM list would.

Editing the JSON by hand still works. This tool exists because several of the constraints on it
are invisible in the file: an unrecognised role is a SILENT demotion rather than an error, one
address must never be mapped, can_view_pii means nothing outside one role, and the executive
role must never be held by a service account. All of them are checked here, and again in
thin-web-app/tests/.

USAGE
-----
  python scripts/access/manage_access.py list
  python scripts/access/manage_access.py roles
  python scripts/access/manage_access.py show someone@sanlam.co.za
  python scripts/access/manage_access.py add someone@sanlam.co.za --role=ROLE_INVESTMENTS
  python scripts/access/manage_access.py add boss@sanlam.co.za --role=EXEC --allow-pii \
      --group=sys_admin
  python scripts/access/manage_access.py set-role someone@sanlam.co.za --role=ROLE_ANNUITY
  python scripts/access/manage_access.py group someone@sanlam.co.za --add=sql_analyst
  python scripts/access/manage_access.py remove someone@sanlam.co.za
  python scripts/access/manage_access.py check
  python scripts/access/manage_access.py principals --group=metabase

Every mutating command prints the change and writes the file. Nothing here touches GCP: a
change only reaches the cloud when scripts/blocked/09_apply_access.sh (IAM) and
scripts/blocked/07_deploy_thin_web.sh (the app image) are run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent                      # data-recon/
ROSTER = REPO_ROOT / "thin-web-app" / "role_assignments.json"

# Kept in step with server.py:KNOWN_ROLES and cube/cube.js:ROLE_PERMISSIONS. `check` proves the
# first of those rather than trusting this copy.
LEAST_PRIVILEGED_ROLE = "ROLE_FINANCE_MEMBER"
EXEC_ROLE = "ROLE_EXECUTIVE" + "_ALL"
ROLES = {
    EXEC_ROLE: "every cube, PII in the clear -- the only role that sees an unmasked member",
    "ROLE_FINANCE_MEMBER": "member measures and flows, PII masked (the fallback)",
    "ROLE_DIGITAL_OPERATIONS": "portal metrics -- no cube defined yet (US-4.5)",
    "ROLE_INVESTMENTS": "investment products and market values",
    "ROLE_ANNUITY": "annuity quotations",
}
# Shorthands, so nobody has to remember whether it is _ALL or _FULL.
ROLE_ALIASES = {
    "EXEC": EXEC_ROLE, "EXECUTIVE": EXEC_ROLE, "ALL": EXEC_ROLE,
    "FINANCE": "ROLE_FINANCE_MEMBER", "MEMBER": "ROLE_FINANCE_MEMBER",
    "DIGITAL": "ROLE_DIGITAL_OPERATIONS", "OPS": "ROLE_DIGITAL_OPERATIONS",
    "INVEST": "ROLE_INVESTMENTS", "INVESTMENTS": "ROLE_INVESTMENTS",
    "ANNUITY": "ROLE_ANNUITY",
}

# What a group REACHES. Expanded by 09_apply_access.sh into IAM bindings; `sys_admin` implies
# the other three, so "the sys-admin gets Metabase and scbi-cube" is true by construction and
# not by remembering to tick three boxes.
GROUPS = {
    "portal":      "the thin web app (roles/iap.httpsResourceAccessor on scbi-thin-web)",
    "metabase":    "Metabase (roles/run.invoker on scbi-metabase)",
    "sql_analyst": "an IAP tunnel to Cube SQL on 5432 (tunnelResourceAccessor + compute.viewer)",
    "sys_admin":   "all of the above, plus the Cube REST API by hand "
                   "(roles/run.invoker on scbi-cube)",
}
GROUP_IMPLIES = {"sys_admin": ("portal", "metabase", "sql_analyst", "cube_rest")}
# Not selectable on its own: calling the Cube REST API by hand is a sys-admin act, and the
# service account that does it per request is granted by 05, not from this roster.
DERIVED_GROUPS = ("cube_rest",)

# tests/conftest.py:40 mints the suite's IAP assertions as this address and the US-1.2 tests
# assert it falls back to least privilege. Mapping it turns them red.
RESERVED_EMAILS = {"test.user@sanlam.co.za"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ──────────────────────────────────────────────────────────────────────────────
# Load / save
# ──────────────────────────────────────────────────────────────────────────────

def die(message):
    print("\nABORT: " + message + "\n", file=sys.stderr)
    raise SystemExit(1)


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"{path} is not valid JSON ({exc}).\n"
            "       server.py SWALLOWS that error and falls back to least privilege for every\n"
            "       caller, so a broken roster deploys silently wrong. Fix it before anything\n"
            "       else.")
    if not isinstance(data, dict):
        die(f"{path} must hold a JSON object keyed by email, not {type(data).__name__}.")
    return data


def save(path: Path, data: dict) -> None:
    ordered = {email: data[email] for email in sorted(data)}
    path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Validation -- the constraints the file cannot state about itself
# ──────────────────────────────────────────────────────────────────────────────

def normalise_role(raw: str) -> str:
    key = raw.strip().upper()
    role = ROLE_ALIASES.get(key, key)
    if role not in ROLES:
        die(f"'{raw}' is not a role.\n"
            f"       Known: {', '.join(sorted(ROLES))}\n"
            "       An unrecognised role is not an error at runtime -- server.py demotes it to\n"
            f"       {LEAST_PRIVILEGED_ROLE} without a message anywhere, so a typo costs\n"
            "       someone access silently.")
    return role


def normalise_groups(raw) -> list:
    out = []
    for item in raw or []:
        for part in item.replace(",", " ").split():
            name = part.strip().lower()
            if name in DERIVED_GROUPS:
                die(f"'{name}' is derived, not assignable -- it comes with sys_admin.")
            if name not in GROUPS:
                die(f"'{name}' is not a group. Known: {', '.join(GROUPS)}")
            if name not in out:
                out.append(name)
    return out


def expand_groups(groups) -> set:
    """A person's effective reach, with sys_admin's implications applied."""
    effective = set(groups or [])
    for group in list(effective):
        effective.update(GROUP_IMPLIES.get(group, ()))
    return effective


def validate(data: dict) -> list:
    """Every problem in the roster, as a list. Empty means it is sound."""
    problems = []
    for email, entry in data.items():
        where = f"{email}:"
        if not EMAIL_RE.match(email):
            problems.append(f"{where} not an email address. The key must be the address IAP "
                            "asserts, exactly.")
        if email in RESERVED_EMAILS:
            problems.append(f"{where} reserved by the test suite (tests/conftest.py). Mapping "
                            "it turns the US-1.2 least-privilege tests red.")
        if not isinstance(entry, dict):
            problems.append(f"{where} must be an object, not {type(entry).__name__}.")
            continue

        role = entry.get("role")
        if role is None:
            problems.append(f"{where} no role, so the caller silently gets "
                            f"{LEAST_PRIVILEGED_ROLE}.")
        elif role not in ROLES:
            problems.append(f"{where} '{role}' is not a known role -- server.py demotes it to "
                            f"{LEAST_PRIVILEGED_ROLE} without saying so.")
        elif role == EXEC_ROLE and email.endswith(".gserviceaccount.com"):
            problems.append(f"{where} a service account may not hold {EXEC_ROLE}. It is the "
                            "only role with PII in the clear, and a shared non-human credential "
                            "holding it defeats every mask in SharedDimensions.js.")

        pii = entry.get("can_view_pii", False)
        if not isinstance(pii, bool):
            problems.append(f"{where} can_view_pii must be true or false, not "
                            f"{type(pii).__name__} -- anything else reads as false.")
        elif pii and role != EXEC_ROLE:
            problems.append(f"{where} can_view_pii is true but the role is {role}, whose "
                            "cube.js definition sets canViewPii false. cube.js wins, so this "
                            "line grants nothing and misleads the next reader.")

        groups = entry.get("groups", [])
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            problems.append(f"{where} groups must be a list of strings.")
        else:
            for group in groups:
                if group not in GROUPS:
                    problems.append(f"{where} '{group}' is not a group. "
                                    f"Known: {', '.join(GROUPS)}")
    return problems


def check_roles_match_the_server() -> list:
    """This file's copy of the role list against server.py's. A role added there and not here
    would be refused by `add` for no reason a reader could see."""
    server = REPO_ROOT / "thin-web-app" / "server.py"
    try:
        text = server.read_text(encoding="utf-8")
    except OSError:
        return [f"could not read {server} to confirm the role list"]
    match = re.search(r"KNOWN_ROLES\s*=\s*\(([^)]*)\)", text, re.S)
    if not match:
        return ["could not find KNOWN_ROLES in server.py -- the role list here is unverified"]
    declared = set(re.findall(r'"([A-Z_]+)"', match.group(1)))
    problems = []
    for missing in sorted(declared - set(ROLES)):
        problems.append(f"server.py knows {missing} and this tool does not -- add it to ROLES.")
    for extra in sorted(set(ROLES) - declared):
        problems.append(f"this tool offers {extra} and server.py does not -- giving it to "
                        "anyone would be a silent demotion.")
    return problems


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────

def describe(email: str, entry: dict) -> str:
    groups = entry.get("groups", []) or []
    reach = sorted(expand_groups(groups)) or ["(nothing beyond the portal sign-in)"]
    pii = "PII IN THE CLEAR" if entry.get("can_view_pii") else "PII masked"
    role = entry.get("role") or f"(none -> {LEAST_PRIVILEGED_ROLE})"
    lines = [f"  {email}",
             f"      role   {role}  [{pii}]",
             f"      groups {', '.join(groups) or '(none)'}",
             f"      reach  {', '.join(reach)}"]
    if entry.get("note"):
        lines.append(f"      note   {entry['note']}")
    return "\n".join(lines)


def print_next_steps(iam_only: bool = False) -> None:
    print("  Nothing has changed in GCP yet. To make it real:")
    print("    python scripts/access/manage_access.py check")
    if not iam_only:
        print("    (cd thin-web-app && python -m pytest -q)")
        print("    ./scripts/blocked/07_deploy_thin_web.sh      (the roster is baked into the "
              "image)")
    print("    ./scripts/blocked/09_apply_access.sh --dry-run   (then again without it)\n")


def cmd_list(args, data):
    if not data:
        print("\n  Nobody is mapped. Every verified caller falls back to "
              f"{LEAST_PRIVILEGED_ROLE} with PII masked.\n")
        return 0
    print(f"\n  {len(data)} person(s) in {args.file}\n")
    for email in sorted(data):
        print(describe(email, data[email]))
        print()
    return 0


def cmd_show(args, data):
    entry = data.get(args.email.strip().lower())
    if entry is None:
        print(f"\n  {args.email} is not mapped -- they resolve to {LEAST_PRIVILEGED_ROLE}, "
              "PII masked.\n")
        return 1
    print()
    print(describe(args.email.strip().lower(), entry))
    print()
    return 0


def cmd_add(args, data):
    email = args.email.strip().lower()
    role = normalise_role(args.role)
    groups = normalise_groups(args.group)
    if email in RESERVED_EMAILS:
        die(f"{email} is reserved by the test suite and must stay unmapped.")
    if not EMAIL_RE.match(email):
        die(f"'{email}' is not an email address. The key must be exactly what IAP asserts.")
    if email in data and not args.force:
        die(f"{email} is already mapped. Use --force to overwrite, or `set-role` / `group` to "
            "change one field.")
    if args.allow_pii and role != EXEC_ROLE:
        die(f"--allow-pii with {role} grants nothing: cube.js sets canViewPii false for it, and "
            f"cube.js wins. Only {EXEC_ROLE} sees PII.")
    if email.endswith(".gserviceaccount.com") and role == EXEC_ROLE:
        die(f"a service account may not hold {EXEC_ROLE} -- see docs/METABASE_CUBE_SQL.md for "
            "the one-connection-per-role-domain shape instead.")
    if role == EXEC_ROLE and not args.allow_pii:
        print(f"\n  NOTE: {EXEC_ROLE} reaches every cube, but PII stays masked until you pass\n"
              "        --allow-pii as well. That split is deliberate: the role is the scope and\n"
              "        can_view_pii is the POPIA decision, and they are not one approval.\n")

    entry = {"role": role, "can_view_pii": bool(args.allow_pii)}
    if groups:
        entry["groups"] = groups
    if args.note:
        entry["note"] = args.note
    data[email] = entry
    save(args.file, data)
    print("\n  added:\n")
    print(describe(email, entry))
    print()
    print_next_steps()
    return 0


def cmd_set_role(args, data):
    email = args.email.strip().lower()
    if email not in data:
        die(f"{email} is not mapped. Use `add`.")
    role = normalise_role(args.role)
    before = data[email].get("role")
    data[email]["role"] = role
    if args.allow_pii is not None:
        if args.allow_pii and role != EXEC_ROLE:
            die(f"--allow-pii with {role} grants nothing -- cube.js sets canViewPii false "
                "for it.")
        data[email]["can_view_pii"] = args.allow_pii
    if role != EXEC_ROLE and data[email].get("can_view_pii"):
        data[email]["can_view_pii"] = False
        print(f"\n  can_view_pii forced to false: {role} does not see PII in cube.js.")
    save(args.file, data)
    print(f"\n  {email}: {before} -> {role}\n")
    print(describe(email, data[email]))
    print()
    print_next_steps()
    return 0


def cmd_group(args, data):
    email = args.email.strip().lower()
    if email not in data:
        die(f"{email} is not mapped. Use `add` first -- reaching a service is only meaningful "
            "once the person has a data role.")
    groups = list(data[email].get("groups", []))
    for name in normalise_groups(args.add):
        if name not in groups:
            groups.append(name)
    for name in normalise_groups(args.remove):
        if name in groups:
            groups.remove(name)
    if groups:
        data[email]["groups"] = groups
    else:
        data[email].pop("groups", None)
    save(args.file, data)
    print()
    print(describe(email, data[email]))
    print()
    print_next_steps(iam_only=True)
    return 0


def cmd_remove(args, data):
    email = args.email.strip().lower()
    if email not in data:
        die(f"{email} is not mapped -- nothing to remove.")
    entry = data.pop(email)
    save(args.file, data)
    print(f"\n  removed {email} ({entry.get('role')}). They now resolve to "
          f"{LEAST_PRIVILEGED_ROLE} with PII masked.\n")
    print("  This does NOT revoke their GCP access on its own. Run:")
    print("    ./scripts/blocked/09_apply_access.sh --prune   (revokes what the roster no "
          "longer justifies)")
    print("    ./scripts/blocked/07_deploy_thin_web.sh        (ships the new roster)\n")
    return 0


def cmd_check(args, data):
    problems = validate(data) + check_roles_match_the_server()
    print()
    if problems:
        print(f"  {len(problems)} problem(s) in {args.file}:\n")
        for problem in problems:
            print(f"    - {problem}")
        print()
        return 1
    print(f"  {args.file}: {len(data)} person(s), sound.\n")
    return 0


def cmd_principals(args, data):
    """IAM principals for one group, one per line. The machine-readable seam 09 consumes."""
    wanted = args.group.strip().lower()
    if wanted not in GROUPS and wanted not in DERIVED_GROUPS:
        die(f"'{wanted}' is not a group. Known: {', '.join(list(GROUPS) + list(DERIVED_GROUPS))}")
    for email in sorted(data):
        entry = data[email]
        if not isinstance(entry, dict):
            continue
        if wanted in expand_groups(entry.get("groups", [])):
            prefix = "serviceAccount" if email.endswith(".gserviceaccount.com") else "user"
            print(f"{prefix}:{email}")
    return 0


def cmd_roles(args, data):
    print("\n  Data roles -- what a person SEES. Exactly one per person.\n")
    for role, description in ROLES.items():
        print(f"    {role:<26} {description}")
    print("\n  Access groups -- what a person REACHES. Any number; sys_admin implies the rest.\n")
    for group, description in GROUPS.items():
        print(f"    {group:<26} {description}")
    print()
    return 0


# ──────────────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Manage who may see and reach the SCBI recon portal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__[__doc__.index("USAGE"):])
    parser.add_argument("--file", type=Path, default=ROSTER,
                        help="roster to operate on (default: thin-web-app/role_assignments.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="everyone in the roster").set_defaults(func=cmd_list)
    sub.add_parser("roles", help="the roles and groups, and what each reaches").set_defaults(
        func=cmd_roles)
    sub.add_parser("check", help="validate the roster").set_defaults(func=cmd_check)

    p = sub.add_parser("show", help="one person")
    p.add_argument("email")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("add", help="map a person to a role")
    p.add_argument("email")
    p.add_argument("--role", required=True, help="one of: " + ", ".join(sorted(ROLES)))
    p.add_argument("--group", action="append", help="repeatable: " + ", ".join(GROUPS))
    p.add_argument("--allow-pii", action="store_true",
                   help="see PII unmasked -- the executive role only")
    p.add_argument("--note", help="why this person has this access")
    p.add_argument("--force", action="store_true", help="overwrite an existing entry")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("set-role", help="change someone's data role")
    p.add_argument("email")
    p.add_argument("--role", required=True)
    pii = p.add_mutually_exclusive_group()
    pii.add_argument("--allow-pii", dest="allow_pii", action="store_true", default=None)
    pii.add_argument("--mask-pii", dest="allow_pii", action="store_false")
    p.set_defaults(func=cmd_set_role)

    p = sub.add_parser("group", help="change what someone can reach")
    p.add_argument("email")
    p.add_argument("--add", action="append", help="repeatable: " + ", ".join(GROUPS))
    p.add_argument("--remove", action="append", help="repeatable")
    p.set_defaults(func=cmd_group)

    p = sub.add_parser("remove", help="unmap a person")
    p.add_argument("email")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("principals", help="IAM principals for one group, one per line")
    p.add_argument("--group", required=True)
    p.set_defaults(func=cmd_principals)

    args = parser.parse_args(argv)
    data = load(args.file)

    # Read-only commands report problems; mutating ones refuse to build on a broken roster.
    if args.command not in ("check", "list", "show", "roles"):
        problems = validate(data)
        if problems:
            die("the roster is already invalid; fix it before adding to it.\n       "
                + "\n       ".join(problems))
    return args.func(args, data)


if __name__ == "__main__":
    raise SystemExit(main())
