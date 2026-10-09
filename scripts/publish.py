"""Publish an approved carousel to Instagram (and optionally Facebook) via the Graph API."""
import os, sys, json, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
date = sys.argv[1]
meta = json.loads((ROOT / "queue" / date / "meta.json").read_text())
if (ROOT / "queue" / date / "POSTED").exists():
    sys.exit("Already posted - refusing to double post.")

# Instagram API with Instagram Login (no Facebook Page needed). For the older Facebook-Login route set
# IG_API_BASE=https://graph.facebook.com/v26.0 and provide IG_USER_ID.
G = os.environ.get("IG_API_BASE") or "https://graph.instagram.com/v26.0"
uid = os.environ.get("IG_USER_ID") or "me"
tok = os.environ["IG_ACCESS_TOKEN"]
raw = os.environ["RAW_BASE"]

# Optional: cross-post the same carousel to the linked Facebook Page. Set PAGE_ID to enable; uses the
# same long-lived Page token (IG_ACCESS_TOKEN) and the Facebook Graph API directly, regardless of IG_API_BASE.
FB_API = "https://graph.facebook.com/v26.0"
page_id = os.environ.get("PAGE_ID")
caption_ig = meta.get("caption_ig", meta.get("caption", ""))
caption_fb = meta.get("caption_fb", meta.get("caption", ""))


def call(path, base=None, **data):
    r = requests.post(f"{(base or G)}/{path}", data={**data, "access_token": tok}, timeout=60)
    if not r.ok:
        sys.exit(f"Graph API error: {r.text}")
    return r.json()


def wait_ready(cid, base=None):
    for _ in range(30):
        s = requests.get(f"{(base or G)}/{cid}", params={"fields": "status_code", "access_token": tok}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            return
        if s.get("status_code") == "ERROR":
            sys.exit(f"Container failed: {s}")
        time.sleep(3)


# ───────────────────────── Instagram ─────────────────────────
kids = []
for i in range(1, len(meta["slides"]) + 1):
    kids.append(call(f"{uid}/media", image_url=f"{raw}/queue/{date}/slide_{i}.png", is_carousel_item="true")["id"])
for k in kids:
    wait_ready(k)
car = call(f"{uid}/media", media_type="CAROUSEL", children=",".join(kids), caption=caption_ig)["id"]
wait_ready(car)
post = call(f"{uid}/media_publish", creation_id=car)
(ROOT / "queue" / date / "POSTED").write_text(post["id"])
print("Published to Instagram:", post["id"])

# ───────────────────────── Facebook Page (optional) ─────────────────────────
if page_id:
    fb_photo_ids = []
    for i in range(1, len(meta["slides"]) + 1):
        img_url = f"{raw}/queue/{date}/slide_{i}.png"
        fb_photo_ids.append(call(f"{page_id}/photos", base=FB_API, url=img_url, published="false")["id"])
    attached = [{"media_fbid": pid} for pid in fb_photo_ids]
    fb_post = requests.post(f"{FB_API}/{page_id}/feed",
                            data={"message": caption_fb, "access_token": tok,
                                  "attached_media": json.dumps(attached)}, timeout=60)
    if not fb_post.ok:
        print("Facebook post failed (Instagram post already succeeded):", fb_post.text)
    else:
        fb_id = fb_post.json()["id"]
        (ROOT / "queue" / date / "POSTED_FB").write_text(fb_id)
        print("Published to Facebook:", fb_id)
else:
    print("PAGE_ID not set - skipping Facebook cross-post.")
