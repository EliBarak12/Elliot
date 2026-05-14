// Centralised HTTP client. CLAUDE.md mandates every fetch go through this
// module so the API key is injected exactly once and base URLs stay env-driven.
//
// Note: VITE_API_KEY is a Vite build-time variable and is baked into the
// shipped bundle. Treat it as a deployment-scoped token, not a per-user
// secret. The plugin/runtime accept it via X-Elliot-Key or
// Authorization: Bearer for browsers that cannot set custom headers
// cross-origin without a preflight (CORS is configured to allow both).
const API_KEY = import.meta.env.VITE_API_KEY ?? "";

export const PLUGIN_URL = (
  import.meta.env.VITE_PLUGIN_URL ?? "http://localhost:3000"
).replace(/\/+$/, "");

export const RUNTIME_URL = (
  import.meta.env.VITE_RUNTIME_URL ?? "http://localhost:3001"
).replace(/\/+$/, "");

function authHeaders(): Record<string, string> {
  if (!API_KEY) return {};
  return {
    "X-Elliot-Key": API_KEY,
    Authorization: `Bearer ${API_KEY}`,
  };
}

function mergeHeaders(
  ...sources: Array<HeadersInit | Record<string, string> | undefined>
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const src of sources) {
    if (!src) continue;
    if (src instanceof Headers) {
      src.forEach((v, k) => {
        out[k] = v;
      });
    } else if (Array.isArray(src)) {
      for (const [k, v] of src) out[k] = v;
    } else {
      Object.assign(out, src);
    }
  }
  return out;
}

export function authHeadersForMcp(): Record<string, string> {
  return authHeaders();
}

export class HttpError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`HTTP ${status}: ${body.slice(0, 200)}`);
    this.status = status;
    this.body = body;
  }
}

export async function httpFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const url = path.startsWith("http") ? path : `${RUNTIME_URL}${path.startsWith("/") ? "" : "/"}${path}`;
  const headers = mergeHeaders(authHeaders(), init.headers as HeadersInit | undefined);
  const resp = await fetch(url, { ...init, headers });
  if (resp.status === 401) {
    console.error("[http] 401 unauthorized — check VITE_API_KEY", { url });
  }
  return resp;
}

export async function httpJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await httpFetch(path, init);
  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new HttpError(resp.status, body);
  }
  return (await resp.json()) as T;
}
