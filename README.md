# Free daily carousel system

Every day: Gemini writes a 5-slide carousel -> Pillow renders it on your glow template ->
images are committed to this repo -> Slack shows previews -> you click **Approve & post** ->
Instagram publishes it. All on free tiers (GitHub Actions, Gemini, Cloudflare Workers, Slack).

## One-time setup (~30 min)
1. **GitHub**: create a PUBLIC repo, push this folder to `main`
   (public is required so Slack/Instagram can fetch `raw.githubusercontent.com` image URLs).
2. **Gemini key**: https://aistudio.google.com/apikey (free). Save as secret `GEMINI_API_KEY`.
3. **Slack**: api.slack.com/apps -> Create app -> Incoming Webhooks -> add to a channel.
   Save the URL as secret `SLACK_WEBHOOK_URL`.
4. **Cloudflare Worker**: dash.cloudflare.com -> Workers -> Create -> paste `worker/worker.js`.
   Add Worker secrets: `APPROVE_SECRET` (any long random string), `GH_TOKEN`
   (GitHub fine-grained token, this repo only, "Actions: read & write"), `GH_REPO` (`you/repo`).
   Save the worker URL as repo secret `WORKER_URL` and reuse the same `APPROVE_SECRET` as a repo secret.
5. **Instagram**: needs a Business or Creator account linked to a Facebook Page.
   developers.facebook.com -> create app -> add Instagram Graph API -> get a long-lived
   access token and your IG user ID. Save as `IG_ACCESS_TOKEN` and `IG_USER_ID`.
   (Long-lived tokens last ~60 days: refresh them, or set a calendar reminder.)
6. Repo -> Actions -> run **Daily carousel** once manually to test. Slack should light up.

## Customise
- Topics, tone, slide count: `scripts/generate.py` (TOPICS, PROMPT, SLIDES_PER_POST)
- Colours/fonts/layout: `scripts/render.py`
- Post time: cron in `.github/workflows/daily.yml` (UTC; Botswana is UTC+2)
- Preview locally: `pip install -r requirements.txt && python scripts/render.py`

## Notes
- The approve link is HMAC-signed, and `publish.py` refuses to post the same day twice.
- Nothing posts without your click.
