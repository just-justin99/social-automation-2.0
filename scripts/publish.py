"""Publish an approved carousel to Instagram via the Graph API."""
import os, sys, json, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
date = sys.argv[1]
meta = json.loads((ROOT / "queue" / date / "meta.json").read_text())
if (ROOT / "queue" / date / "POSTED").exists():
    sys.exit("Already posted - refusing to double post.")

G = "https://graph.facebook.com/v21.0"
uid, tok = os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]
raw = os.environ["RAW_BASE"]


def call(path, **data):
    r = requests.post(f"{G}/{path}", data={**data, "access_token": tok}, timeout=60)
    if not r.ok:
        sys.exit(f"Graph API error: {r.text}")
    return r.json()


def wait_ready(cid):
    for _ in range(30):
        s = requests.get(f"{G}/{cid}", params={"fields": "status_code", "access_token": tok}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            return
        if s.get("status_code") == "ERROR":
            sys.exit(f"Container failed: {s}")
        time.sleep(3)


kids = []
for i in range(1, len(meta["slides"]) + 1):
    kids.append(call(f"{uid}/media", image_url=f"{raw}/queue/{date}/slide_{i}.png", is_carousel_item="true")["id"])
for k in kids:
    wait_ready(k)
car = call(f"{uid}/media", media_type="CAROUSEL", children=",".join(kids), caption=meta["caption"])["id"]
wait_ready(car)
post = call(f"{uid}/media_publish", creation_id=car)
(ROOT / "queue" / date / "POSTED").write_text(post["id"])
print("Published", post["id"])
