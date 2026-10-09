"""Publish an approved carousel to Instagram, then (optionally) Facebook and LinkedIn."""
import os, sys, json, time, urllib.parse
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
date = sys.argv[1]
meta = json.loads((ROOT / "queue" / date / "meta.json").read_text())
if (ROOT / "queue" / date / "POSTED").exists():
    sys.exit("Already posted - refusing to double post.")

# Instagram via the Facebook-Login route: IG_API_BASE=https://graph.facebook.com/v26.0 and IG_USER_ID set.
G = os.environ.get("IG_API_BASE") or "https://graph.instagram.com/v26.0"
uid = os.environ.get("IG_USER_ID") or "me"
tok = os.environ["IG_ACCESS_TOKEN"]
raw = os.environ["RAW_BASE"]

FB_API = "https://graph.facebook.com/v26.0"
page_id = os.environ.get("PAGE_ID")                      # set to enable the Facebook cross-post
li_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")       # set to enable the LinkedIn cross-post
LI_API = "https://api.linkedin.com"
LI_VERSION = os.environ.get("LINKEDIN_VERSION") or "202608"   # YYYYMM; change if LinkedIn reports a bad version

n_slides = len(meta["slides"])
caption_ig = meta.get("caption_ig", meta.get("caption", ""))
caption_fb = meta.get("caption_fb", meta.get("caption", ""))
caption_li = meta.get("caption_li", caption_fb)


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


def post_facebook():
    photo_ids = []
    for i in range(1, n_slides + 1):
        r = requests.post(f"{FB_API}/{page_id}/photos", timeout=60,
                          data={"url": f"{raw}/queue/{date}/slide_{i}.png", "published": "false", "access_token": tok})
        if not r.ok:
            raise RuntimeError(r.text)
        photo_ids.append(r.json()["id"])
    r = requests.post(f"{FB_API}/{page_id}/feed", timeout=60,
                      data={"message": caption_fb, "access_token": tok,
                            "attached_media": json.dumps([{"media_fbid": p} for p in photo_ids])})
    if not r.ok:
        raise RuntimeError(r.text)
    return r.json()["id"]


def li_escape(text):
    """LinkedIn treats these characters as formatting; unescaped they can truncate the post."""
    return "".join("\\" + c if c in '\\|{}@[]()<>#*_~' else c for c in text)


def post_linkedin():
    auth = {"Authorization": f"Bearer {li_token}"}
    h = {**auth, "LinkedIn-Version": LI_VERSION, "X-Restli-Protocol-Version": "2.0.0"}
    author_id = os.environ.get("LINKEDIN_AUTHOR_ID")
    if not author_id:
        r = requests.get(f"{LI_API}/v2/userinfo", headers=auth, timeout=30)
        if r.status_code == 401:
            raise RuntimeError("LinkedIn token expired or invalid - regenerate LINKEDIN_ACCESS_TOKEN")
        if not r.ok:
            raise RuntimeError(f"userinfo failed: {r.status_code} {r.text}")
        author_id = r.json()["sub"]
    author = f"urn:li:person:{author_id}"

    images = []
    for i in range(1, n_slides + 1):
        r = requests.post(f"{LI_API}/rest/images?action=initializeUpload", headers=h, timeout=30,
                          json={"initializeUploadRequest": {"owner": author}})
        if not r.ok:
            raise RuntimeError(f"image init failed: {r.status_code} {r.text}")
        val = r.json()["value"]
        data = (ROOT / "queue" / date / f"slide_{i}.png").read_bytes()
        up = requests.put(val["uploadUrl"], headers={**auth, "Content-Type": "application/octet-stream"},
                          data=data, timeout=120)
        if up.status_code not in (200, 201):
            raise RuntimeError(f"image upload failed: {up.status_code} {up.text}")
        for _ in range(10):   # wait until LinkedIn has processed the image
            st = requests.get(f"{LI_API}/rest/images/{urllib.parse.quote(val['image'], safe='')}", headers=h, timeout=30)
            if st.ok and st.json().get("status") == "AVAILABLE":
                break
            time.sleep(2)
        images.append({"id": val["image"], "altText": f"{meta.get('label', 'Carousel')} slide {i}"})

    body = {"author": author, "commentary": li_escape(caption_li), "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "content": {"multiImage": {"images": images}},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    r = requests.post(f"{LI_API}/rest/posts", headers={**h, "Content-Type": "application/json"}, json=body, timeout=60)
    if r.status_code not in (200, 201):   # never retry after a 2xx: the post would be duplicated
        raise RuntimeError(f"post failed: {r.status_code} {r.text}")
    return r.headers.get("x-restli-id", "ok")


def cross_post(name, enabled, fn, marker):
    if not enabled:
        print(f"{name}: not configured - skipped.")
        return
    try:
        out = fn()
        (ROOT / "queue" / date / marker).write_text(str(out))
        print(f"Published to {name}: {out}")
    except (Exception, SystemExit) as e:   # one platform failing must never block the others
        print(f"{name} post failed (other platforms unaffected): {e}")


# ───────────────────────── Instagram (required) ─────────────────────────
kids = [call(f"{uid}/media", image_url=f"{raw}/queue/{date}/slide_{i}.png", is_carousel_item="true")["id"]
        for i in range(1, n_slides + 1)]
for k in kids:
    wait_ready(k)
car = call(f"{uid}/media", media_type="CAROUSEL", children=",".join(kids), caption=caption_ig)["id"]
wait_ready(car)
post = call(f"{uid}/media_publish", creation_id=car)
(ROOT / "queue" / date / "POSTED").write_text(post["id"])
print("Published to Instagram:", post["id"])

# ───────────────────────── Optional cross-posts ─────────────────────────
cross_post("Facebook", page_id, post_facebook, "POSTED_FB")
cross_post("LinkedIn", li_token, post_linkedin, "POSTED_LI")
