import http from "node:http";
import { proxyHeaders } from "./proxy.mjs";
import https from "node:https";
import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL(".", import.meta.url));
const upstream = new URL(process.env.API_TARGET || "http://127.0.0.1:8000");
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};
const server = http.createServer(async (req, res) => {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "no-referrer");
  const raw = req.url || "/";
  if (raw.startsWith("/api/") || raw === "/health") {
    const transport = upstream.protocol === "https:" ? https : http;
    const proxy = transport.request(
      {
        hostname: upstream.hostname,
        port: upstream.port,
        path: raw,
        method: req.method,
        headers: proxyHeaders(
          req.headers,
          req.socket.remoteAddress,
          upstream.host,
        ),
        timeout: 15000,
      },
      (r) => {
        res.writeHead(r.statusCode, r.headers);
        r.pipe(res);
      },
    );
    proxy.on("timeout", () => proxy.destroy(new Error("API timeout")));
    proxy.on("error", () => {
      if (!res.headersSent) {
        res.writeHead(502, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            detail: "Backend nije dostupan. Proveri da API radi na portu 8000.",
          }),
        );
      } else res.destroy();
    });
    req.on("aborted", () => proxy.destroy());
    req.pipe(proxy);
    return;
  }
  if (!["GET", "HEAD"].includes(req.method)) {
    res.writeHead(405);
    res.end();
    return;
  }
  try {
    const pathname = decodeURIComponent(
      new URL(raw, "http://localhost").pathname,
    );
    // Only expose frontend assets. Never expose repository, .env or server sources.
    let rel = ["/", "/verify-email", "/reset-password"].includes(pathname)
      ? "index.html"
      : pathname.replace(/^\//, "");
    if (rel.startsWith("assets/")) rel = "public/" + rel;
    if (
      rel !== "index.html" &&
      !rel.startsWith("src/") &&
      !rel.startsWith("public/assets/")
    ) {
      res.writeHead(404);
      res.end("Not found");
      return;
    }
    const absolute = path.resolve(root, rel);
    if (
      !absolute.startsWith(root) ||
      rel.split("/").some((s) => s.startsWith("."))
    ) {
      res.writeHead(403);
      res.end();
      return;
    }
    if (!(await stat(absolute)).isFile()) throw new Error("Not file");
    res.writeHead(200, {
      "Content-Type":
        types[path.extname(absolute)] || "application/octet-stream",
      "Cache-Control": "no-cache",
    });
    res.end(req.method === "HEAD" ? undefined : await readFile(absolute));
  } catch {
    res.writeHead(404);
    res.end("Not found");
  }
});
server.listen(
  Number(process.env.PORT || 3000),
  process.env.HOST || "127.0.0.1",
  () =>
    console.log(
      `VRL Fantasy: http://localhost:${process.env.PORT || 3000} → API ${upstream.origin}`,
    ),
);
