"""Weekly job: read Instagram + Facebook results (and optional LinkedIn numbers) -> score -> learn -> Slack report.

Writes queue/insights.json, which generate.py reads to bias subjects/formats/hooks.
Each platform is scored against its OWN median (1.0 = a typical post on that platform):
    0.4 * attention (reach/views)  +  0.6 * value (engagement per reach)
The overall score is a weighted average of the platforms that have data (Instagram 50%, Facebook 25%, LinkedIn 25%,
re-balanced over whichever platforms are present).

Small-sample protection: engagement-per-reach is smoothed (SMOOTH_REACH) so a post with a handful of views can't
produce a huge percentage, and every component is capped at CAP x typical.

LinkedIn: the API does not expose personal-post analytics to self-serve apps, so optionally fill
queue/linkedin_stats.csv by hand (date,impressions,reactions,comments,reposts) from LinkedIn's "View analytics".
"""
import os, csv, json, datetime, statistics
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
G = os.environ.get("IG_API_BASE") or "https://graph.instagram.com/v26.0"
FB_API = "https://graph.facebook.com/v26.0"
MIN_AGE_DAYS = 3          # let a post finish collecting reach before judging it
MIN_POSTS_TO_LEARN = 10   # below this, stay on defaults: tiny samples are mostly noise
RETIRE_BELOW, BOOST_ABOVE = 0.6, 1.3
SMOOTH_REACH = 25         # adds to reach before dividing, so tiny reach can't explode a rate
CAP = 5.0                 # no single post counts for more than 5x "typical" on any component

IG_WEIGHTS = {"saved": 4, "shares": 5, "comments": 3, "likes": 1, "profile_visits": 6, "follows": 8}
FB_WEIGHTS = {"shares": 5, "comments": 3, "reactions": 1}
LI_WEIGHTS = {"reposts": 5, "comments": 3, "reactions": 1}
METRICS = ["reach", "saved", "shares", "likes", "comments", "profile_visits", "follows"]
PLATFORMS = {
    "ig": dict(label="Instagram", reach="reach", weights=IG_WEIGHTS, weight=0.50, min_posts=1),
    "fb": dict(label="Facebook", reach="reach", weights=FB_WEIGHTS, weight=0.25, min_posts=3),
    "li": dict(label="LinkedIn", reach="impressions", weights=LI_WEIGHTS, weight=0.25, min_posts=3),
}


# ───────────────────────── Instagram ─────────────────────────
def metric(mid, name, tok):
    """One metric at a time, so an unsupported metric is skipped instead of failing the whole request."""
    r = requests.get(f"{G}/{mid}/insights", params={"metric": name, "access_token": tok}, timeout=30)
    if not r.ok:
        return None
    try:
        e = r.json()["data"][0]
        return e["total_value"]["value"] if "total_value" in e else e["values"][0]["value"]
    except Exception:
        return None


# ───────────────────────── Facebook ─────────────────────────
def fb_metric(pid, name, tok):
    r = requests.get(f"{FB_API}/{pid}/insights", params={"metric": name, "access_token": tok}, timeout=30)
    if not r.ok:
        return None
    try:
        return r.json()["data"][0]["values"][0]["value"]
    except Exception:
        return None


def fb_collect(pid, tok):
    """Reactions/comments/shares work with pages_read_engagement. Reach needs the read_insights permission."""
    r = requests.get(f"{FB_API}/{pid}", timeout=30, params={
        "fields": "reactions.summary(true).limit(0),comments.summary(true).limit(0),shares", "access_token": tok})
    if not r.ok:
        print("No Facebook data for", pid, "-", r.text[:200])
        return None
    j = r.json()
    m = {"reactions": (j.get("reactions") or {}).get("summary", {}).get("total_count", 0),
         "comments": (j.get("comments") or {}).get("summary", {}).get("total_count", 0),
         "shares": (j.get("shares") or {}).get("count", 0)}
    m["reach"] = fb_metric(pid, "post_total_media_view_unique", tok)
    if m["reach"] is None:
        m["reach"] = fb_metric(pid, "post_media_view", tok)      # views, if unique reach is unavailable
    return m


