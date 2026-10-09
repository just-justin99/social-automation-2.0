"""Post today's queued carousel to Slack with an Approve button (runs after images are pushed)."""
import os, json, hmac, hashlib, datetime
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.date.today().isoformat()


def sign(msg):
    return hmac.new(os.environ["APPROVE_SECRET"].encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]


def linkedin_warning():
    """Warn in Slack when the 60-day LinkedIn token is close to expiry (date kept in a GitHub variable)."""
    exp = os.environ.get("LINKEDIN_TOKEN_EXPIRES", "").strip()
    if not exp:
        return None
    try:
        days = (datetime.date.fromisoformat(exp) - datetime.date.today()).days
    except ValueError:
        return f":warning: LINKEDIN_TOKEN_EXPIRES should look like 2026-12-08 (got '{exp}')."
    how = ("Developer Portal > Tools > OAuth token generator > update the LINKEDIN_ACCESS_TOKEN secret, "
           "then set LINKEDIN_TOKEN_EXPIRES to 60 days from today.")
    if days < 0:
        return f":rotating_light: *LinkedIn token has expired.* LinkedIn posts will fail until you renew it. {how}"
    if days <= 10:
        return f":warning: *LinkedIn token expires in {days} day{'s' if days != 1 else ''}* ({exp}). {how}"
    return None


meta = json.loads((ROOT / "queue" / TODAY / "meta.json").read_text())
raw = os.environ["RAW_BASE"]  # https://raw.githubusercontent.com/<user>/<repo>/main
worker = os.environ["WORKER_URL"]
blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"Carousel for {TODAY}"}}]
warn = linkedin_warning()
if warn:
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": warn}})
for i in range(1, len(meta["slides"]) + 1):
    blocks.append({"type": "image", "image_url": f"{raw}/queue/{TODAY}/slide_{i}.png", "alt_text": f"slide {i}"})
caption_ig = meta.get("caption_ig", meta.get("caption", ""))
caption_fb = meta.get("caption_fb", meta.get("caption", ""))
blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Instagram caption*\n" + caption_ig}})
caption_li = meta.get("caption_li", caption_fb)
blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Facebook caption*\n" + caption_fb}})
blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*LinkedIn caption*\n" + caption_li}})
blocks.append({"type": "actions", "elements": [
    {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Approve & post"},
     "url": f"{worker}/approve?date={TODAY}&token={sign(TODAY)}"},
    {"type": "button", "text": {"type": "plain_text", "text": "Regenerate"},
     "url": f"{worker}/regenerate?token={sign('regenerate')}"}]})
requests.post(os.environ["SLACK_WEBHOOK_URL"], json={"blocks": blocks}, timeout=30).raise_for_status()
print("sent to Slack")
