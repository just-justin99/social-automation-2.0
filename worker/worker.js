// Cloudflare Worker (free tier): turns a Slack button click into a GitHub Actions run.
// Secrets: APPROVE_SECRET, GH_TOKEN (fine-grained PAT, Actions: read/write), GH_REPO ("user/repo")
async function sign(secret, msg) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}
async function dispatch(env, workflow, inputs) {
  return fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GH_TOKEN}`, "User-Agent": "approve-worker",
               Accept: "application/vnd.github+json" },
    body: JSON.stringify({ ref: "main", inputs })
  });
}
const page = (msg, status = 200) => new Response(
  `<body style="background:#04090b;color:#ddd;font:20px system-ui;display:grid;place-items:center;height:100vh">${msg}</body>`,
  { status, headers: { "content-type": "text/html" } });

export default {
  async fetch(req, env) {
    const u = new URL(req.url);
    const token = u.searchParams.get("token");
    if (u.pathname === "/approve") {
      const date = u.searchParams.get("date");
      if (token !== await sign(env.APPROVE_SECRET, date)) return page("Invalid link", 403);
      const r = await dispatch(env, "publish.yml", { date });
      return page(r.ok ? "Approved. Posting now." : "GitHub error " + r.status);
    }
    if (u.pathname === "/regenerate") {
      if (token !== await sign(env.APPROVE_SECRET, "regenerate")) return page("Invalid link", 403);
      const r = await dispatch(env, "daily.yml", {});
      return page(r.ok ? "Regenerating. Check Slack in a minute." : "GitHub error " + r.status);
    }
    return page("OK");
  }
};
