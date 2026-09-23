import os
import urllib.request
import json
import ssl
import datetime
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

url = f"{CUBE_BASE_URL}/cubejs-api/v1/meta"
req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
try:
    with urllib.request.urlopen(req, context=ctx) as response:
        print('Status:', response.status)
        data = json.loads(response.read().decode())
        cubes = [c['name'] for c in data.get('cubes', [])]
        print('Cubes in Cube.js:', cubes)
        for c in data.get('cubes', []):
            measures = [m['name'] for m in c.get('measures', [])]
            print(f"Cube: {c['name']} -> {len(measures)} measures: {measures[:5]}")
except Exception as e:
    print('Error:', e)
    if hasattr(e, 'read'):
        print(e.read().decode())
