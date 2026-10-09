"""Daily job: pick a plan (80/15/5 mix, learned weights) -> write -> self-critique -> render -> queue."""
import os, json, datetime, random, time
from pathlib import Path
import requests
from render import render_carousel, ROOT

TODAY = datetime.date.today().isoformat()
QUEUE = ROOT / "queue" / TODAY
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
TITLE_STYLE = os.environ.get("TITLE_STYLE", "sentence")   # "sentence" or "upper"

# ───────────────────────── STRATEGY ─────────────────────────
# 80% education -> 15% authority -> 5% direct selling
MIX = {"education": 0.80, "authority": 0.15, "selling": 0.05}

SUBJECTS = {
    "Web design": "layout, hierarchy, whitespace, what makes a site feel professional or amateur",
    "Branding": "what a brand actually is, identity systems, how brands are perceived",
    "UI/UX": "how visitors navigate, friction, tap targets, forms, navigation patterns",
    "SEO": "how Google finds and ranks small-business sites, page titles, local search basics",
    "AEO": "answer-engine optimisation: being quoted by AI assistants and Google AI answers (clear answers, FAQs, structured info)",
    "Conversion": "turning visitors into enquiries: calls to action, offers, friction, trust signals",
    "Typography": "readability, font pairing, size, contrast, what type says about a business",
    "Colour psychology": "how colour affects trust, emotion and action (be careful and honest: avoid overclaiming)",
    "Brand strategy": "positioning, audience, promise, consistency, being chosen over competitors",
    "Website mistakes": "specific, common, fixable errors that cost small businesses enquiries",
    "Digital marketing": "how a website fits with social, search, email and ads",
    "User behaviour": "how people actually scan, judge and decide on websites (first impressions, scanning, attention)",
    "Accessibility": "contrast, alt text, keyboard use, readable text: right thing to do and good for business",
    "Business positioning": "saying what you do, who for and why you, so you are not compared on price alone",
    "Things businesses get wrong": "common misconceptions owners have about websites and branding",
    "Things your website should have": "concrete elements every small-business site needs and why",
    "Client education": "what to know before hiring a designer, how projects work, what to ask for",
}

HOOK_STYLES = {
    "problem_callout": "names a specific problem the reader may have right now ('Your contact form may be costing you leads')",
    "hidden_cost": "reveals something quietly costing them money or trust",
    "myth_bust": "corrects a common belief ('Your website isn't your brand')",
    "spot_it": "tells them how to check their own site in 30 seconds",
    "bold_claim": "a sharp, defensible statement that makes them want the explanation",
    "question": "a pointed question they can't help answering about their own business",
}

FORMATS = {
    "list": dict(slides=5, numbered=True, text="""A numbered list. Slide 1 = hook (+ a short series label). Slides 2-4 = three DIFFERENT
points, each one insight a business owner can act on. Slide 5 = a one-line takeaway that makes them want to save/send it."""),
    "deep_dive": dict(slides=5, numbered=False, text="""One idea explained properly across the carousel. Slide 1 = a sharp claim/hook.
Slide 2 = why the common belief is wrong or incomplete. Slide 3 = what is really going on. Slide 4 = what to do about it.
Slide 5 = a memorable closing line that reframes the idea."""),
    "spot_the_problem": dict(slides=5, numbered=True, text="""A self-diagnosis. Slide 1 = hook that makes the reader worry their site has a problem.
Slides 2-4 = one SYMPTOM each ('Visitors can't tell what you do in 5 seconds') with why it costs them. Slide 5 = how to
check/fix the first one, framed as a tip, not a pitch."""),
    "before_after": dict(slides=4, numbered=False, text="""A text-only before/after breakdown. Slide 1 = hook naming the common mistake.
Slides 2-3 = each slide shows the weak version ('Before: ...') then the stronger version ('After: ...') with the reason in a
short phrase. Slide 4 = the principle behind both."""),
    "process": dict(slides=5, numbered=False, text="""First-person professional perspective ('When I look at a small-business site, the first thing I check is...').
Slide 1 = hook. Slides 2-4 = what you look at and why it matters. Slide 5 = the takeaway. Describe the
PROCESS and reasoning only. Never invent client stories, names, results or numbers."""),
    "audit_offer": dict(slides=4, numbered=False, text="""A soft offer. Slide 1 = hook about a symptom ('If your site does any of these...').
Slides 2-3 = two specific signs a site needs attention. Slide 4 = invite them to DM the word AUDIT for a free quick review.
Warm and low-pressure. No hype."""),
}
TYPE_FORMATS = {
    "education": ["list", "deep_dive", "spot_the_problem", "before_after"],
    "authority": ["process", "deep_dive"],
    "selling": ["audit_offer"],
}
TYPE_GOAL = {
    "education": "TEACH. Give the reader something they did not know and can use. Do not mention hiring anyone or your services.",
    "authority": "SHOW EXPERTISE through how you think and what you look for. No selling, no invented case studies.",
    "selling": "INVITE, gently. One clear next step. Still useful on its own.",
}

