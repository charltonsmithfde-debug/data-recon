"""Extract the deployed CUBEJS_SQL_USERS from the SQL VM's instance metadata.

The store holds scrypt digests, not passwords, but it is still credential material and this
script treats it as such: the file it writes is 0600 and outside the repo, and stdout carries
only usernames, roles, and an 8-hex-character SHA-256 fingerprint of each digest string. A
fingerprint is enough to tell two mint runs apart -- which is the entire question -- and is not
reversible into anything useful.

    python pull_store.py <instance> <zone> <out.json>

Exit codes: 0 extracted, 1 not found, 2 malformed.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys

# Node's scryptSync defaults, which mint_sql_users.js relies on: N=16384, r=8, p=1, 32-byte key,
# 8-byte salt, rendered as scrypt:<salt hex>:<key hex>.
DIGEST_RE = re.compile(r"^scrypt:[0-9a-f]{16}:[0-9a-f]{64}$")


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def gcloud_exe():
    """Resolve gcloud to a real executable.

    On Windows gcloud is a .cmd shim, which CreateProcess will not find from the bare name
    "gcloud" -- subprocess raises FileNotFoundError even though the command works in the shell
    this script was launched from. shutil.which consults PATHEXT and returns the shim's full path.
    """
    found = shutil.which("gcloud")
    if found is None:
        print("gcloud is not on PATH.")
        sys.exit(1)
    return found


def describe(instance, zone):
    result = subprocess.run(
        [gcloud_exe(), "compute", "instances", "describe", instance,
         "--zone", zone, "--format=json(metadata)"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"gcloud failed ({result.returncode}): {result.stderr.strip().splitlines()[-1:]}")
        sys.exit(1)
    return result.stdout


def metadata_text(blob):
    r"""Return the instance metadata as decoded text.

    --format=json(metadata) hands back the whole cloud-init user-data as a single JSON string
    value, so every quote inside it arrives escaped as \". Brace-balancing that raw stdout would
    then give json.loads a string beginning {\" -- perfectly good metadata reported as MALFORMED.
    Decoding through json first lets the parser undo its own escaping. A non-JSON blob (an older
    gcloud, or a plain-text format) is searched as-is.
    """
    try:
        document = json.loads(blob)
    except json.JSONDecodeError:
        return blob

    chunks = []

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            chunks.append(node)

    walk(document)
    return "\n".join(chunks)


def extract(blob):
    """Find the CUBEJS_SQL_USERS assignment wherever cloud-init put it.

    deploy_cube_sql_vm.sh writes it into a systemd unit as Environment="CUBEJS_SQL_USERS={...}",
    but an earlier revision used a --container-env file, so both shapes are matched. The JSON
    object is found by brace balancing rather than a lazy regex, because the digests contain no
    braces but the role names could gain nested structure later.
    """
    hits = []
    for match in re.finditer(r"CUBEJS_SQL_USERS=(\{)", blob):
        start = match.start(1)
        depth, index = 0, start
        while index < len(blob):
            if blob[index] == "{":
                depth += 1
            elif blob[index] == "}":
                depth -= 1
                if depth == 0:
                    hits.append(blob[start:index + 1])
                    break
            index += 1
    return hits


def main(instance, zone, out_path):
    hits = extract(metadata_text(describe(instance, zone)))
    if not hits:
        print("NOT FOUND: no CUBEJS_SQL_USERS assignment in the instance metadata.")
        print("The VM may predate the credential store, or the deploy wrote it elsewhere.")
        return 1

    try:
        store = json.loads(hits[0])
    except json.JSONDecodeError as err:
        print(f"MALFORMED: the deployed store is not valid JSON ({err}).")
        print("That alone would make every login fail, whatever the passwords are.")
        return 2

    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(store, handle)
    os.chmod(out_path, stat.S_IRUSR | stat.S_IWUSR)

    print(f"occurrences in metadata: {len(hits)} (all identical: {len(set(hits)) == 1})")
    print(f"users deployed: {len(store)}")
    print()
    for user, entry in sorted(store.items()):
        digest = entry["password"] if isinstance(entry, dict) else entry
        role = entry.get("role", "?") if isinstance(entry, dict) else "?"
        shape = "scrypt" if DIGEST_RE.match(digest) else f"UNEXPECTED({digest.split(':', 1)[0]})"
        print(f"  {user:42s} role={role:22s} {shape:20s} fp={fingerprint(digest)}")
    print()
    print(f"written 0600 to {out_path}")

    plain = [u for u, e in store.items()
             if not DIGEST_RE.match(e["password"] if isinstance(e, dict) else e)]
    if plain:
        print()
        print(f"WARNING: {len(plain)} entr(y|ies) are not scrypt digests. cube.js refuses to "
              f"start on a plaintext store, so the container would not be up at all.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