# ───────────────────────── LinkedIn (manual CSV) ─────────────────────────
def li_load():
    f = ROOT / "queue" / "linkedin_stats.csv"
    out = {}
    if not f.exists():
        return out
    with f.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            d = (row.get("date") or "").strip()
            if not d:
                continue
            try:
                out[d] = {k: int(float((row.get(k) or "0").strip() or 0))
                          for k in ("impressions", "reactions", "comments", "reposts")}
            except ValueError:
                print("Skipping bad LinkedIn row:", row)
    return out


# ───────────────────────── Collect ─────────────────────────
def collect(tok):
    today = datetime.date.today()
    li = li_load()
    rows = []
    for d in sorted((ROOT / "queue").glob("20*")):
        posted, meta = d / "POSTED", d / "meta.json"
        if not (posted.exists() and meta.exists()):
            continue
        if (today - datetime.date.fromisoformat(d.name)).days < MIN_AGE_DAYS:
            continue
        m = json.loads(meta.read_text())
        mid = posted.read_text().strip()
        vals = {k: metric(mid, k, tok) for k in METRICS}
        if vals["reach"] is None:
            print("No insights for", d.name, "(skipped)")
            continue
        fb_file = d / "POSTED_FB"
        fb = fb_collect(fb_file.read_text().strip(), tok) if fb_file.exists() else None
        rows.append({"date": d.name, "type": m.get("type"), "format": m.get("format"),
                     "subject": m.get("subject") or m.get("topic"), "hook_style": m.get("hook_style"),
                     "hook": m["slides"][0]["title"], "m": {k: (v or 0) for k, v in vals.items()},
                     "fb": fb, "li": li.get(d.name)})
    return rows


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else 0


# ───────────────────────── Score ─────────────────────────
def score_platform(rows, key, p):
    """Adds r[key_score] (and r[key_att]) for every row that has data for this platform. Returns how many."""
    have = [r for r in rows if r.get(key)]
    if len(have) < p["min_posts"]:
        return 0
    reach_key = p["reach"]
    for r in have:
        m = r[key]
        w = sum(wt * (m.get(k) or 0) for k, wt in p["weights"].items())
        rv = m.get(reach_key)
        r[f"{key}_raw"] = w / (rv + SMOOTH_REACH) * 100 if rv is not None else float(w)
    base = [r for r in have if r["type"] != "selling"] or have     # baselines from teaching/authority posts
    vmed = med([r[f"{key}_raw"] for r in base]) or 1
    rmed = med([r[key].get(reach_key) for r in base]) or 1
    for r in have:
        value = min(r[f"{key}_raw"] / vmed, CAP)
        rv = r[key].get(reach_key)
        if rv is None:                                              # engagement-only (no reach available)
            r[f"{key}_att"], r[f"{key}_score"] = None, round(value, 3)
        else:
            att = min(rv / rmed, CAP)
            r[f"{key}_att"], r[f"{key}_score"] = att, round(0.4 * att + 0.6 * value, 3)
    return len(have)


def score_rows(rows):
    for r in rows:
        r["ig"] = r["m"]
    used = {k: score_platform(rows, k, p) for k, p in PLATFORMS.items()}
    for r in rows:
        parts = [(PLATFORMS[k]["weight"], r[f"{k}_score"]) for k in PLATFORMS if r.get(f"{k}_score") is not None]
        r["score"] = round(sum(w * s for w, s in parts) / sum(w for w, _ in parts), 3)
        r["platform_scores"] = {PLATFORMS[k]["label"]: r[f"{k}_score"] for k in PLATFORMS
                                if r.get(f"{k}_score") is not None}
        r["attention"] = r.get("ig_att") or 0
    return rows, used


def group(rows, key):
    out = {}
    for r in rows:
        if r.get(key):
            out.setdefault(r[key], []).append(r["score"])
    return {k: {"posts": len(v), "avg_score": round(sum(v) / len(v), 3)} for k, v in out.items()}


