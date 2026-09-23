"""Minimal Postgres v3 client: enough to prove the Cube SQL API is listening and authenticating.

No driver is installed on this machine and the point of the probe is the handshake itself, so it
is written against the wire protocol directly: StartupMessage -> AuthenticationCleartextPassword
-> PasswordMessage -> AuthenticationOk/ErrorResponse -> a single 'SELECT 1'.
"""
import json
import os
import socket
import struct
import sys

HOST = os.environ.get("PROBE_HOST", "127.0.0.1")
PORT = int(os.environ.get("PROBE_PORT", "15432"))

# SELECT 1 is answered by Cube's SQL layer alone. It proves the login and nothing more. Set
# PROBE_QUERY to a real cube query to exercise the DuckDB -> GCS read path, which is the half
# US-8.3 still has untested:
#
#   PROBE_QUERY="SELECT COUNT(*) FROM MemberMonthly LIMIT 1"
QUERY = os.environ.get("PROBE_QUERY", "SELECT 1")


def send(sock, tag, body):
    payload = struct.pack("!I", len(body) + 4) + body
    sock.sendall((tag.encode() if tag else b"") + payload)


def read_message(sock):
    tag = sock.recv(1)
    if not tag:
        raise EOFError("server closed the connection")
    (length,) = struct.unpack("!I", recv_exactly(sock, 4))
    return tag.decode(), recv_exactly(sock, length - 4)


def recv_exactly(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("server closed mid-message")
        buf += chunk
    return buf


def error_text(body):
    fields = {}
    for part in body.split(b"\x00"):
        if part:
            fields[chr(part[0])] = part[1:].decode("utf-8", "replace")
    return fields.get("M", repr(body))


def login(user, password, database="cube"):
    with socket.create_connection((HOST, PORT), timeout=30) as sock:
        params = b"".join(
            k + b"\x00" + v + b"\x00"
            for k, v in [(b"user", user.encode()), (b"database", database.encode())]
        )
        send(sock, "", struct.pack("!I", 196608) + params + b"\x00")

        while True:
            tag, body = read_message(sock)
            if tag == "E":
                return False, error_text(body)
            if tag == "R":
                (code,) = struct.unpack("!I", body[:4])
                if code == 0:
                    break
                if code == 3:
                    send(sock, "p", password.encode() + b"\x00")
                    continue
                return False, f"unsupported auth method {code} (probe handles cleartext only)"

        while True:
            tag, body = read_message(sock)
            if tag == "Z":
                break
            if tag == "E":
                return False, error_text(body)

        send(sock, "Q", QUERY.encode() + b"\x00")
        rows = []
        while True:
            tag, body = read_message(sock)
            if tag == "D":
                rows.append(body)
            elif tag == "E":
                return False, error_text(body)
            elif tag == "Z":
                break
        return True, f"authenticated; {QUERY!r} returned {len(rows)} row(s)"


if __name__ == "__main__":
    print(f"probing {HOST}:{PORT} with {QUERY!r}")
    users = json.load(open(sys.argv[1], encoding="utf-8"))
    for user, password in users.items():
        try:
            ok, detail = login(user, password)
        except Exception as err:  # noqa: BLE001 - the probe reports, it does not recover
            ok, detail = False, f"{type(err).__name__}: {err}"
        print(f"{'PASS' if ok else 'FAIL'}  {user}  {detail}")