PROMPT = """You write minimalist Instagram carousels for a freelance web and brand designer (@justin_masie).
The audience: small-business owners who are not designers. Success = a reader thinks one of:
  "I didn't know that." / "That's actually useful." / "My website might have this problem." / "I should get this looked at."

POST TYPE: {type}: {goal}
SUBJECT: {subject} ({subject_desc})
FORMAT: {format}: {format_text}
COVER HOOK STYLE: {hook_style}: {hook_desc}
SLIDES: exactly {n}

QUALITY RULES (non-negotiable)
- Every slide must carry a concrete, specific insight. If a slide could appear on any generic marketing blog, rewrite it.
- Lead with the consequence for THEIR business (lost sales, lost trust, lost enquiries), not the design theory.
- Claims should be accurate and hedged honestly ("can", "may", "often"). NEVER invent statistics, percentages, studies,
  client stories, testimonials or results. If you are not sure something is true, leave it out.
- Plain language, short sentences, no jargon (or explain it in five words), no emojis, no hashtags in slides.
- Banned: "in today's digital world", "elevate", "unlock", "game-changer", "stand out from the crowd",
  "consistency is key", "first impressions matter" (unless you add something genuinely new), "it's important to".
- Titles: max 9 words, a full thought, not a label. Body: max 38 words (cover body: 1-2 short sentences).

STYLE: weak vs better
WEAK: "Make your website mobile friendly."
BETTER: title "Your mobile experience can lose the sale." body "If your buttons are hard to tap, text is cramped, or important information is buried, mobile visitors may leave before they ever contact you."
WEAK: "Consistency is important for your brand."
BETTER: title "Your website isn't your brand." body "Your brand is the expectation people have before they buy from you. Your website either reinforces that expectation, or breaks it."
{learned}
Also write: "label" (the series label for the cover, max 3 words, e.g. "Website trust"), and THREE captions for the
same post, written separately so each reads naturally on its platform (not just copy-pasted):
- "caption_ig": Instagram caption, max 60 words, punchy and direct, adds one extra useful thought, ends with one line of
  exactly 5 hashtags, no selling unless post type is selling.
- "caption_fb": Facebook caption, max 90 words, a slightly more conversational and explanatory tone, written in full
  sentences as if talking to the reader, no hashtags (Facebook audiences respond better to plain text), same core message
  and no selling unless post type is selling.
- "caption_li": LinkedIn caption, max 110 words, professional first-person voice of a working designer, opens with a
  one-line hook, short paragraphs separated by blank lines, ends with a takeaway or a question for the reader, no
  hashtags, no emojis, same core message and no selling unless post type is selling.
Avoid repeating or paraphrasing these recent titles: {recent}

Return ONLY JSON: {{"label":"","slides":[{{"title":"","body":""}}],"caption_ig":"","caption_fb":"","caption_li":""}}"""

