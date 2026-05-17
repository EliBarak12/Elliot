// Centralised HTTP client. CLAUDE.md mandates every fetch go through this
// module so base URLs stay consistent.
//
// All browser → backend traffic is SAME-ORIGIN. Studio's nginx (production)
// and the Vite dev server (development) proxy `/api/plugin/*` and
// `/api/runtime/*` to the plugin and runtime, and inject the `X-Elliot-Key`
// header server-side. The API key therefore never reaches the browser bundle
// — there is no `VITE_API_KEY` anymore.
export const PLUGIN_URL = "/api/plugin";
export const RUNTIME_URL = "/api/runtime";

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
  const url = path.startsWith("http")
    ? path
    : `${RUNTIME_URL}${path.startsWith("/") ? "" : "/"}${path}`;
  const headers = mergeHeaders(init.headers as HeadersInit | undefined);
  const resp = await fetch(url, { ...init, headers });
  if (resp.status === 401) {
    console.error(
      "[http] 401 unauthorized — the Studio proxy is not injecting a valid " +
        "ELLIOT_API_KEY, or it does not match the backend's",
      { url }
    );
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
