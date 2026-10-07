"""Daily job: write copy (Gemini free tier) -> render slides -> queue -> ping Slack."""
import os, json, datetime, random
from pathlib import Path
import requests
from render import render_carousel, ROOT

TODAY = datetime.date.today().isoformat()
QUEUE = ROOT / "queue" / TODAY
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
SLIDES = int(os.environ.get("SLIDES_PER_POST", 5))

TOPICS = [
    "website essentials for small businesses", "branding mistakes that cost clients",
    "why a logo is not a brand", "website speed and conversions", "clear calls to action",
    "colour and typography for trust", "what to put on a homepage", "mobile-first design",
    "SEO basics for new websites", "brand consistency across platforms",
    "social proof and testimonials", "signs your website is outdated",
    "how to write website copy that sells", "contact forms that get filled in",
]

PROMPT = """You write minimalist Instagram carousels for a freelance web designer / brand designer
(@justin_masie) whose goal is to attract small-business clients.
Topic: {topic}
Write exactly {n} slides:
- Slide 1: a scroll-stopping hook title (max 8 words) + 1-2 sentence body promising a payoff.
- Slides 2..{m}: one concrete, genuinely useful tip each. Title max 3 words. Body max 30 words,
  plain language, no jargon, no fluff.
- Last slide: soft call to action (e.g. DM 'WEBSITE' for a free quick audit). Title max 4 words.
Also write an Instagram caption (max 60 words, 1 line of hashtags, 5 hashtags).
Avoid repeating these recent titles: {recent}
Return ONLY JSON: {{"slides":[{{"title":"","body":""}}], "caption":""}}"""


def recent_titles():
    f = ROOT / "queue" / "history.json"
    return json.loads(f.read_text())[-30:] if f.exists() else []


def write_copy():
    topic = random.choice(TOPICS)
    r = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent",
        params={"key": GEMINI_KEY},
        json={"contents": [{"parts": [{"text": PROMPT.format(
            topic=topic, n=SLIDES, m=SLIDES - 1, recent=recent_titles())}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9}},
        timeout=60)
    r.raise_for_status()
    data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    assert len(data["slides"]) >= 3, "too few slides"
    return topic, data


if __name__ == "__main__":
    topic, data = write_copy()
    render_carousel(data["slides"], QUEUE)
    (QUEUE / "meta.json").write_text(json.dumps({"topic": topic, "caption": data["caption"],
                                                 "slides": data["slides"]}, indent=2))
    hist = ROOT / "queue" / "history.json"
    old = json.loads(hist.read_text()) if hist.exists() else []
    hist.write_text(json.dumps(old + [s["title"] for s in data["slides"]]))