CRITIC = """You are a ruthless editor of Instagram/Facebook carousels for small-business owners (not designers).
For EACH slide ask: would the owner of a small business think "I didn't know that", "that's actually useful" or "my website
might have this problem"? Rewrite every slide that is generic, obvious, vague, preachy or could sit on any marketing blog,
making it more specific and consequence-led. Remove or soften anything that sounds like an invented statistic or an
unprovable claim. Keep it accurate. Keep the SAME JSON schema (label, slides, caption_ig, caption_fb, caption_li) and EXACTLY {n}
slides. Make sure caption_ig, caption_fb and caption_li still genuinely differ in tone as described in their original brief (Instagram
punchy with hashtags, Facebook conversational with no hashtags, LinkedIn professional with no hashtags). Limits: titles max 9 words, body max 38 words. Keep the voice
plain and confident.

DRAFT:
{draft}

Return ONLY the improved JSON."""

# ───────────────────────── HISTORY + LEARNING ─────────────────────────

def load_history():
    """Past queued posts (newest first), excluding today so a Regenerate does not skew choices."""
    metas = []
    for d in sorted((ROOT / "queue").glob("20*"), reverse=True):
        f = d / "meta.json"
        if d.name != TODAY and f.exists():
            try:
                metas.append(json.loads(f.read_text()))
            except Exception:
                pass
    return metas


def load_insights():
    f = ROOT / "queue" / "insights.json"
    return json.loads(f.read_text()) if f.exists() else {}


def pick_type(history, window=20):
    """Keep the rolling mix near 80/15/5: types that are behind target get more weight,
    with spacing rules (no back-to-back authority, no sales post within 7 posts of another)."""
    recent = [m.get("type") for m in history[:window]]
    w = {}
    for t, target in MIX.items():
        actual = recent.count(t) / len(recent) if recent else target
        w[t] = max(target + 1.5 * (target - actual), 0.01)
    if "selling" in [m.get("type") for m in history[:7]]:
        w["selling"] = 0
    if "authority" in [m.get("type") for m in history[:2]]:
        w["authority"] = 0
    return random.choices(list(w), weights=list(w.values()))[0]


def pick_weighted(names, key, history, insights, avoid_last=4):
    """Random choice, nudged by what has performed, avoiding recent repeats; retired items are rare."""
    stats = insights.get(f"by_{key}", {})
    retired = set(insights.get("retire", {}).get(key, []))
    recent = [m.get(key) for m in history[:avoid_last]]
    weights = []
    for n in names:
        x = 1.0
        if n in recent:
            x *= 0.1
        s = stats.get(n)
        if insights.get("learning_active") and s and s.get("posts", 0) >= 2:
            x *= min(2.0, max(0.5, s["avg_score"]))
        if n in retired:
            x *= 0.1
        weights.append(x)
    return random.choices(names, weights=weights)[0]


def learned_block(insights):
    if not insights.get("learning_active"):
        return ""
    good = [h["title"] for h in insights.get("top_hooks", [])][:3]
    weak = [h["title"] for h in insights.get("weak_hooks", [])][:3]
    out = "\nWHAT THIS AUDIENCE RESPONDS TO (from real performance data; learn the pattern, do not copy):\n"
    if good:
        out += "Hooks that earned attention: " + " | ".join(good) + "\n"
    if weak:
        out += "Hooks that were ignored: " + " | ".join(weak) + "\n"
    return out


def recent_titles(history):
    return [s["title"] for m in history[:8] for s in m.get("slides", [])][:30]

# ───────────────────────── GEMINI (with model fallback) ─────────────────────────
API = "https://generativelanguage.googleapis.com/v1beta"
PREFERRED = os.environ.get("GEMINI_MODELS", "gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite").split(",")


def discover_models():
    r = requests.get(f"{API}/models", params={"key": GEMINI_KEY, "pageSize": 200}, timeout=30)
    if not r.ok:
        return []
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])
             and "flash" in m["name"] and not any(x in m["name"] for x in ("image", "tts", "live", "audio"))]
    return sorted(names, reverse=True)


