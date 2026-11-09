// Cloudflare Worker: inoltra le richieste a trasparenzascuole.it, il cui WAF blocca
// gli IP di GitHub Actions. Variabile segreta del Worker: PROXY_KEY (uguale al secret
// GitHub TRASPARENZA_PROXY_KEY), cosi il Worker non e un proxy aperto.
const TARGET = "https://www.trasparenzascuole.it";

export default {
  async fetch(req, env) {
    if (!env.PROXY_KEY || req.headers.get("x-proxy-key") !== env.PROXY_KEY) {
      return new Response("forbidden", { status: 403 });
    }
    const url = new URL(req.url);
    const headers = new Headers(req.headers);
    headers.delete("x-proxy-key");
    // L'IP del chiamante (GitHub) non deve arrivare al WAF: toglie gli header che lo portano
    for (const h of [...headers.keys()]) {
      if (h.startsWith("cf-") || h.startsWith("x-forwarded") || h === "x-real-ip" || h === "true-client-ip" || h === "forwarded") {
        headers.delete(h);
      }
    }
    // Cloudflare rimette X-Forwarded-For anche se cancellato: va sovrascritto
    headers.set("x-forwarded-for", "127.0.0.1");
    const resp = await fetch(TARGET + url.pathname + url.search, {
      method: req.method,
      headers,
      body: ["GET", "HEAD"].includes(req.method) ? undefined : await req.arrayBuffer(),
      redirect: "manual",
    });
    const out = new Response(resp.body, resp);
    const loc = out.headers.get("location");
    if (loc) out.headers.set("location", loc.replace(/^https?:\/\/(www\.)?trasparenzascuole\.it/i, url.origin));
    return out;
  },
};