def build(rows):
    rows, used = score_rows(rows)
    learn_rows = [r for r in rows if r["type"] != "selling"]
    ins = {"updated": datetime.date.today().isoformat(), "n_posts": len(rows),
           "platforms": {PLATFORMS[k]["label"]: n for k, n in used.items()},
           "facebook_has_reach": any(r.get("fb") and r["fb"].get("reach") is not None for r in rows),
           "learning_active": len(learn_rows) >= MIN_POSTS_TO_LEARN,
           "by_type": group(rows, "type"), "by_subject": group(learn_rows, "subject"),
           "by_format": group(learn_rows, "format"), "by_hook_style": group(learn_rows, "hook_style")}
    ins["repeat"], ins["retire"] = {}, {}
    for key in ("subject", "format", "hook_style"):
        stats = ins[f"by_{key}"]
        ins["repeat"][key] = [k for k, v in stats.items() if v["posts"] >= 2 and v["avg_score"] >= BOOST_ABOVE]
        ins["retire"][key] = [k for k, v in stats.items() if v["posts"] >= 3 and v["avg_score"] <= RETIRE_BELOW]
    by_att = sorted(learn_rows, key=lambda r: r["attention"], reverse=True)
    ins["top_hooks"] = [{"title": r["hook"], "attention": round(r["attention"], 2)} for r in by_att[:3]]
    ins["weak_hooks"] = [{"title": r["hook"], "attention": round(r["attention"], 2)} for r in by_att[-3:][::-1]] \
        if len(by_att) >= 6 else []
    ins["best_posts"] = [{"date": r["date"], "hook": r["hook"], "score": r["score"],
                          "by_platform": r["platform_scores"], "profile_visits": r["m"]["profile_visits"]}
                         for r in sorted(learn_rows, key=lambda r: r["score"], reverse=True)[:3]]
    ins["most_profile_visits"] = [{"date": r["date"], "hook": r["hook"], "profile_visits": r["m"]["profile_visits"]}
                                  for r in sorted(rows, key=lambda r: r["m"]["profile_visits"], reverse=True)[:3]
                                  if r["m"]["profile_visits"]]
    return ins


def report(ins):
    def top(d, n=3, rev=True):
        items = sorted(d.items(), key=lambda kv: kv[1]["avg_score"], reverse=rev)[:n]
        return ", ".join(f"{k} ({v['avg_score']:.1f}, {v['posts']} posts)" for k, v in items) or "n/a"
    lines = [f"*Weekly content report*: {ins['n_posts']} posts measured"]
    lines.append("*Platforms:* " + " · ".join(f"{k} {v}" for k, v in ins["platforms"].items()))
    if not ins["learning_active"]:
        lines.append(f"Still collecting data. The system starts adapting at {MIN_POSTS_TO_LEARN} posts; "
                     "until then it uses your default mix.")
    if ins["platforms"].get("Facebook") and not ins["facebook_has_reach"]:
        lines.append("_Facebook is scored on reactions, comments and shares only. Add the read_insights permission "
                     "to the Page token to include views._")
    if not ins["platforms"].get("LinkedIn"):
        lines.append("_LinkedIn not measured yet (optional: fill queue/linkedin_stats.csv from LinkedIn's post analytics)._")
    lines += [f"*Best subjects:* {top(ins['by_subject'])}",
              f"*Weakest subjects:* {top(ins['by_subject'], rev=False)}",
              f"*Best formats:* {top(ins['by_format'])}",
              f"*Best hook styles:* {top(ins['by_hook_style'])}"]
    if ins["top_hooks"]:
        lines.append("*Hooks that got attention:*\n" + "\n".join(f"• {h['title']}" for h in ins["top_hooks"]))
    if ins["most_profile_visits"]:
        lines.append("*Drove the most profile visits:*\n" + "\n".join(
            f"• {h['hook']} ({h['profile_visits']})" for h in ins["most_profile_visits"]))
    if ins["repeat"]["subject"]:
        lines.append("*Repeating more:* " + ", ".join(ins["repeat"]["subject"]))
    if ins["retire"]["subject"]:
        lines.append("*Retiring (rarely picked now):* " + ", ".join(ins["retire"]["subject"]))
    lines.append("_Scores: 1.0 = your typical post, capped at 5. Small samples are noisy, so treat early numbers as hints._")
    return "\n".join(lines)


if __name__ == "__main__":
    rows = collect(os.environ["IG_ACCESS_TOKEN"])
    if not rows:
        raise SystemExit("No posted carousels old enough to measure yet.")
    ins = build(rows)
    (ROOT / "queue" / "insights.json").write_text(json.dumps(ins, indent=2))
    text = report(ins)
    print(text)
    if os.environ.get("SLACK_WEBHOOK_URL"):
        requests.post(os.environ["SLACK_WEBHOOK_URL"], json={"text": text}, timeout=30)
