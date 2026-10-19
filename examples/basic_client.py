"""Send a stable, read-only request via local gateway.

Requires OPENAI_API_KEY and a running `python -m cooooost serve`.
This example intentionally enables replay; do not use replay for live data.
"""
import json
import os
import urllib.request

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise SystemExit("Set OPENAI_API_KEY first")

payload = {"model": os.environ.get("COOOOOST_MODEL", "gpt-4.1-mini"),
           "temperature": 0,
           "messages": [{"role": "user", "content": "Name the three primary colors."}]}
request = urllib.request.Request(
    "http://127.0.0.1:8765/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json",
             "X-Cooooost-Cache": "replay", "X-Cooooost-Namespace": "colors-demo"},
    method="POST")
with urllib.request.urlopen(request, timeout=120) as response:
    print("Cooooost:", response.headers.get("X-Cooooost-Cache"))
    print(json.dumps(json.load(response), indent=2, ensure_ascii=False))