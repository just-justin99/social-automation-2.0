"""Post today's queued carousel to Slack with an Approve button (runs after images are pushed)."""
import os, json, hmac, hashlib, datetime
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.date.today().isoformat()


def sign(msg):
    return hmac.new(os.environ["APPROVE_SECRET"].encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]


meta = json.loads((ROOT / "queue" / TODAY / "meta.json").read_text())
raw = os.environ["RAW_BASE"]  # https://raw.githubusercontent.com/<user>/<repo>/main
worker = os.environ["WORKER_URL"]
blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"Carousel for {TODAY}"}}]
for i in range(1, len(meta["slides"]) + 1):
    blocks.append({"type": "image", "image_url": f"{raw}/queue/{TODAY}/slide_{i}.png", "alt_text": f"slide {i}"})
blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Caption*\n" + meta["caption"]}})
blocks.append({"type": "actions", "elements": [
    {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Approve & post"},
     "url": f"{worker}/approve?date={TODAY}&token={sign(TODAY)}"},
    {"type": "button", "text": {"type": "plain_text", "text": "Regenerate"},
     "url": f"{worker}/regenerate?token={sign('regenerate')}"}]})
requests.post(os.environ["SLACK_WEBHOOK_URL"], json={"blocks": blocks}, timeout=30).raise_for_status()
print("sent to Slack")