def gemini_json(prompt, validate, temperature=0.9, start_models=None):
    """Try models in order; return (parsed_json, model_used). Raises SystemExit if everything fails."""
    tried, last = [], None
    candidates = list(start_models or PREFERRED)
    for round_ in (1, 2):
        for model in candidates:
            if model in tried:
                continue
            tried.append(model)
            for attempt, wait in enumerate((0, 8, 25, 60)):   # retry temporary overloads (503/429/5xx)
                time.sleep(wait)
                try:
                    r = requests.post(f"{API}/models/{model}:generateContent", params={"key": GEMINI_KEY},
                                      json={"contents": [{"parts": [{"text": prompt}]}],
                                            "generationConfig": {"responseMimeType": "application/json",
                                                                 "temperature": temperature}}, timeout=120)
                except requests.RequestException as e:
                    print(f"{model}: network error, retrying ({e})")
                    continue
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
                print(f"{model}: HTTP {r.status_code}, retry {attempt + 1}")
            else:
                last = f"{model}: still unavailable after retries"
                continue
            if not r.ok:
                last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                print("Skipping", last)
                if r.status_code in (400, 401, 403) and "API key" in r.text:
                    raise SystemExit("API key rejected - check the GEMINI_API_KEY secret.")
                continue
            try:
                data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                validate(data)
                return data, model
            except Exception as e:
                last = f"{model}: unusable output ({e})"
                print("Skipping", last)
        if round_ == 1:
            candidates = discover_models()
            print("Preferred models failed; discovered:", candidates)
    raise SystemExit(f"All Gemini models failed. Last error: {last}")


def make_validator(n):
    def v(d):
        sl = d["slides"]
        assert len(sl) == n, f"expected {n} slides, got {len(sl)}"
        for s in sl:
            assert s["title"].strip() and len(s["title"].split()) <= 12, f"title too long/empty: {s['title']}"
            assert len(s.get("body", "").split()) <= 45, "body too long"
        assert d["caption_ig"].strip()
        assert d["caption_fb"].strip()
        assert d["caption_li"].strip()
    return v

# ───────────────────────── MAIN ─────────────────────────

def build():
    history, insights = load_history(), load_insights()
    ptype = pick_type(history)
    fmt = pick_weighted(TYPE_FORMATS[ptype], "format", history, insights, avoid_last=2)
    subject = pick_weighted(list(SUBJECTS), "subject", history, insights, avoid_last=5)
    hook = pick_weighted(list(HOOK_STYLES), "hook_style", history, insights, avoid_last=2)
    spec = FORMATS[fmt]
    n = spec["slides"]
    print(f"Plan: type={ptype} format={fmt} subject={subject} hook={hook}")

    prompt = PROMPT.format(type=ptype, goal=TYPE_GOAL[ptype], subject=subject, subject_desc=SUBJECTS[subject],
                           format=fmt, format_text=spec["text"], hook_style=hook, hook_desc=HOOK_STYLES[hook],
                           n=n, learned=learned_block(insights), recent=recent_titles(history))
    validate = make_validator(n)
    draft, model = gemini_json(prompt, validate)
    try:  # second pass: editor rewrites anything generic; fall back to the draft if it misbehaves
        final, _ = gemini_json(CRITIC.format(n=n, draft=json.dumps(draft)), validate, 0.6, [model] + PREFERRED)
    except SystemExit:
        final = draft
    print("Used model:", model)

    slides = final["slides"]
    label = (final.get("label") or subject).upper()
    slides[0]["kicker"] = label
    if spec["numbered"]:
        for i, s in enumerate(slides[1:-1], 1):
            s["kicker"] = f"{i:02d}"
    if TITLE_STYLE == "upper":
        for s in slides:
            s["title"] = s["title"].upper()
    return dict(date=TODAY, type=ptype, format=fmt, subject=subject, topic=subject, hook_style=hook,
                label=label, caption_ig=final["caption_ig"], caption_fb=final["caption_fb"], caption_li=final["caption_li"], slides=slides)


if __name__ == "__main__":
    meta = build()
    render_carousel(meta["slides"], QUEUE)
    (QUEUE / "meta.json").write_text(json.dumps(meta, indent=2))
