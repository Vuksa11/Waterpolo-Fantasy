export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}
async function fetchRequest(
  path,
  { signal, method = "GET", body, token, idempotencyKey } = {},
) {
  const controller = new AbortController(),
    timer = setTimeout(() => controller.abort(), 15000);
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", abort, { once: true });
  try {
    const response = await fetch("/api" + path, {
      method,
      signal: controller.signal,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const data = await response.json().catch(() => null);
    if (response.ok && data === null) {
      throw new ApiError(
        "Server je vratio neispravan odgovor. Ishod nije potvrđen.",
        502,
      );
    }
    if (!response.ok) {
      if (response.status === 429) {
        const seconds = Number(response.headers.get("Retry-After"));
        const retryAt = Date.parse(response.headers.get("Retry-After") || "");
        const wait =
          seconds > 0
            ? seconds
            : Number.isFinite(retryAt)
              ? Math.max(0, (retryAt - Date.now()) / 1000)
              : 0;
        const error = new ApiError(
          wait > 0
            ? `Previše pokušaja. Pokušaj ponovo za oko ${Math.ceil(wait / 60)} min.`
            : "Previše pokušaja. Sačekaj pre ponovnog slanja.",
          429,
        );
        error.retryAfter = wait;
        throw error;
      }
      let detail = data?.detail;
      throw new ApiError(
        Array.isArray(detail)
          ? detail.map((d) => d.msg).join(" · ")
          : typeof detail === "string"
            ? detail
            : `API greška (${response.status})`,
        response.status,
      );
    }
    return data;
  } catch (error) {
    if (controller.signal.aborted && !signal?.aborted)
      throw new ApiError(
        "Server nije odgovorio na vreme. Pokušaj ponovo.",
        408,
      );
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
export function catalogQuery({
  competition,
  search = "",
  position = "",
  club = "",
  sort = "cost_desc",
  offset = 0,
  limit = 24,
}) {
  const p = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    sort,
  });
  for (const [key, value] of Object.entries({
    competition_id: competition,
    search,
    position,
    club,
  }))
    if (value) p.set(key, value);
  return "/players/catalog?" + p;
}

// Only public GET responses are cached. Private responses never enter this map.
const publicCache = new Map();
const writes = new Map();
const pendingKeys = new Map();
export function clearPublicCache() {
  publicCache.clear();
}
export function peekCache(path) {
  return publicCache.get(path)?.data;
}
export async function request(path, options = {}) {
  const { method = "GET", token, cacheMs = 0 } = options;
  const cacheable = method === "GET" && !token && cacheMs > 0;
  const hit = publicCache.get(path);
  if (cacheable && hit && Date.now() - hit.at < cacheMs) return hit.data;
  const protectedWrite =
    method === "POST" &&
    (path === "/teams" || /^\/teams\/[^/]+\/transfers$/.test(path));
  if (!protectedWrite) {
    const data = await fetchRequest(path, options);
    if (cacheable && !options.signal?.aborted) {
      publicCache.delete(path);
      publicCache.set(path, { data, at: Date.now() });
      if (publicCache.size > 40)
        publicCache.delete(publicCache.keys().next().value);
    }
    return data;
  }
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify([token, path, options.body])),
  );
  const storageKey =
    "vrl-write-" +
    [...new Uint8Array(digest)]
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("");
  if (writes.has(storageKey)) return writes.get(storageKey);
  let key = pendingKeys.get(storageKey);
  try {
    key ||= sessionStorage.getItem(storageKey);
  } catch {}
  key ||= crypto.randomUUID();
  pendingKeys.set(storageKey, key);
  try {
    sessionStorage.setItem(storageKey, key);
  } catch {}
  const task = fetchRequest(path, { ...options, idempotencyKey: key })
    .then((data) => {
      pendingKeys.delete(storageKey);
      try {
        sessionStorage.removeItem(storageKey);
      } catch {}
      clearPublicCache();
      return data;
    })
    .catch((error) => {
      // An uncertain result must reuse its key on the next user-initiated retry.
      if (
        error.status >= 400 &&
        error.status < 500 &&
        ![408, 409, 429].includes(error.status)
      ) {
        pendingKeys.delete(storageKey);
        try {
          sessionStorage.removeItem(storageKey);
        } catch {}
      }
      if (
        error.status === 409 &&
        /progress|claim.*attempt/i.test(error.message)
      ) {
        error.message =
          "Prethodni zahtev se još obrađuje. Sačekaj pa ponovi istu radnju.";
      } else if (!error.status || error.status === 408 || error.status >= 500) {
        error.message =
          "Ishod zahteva nije potvrđen. Ponovi istu radnju da proveriš rezultat.";
      }
      throw error;
    })
    .finally(() => writes.delete(storageKey));
  writes.set(storageKey, task);
  return task;
}
