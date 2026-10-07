"""Weekly job: read Instagram insights for posted carousels -> score -> learn -> Slack report.

Writes queue/insights.json, which generate.py reads to bias subjects/formats/hooks.
Score (relative to the account's own median, so 1.0 = typical):
    0.4 * attention (reach)  +  0.6 * value (saves, shares, comments, likes, profile visits, follows per reach)
"""
import os, json, datetime, statistics
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
G = "https://graph.facebook.com/v21.0"
MIN_AGE_DAYS = 3          # let a post finish collecting reach before judging it
MIN_POSTS_TO_LEARN = 10   # below this, stay on defaults: tiny samples are mostly noise
RETIRE_BELOW, BOOST_ABOVE = 0.6, 1.3
WEIGHTS = {"saved": 4, "shares": 5, "comments": 3, "likes": 1, "profile_visits": 6, "follows": 8}
METRICS = ["reach", "saved", "shares", "likes", "comments", "profile_visits", "follows"]


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


def collect(tok):
    today = datetime.date.today()
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
        rows.append({"date": d.name, "type": m.get("type"), "format": m.get("format"),
                     "subject": m.get("subject") or m.get("topic"), "hook_style": m.get("hook_style"),
                     "hook": m["slides"][0]["title"], "m": {k: (v or 0) for k, v in vals.items()}})
    return rows


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else 0


def score_rows(rows):
    for r in rows:
        reach = max(r["m"]["reach"], 1)
        r["value_raw"] = sum(WEIGHTS[k] * r["m"][k] for k in WEIGHTS) / reach * 100
    base = [r for r in rows if r["type"] != "selling"] or rows     # baselines from teaching/authority posts
    reach_med = med([r["m"]["reach"] for r in base]) or 1
    value_med = med([r["value_raw"] for r in base]) or 1
    for r in rows:
        r["attention"] = r["m"]["reach"] / reach_med
        r["value"] = r["value_raw"] / value_med
        r["score"] = round(0.4 * r["attention"] + 0.6 * r["value"], 3)
    return rows


def group(rows, key):
    out = {}
    for r in rows:
        if r.get(key):
            out.setdefault(r[key], []).append(r["score"])
    return {k: {"posts": len(v), "avg_score": round(sum(v) / len(v), 3)} for k, v in out.items()}


def build(rows):
    rows = score_rows(rows)
    learn_rows = [r for r in rows if r["type"] != "selling"]
    ins = {"updated": datetime.date.today().isoformat(), "n_posts": len(rows),
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
                          "profile_visits": r["m"]["profile_visits"]}
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
    if not ins["learning_active"]:
        lines.append(f"Still collecting data. The system starts adapting at {MIN_POSTS_TO_LEARN} posts; "
                     "until then it uses your default mix.")
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
    lines.append("_Scores: 1.0 = your typical post. Small samples are noisy, so treat early numbers as hints._")
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
