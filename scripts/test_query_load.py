import os
import urllib.request
import json
import ssl
import datetime
import time
import jwt

CUBE_SECRET = os.environ["CUBEJS_API_SECRET"]  # US-2.2: no in-code default

token = jwt.encode({
    'iat': int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
    'exp': int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).timestamp()),
    'role': 'ROLE_EXECUTIVE_ALL',
    'canViewPii': True
}, CUBE_SECRET, algorithm='HS256')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

query = {
    "measures": ["InvestmentsFundamental.totalMarketValue", "InvestmentsFundamental.distinctPortfolios"]
}

url = f"{CUBE_BASE_URL}/cubejs-api/v1/load"
req = urllib.request.Request(
    url,
    data=json.dumps({"query": query}).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    },
    method="POST"
)

print(f"Querying {url} with query: {query}")
start = time.time()
while time.time() - start < 90:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"query": query}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            if data.get("continueWait") or data.get("error") == "Continue wait":
                print(f"Waiting for query execution (response: {data})...")
                time.sleep(2)
                continue
            print("Query Result Status: 200 OK")
            print(json.dumps(data, indent=2))
            break
    except Exception as e:
        print("Error executing query:", e)
        if hasattr(e, 'read'):
            print(e.read().decode())
        break
