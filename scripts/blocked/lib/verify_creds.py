"""Answer one question: does the probe's plaintext match the digests that are actually deployed?

This is the diagnosis the agent could not run -- not because it is dangerous, but because every
route to it reads credential material and the tool sandbox refuses that categorically, and
correctly. Run by a human it is cheap and decisive.

Output is booleans and digest fingerprints only. No password, salt or key is printed, logged or
returned, and the comparison is done by re-deriving the scrypt key rather than by reversing
anything.

    python verify_creds.py <probe_creds.json> <store.json> [<store2.json> ...]

  probe_creds.json  {"user": "password", ...}          -- what pg_probe.py will send
  store.json        CUBEJS_SQL_USERS as deployed       -- from pull_store.py

Reading it:

  MATCH   the password verifies against that digest; a failed login is NOT a credential problem
  no      the password does not verify; that store was minted by a different run
  ABSENT  the user is not in that store at all

Exit codes: 0 every probe user matches somewhere, 1 at least one does not.
"""

import hashlib
import json
import sys

# mint_sql_users.js uses Node's crypto.scryptSync defaults. CPython exposes the same primitive
# but requires maxmem to be stated: the default is 32 MiB and N=16384,r=8 needs 128*N*r = 16 MiB
# of working memory plus overhead, so the default is marginal and fails on some builds.
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_KEYLEN = 16384, 8, 1, 32
SCRYPT_MAXMEM = 128 * SCRYPT_N * SCRYPT_R * 2


def fingerprint(text):
    """Stable short label for a digest string. Not a password hash -- a hash of a hash."""
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def load_store(path):
    raw = json.load(open(path, encoding="utf-8"))
    return {user: (entry["password"] if isinstance(entry, dict) else entry)
            for user, entry in raw.items()}


def verify(password, digest):
    try:
        scheme, salt_hex, key_hex = digest.split(":", 2)
    except ValueError:
        return None
    if scheme != "scrypt":
        return None
    derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                             n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                             dklen=SCRYPT_KEYLEN, maxmem=SCRYPT_MAXMEM)
    # Not timing-safe on purpose: this is an offline diagnostic against a local file, and
    # hmac.compare_digest here would imply a threat model that does not apply.
    return derived.hex() == key_hex


def main(argv):
    creds = json.load(open(argv[0], encoding="utf-8"))
    stores = {path: load_store(path) for path in argv[1:]}

    print(f"probe users:  {len(creds)}")
    for path, store in stores.items():
        prints = sorted(fingerprint(d) for d in store.values())
        print(f"store {path}")
        print(f"    {len(store)} users, digest fingerprints: {' '.join(prints)}")
    print()

    width = max(len(u) for u in creds) if creds else 10
    header = " ".join(f"{path.rsplit('/', 1)[-1]:>24s}" for path in stores)
    print(f"{'user':{width}s}  {header}")
    print("-" * (width + 2 + len(header)))

    failures = 0
    for user, password in sorted(creds.items()):
        cells = []
        matched_anywhere = False
        for store in stores.values():
            digest = store.get(user)
            if digest is None:
                cells.append(f"{'ABSENT':>24s}")
                continue
            result = verify(password, digest)
            if result is None:
                cells.append(f"{'NOT-A-SCRYPT-DIGEST':>24s}")
            elif result:
                cells.append(f"{fingerprint(digest) + ' MATCH':>24s}")
                matched_anywhere = True
            else:
                cells.append(f"{fingerprint(digest) + ' no':>24s}")
        if not matched_anywhere:
            failures += 1
        print(f"{user:{width}s}  {' '.join(cells)}")

    print()
    if failures == 0:
        print("Every probe password verifies against a deployed digest.")
        print("So a failing login is NOT a credential mismatch -- look at the database name, the")
        print("auth method Cube offers, or checkSqlAuth's role lookup instead.")
        return 0

    print(f"{failures} of {len(creds)} probe passwords verify against nothing deployed.")
    print("The probe file and the deployed store came from different mint_sql_users.js runs.")
    print("Fix: re-mint and redeploy the store -- 02b_remint_sql_users.sh -- keeping the existing")
    print("CUBEJS_API_SECRET and HMAC pair, so no other credential is rotated as a side effect.")
    return 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
