/**
 * Same-origin proxy to the Nightwatch API.
 *
 * Why this exists: the desk is served over HTTPS from Vercel, while the backend runs on
 * a plain box. A browser refuses to call an http:// API from an https:// page, and
 * putting a certificate on the box needs a domain. Routing the call through the app's
 * own origin removes both problems: the browser only ever talks to Vercel, and Vercel
 * talks to the backend server-side, where mixed content does not apply.
 *
 * Set NIGHTWATCH_API_ORIGIN (e.g. http://12.34.56.78:8000) in the Vercel project, and
 * NEXT_PUBLIC_API_URL to /api so the client calls this route. Locally, point
 * NEXT_PUBLIC_API_URL straight at the backend and this file is never used.
 */

import type { NextRequest } from "next/server";
import { snapshot } from "@/snapshot";
import { SNAPSHOT_HEADER, shouldFallback, snapshotGet, snapshotPost } from "@/lib/snapshot";

const GET_TIMEOUT_MS = 20_000; // a busy box answers in 15-25 s; cutting at 12 s made slow-but-fine calls look dead
const POST_TIMEOUT_MS = 110_000; // under maxDuration; a busy backend answered one chat in 105 s
// A signal passed to fetch() also cuts the response body when it fires. The chat stream's body
// legitimately runs for the whole turn (a busy backend takes 50-100 s), so it gets its own
// limit, just under maxDuration: with the 60 s one, every turn that took longer was cut off
// mid-answer and the browser reported "the connection dropped".
const STREAM_TIMEOUT_MS = 115_000;

export const dynamic = "force-dynamic"; // every call is live data
export const maxDuration = 120; // an analysis takes seconds; a cold backend can take longer

const ORIGIN = (process.env.NIGHTWATCH_API_ORIGIN ?? "").replace(/\/$/, "");

function target(req: NextRequest, path: string[]): string {
  const qs = req.nextUrl.search;
  return `${ORIGIN}/${path.map(encodeURIComponent).join("/")}${qs}`;
}

const PROXY_SECRET = process.env.NIGHTWATCH_PROXY_SECRET ?? "";

/** Headers the backend needs beyond content-type: the shared secret (when configured), the
 *  visitor's real address for per-client rate limits, and the desk's own x-nw-* markers. */
function upstreamHeaders(req: NextRequest): Record<string, string> {
  const h: Record<string, string> = { "content-type": "application/json", accept: "application/json" };
  if (PROXY_SECRET) h["x-nightwatch-proxy-secret"] = PROXY_SECRET;
  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || (req.headers.get("x-real-ip") ?? "").trim();
  if (ip) h["x-nightwatch-client-ip"] = ip;
  for (const name of ["x-nw-client", "x-nw-lang", "x-nw-internal"]) {
    const v = req.headers.get(name);
    if (v) h[name] = v;
  }
  return h;
}

const BACKOFF_MS = [1500, 4000]; // two retries: a read that is merely slow gets a second and third chance

/** A connection the backend refused outright. Nothing was delivered, so nothing can have
 *  been applied, which makes it the one failure a write may safely be retried on. */
function wasRefused(e: unknown): boolean {
  const code = (e as { cause?: { code?: string } })?.cause?.code;
  return code === "ECONNREFUSED" || code === "ECONNRESET" || code === "EHOSTUNREACH";
}

/** The backend restarts on every deploy and takes the better part of a minute to answer
 *  again. A call that lands in that window should wait rather than show a judge an error.
 *
 *  Reads retry on anything. Writes retry only on a refused connection: a POST that got as
 *  far as a 502 from the backend may have been applied, and an analysis is journaled, so
 *  sending it twice would write the same forecast down twice. */
async function withRetry(fn: () => Promise<Response>, isRead: boolean, maxRetries = BACKOFF_MS.length): Promise<Response> {
  let last: Response | undefined;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    if (attempt > 0) await new Promise((r) => setTimeout(r, BACKOFF_MS[attempt - 1]));
    try {
      last = await fn();
      if (!isRead || ![502, 503, 504].includes(last.status)) return last;
    } catch (e) {
      if (!isRead && !wasRefused(e)) throw e;
      if (attempt === maxRetries) throw e;
    }
  }
  return last as Response;
}

/** Saved answer for this call, or null. Sent with a header so the client can say so. */
function fromSnapshot(req: NextRequest, path: string[], body?: string): Response | null {
  const joined = path.join("/");
  const data = req.method === "GET" ? snapshotGet(snapshot, joined, req.nextUrl.search) : snapshotPost(snapshot, joined, body ?? "");
  if (data === null || !snapshot) return null;
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json", "cache-control": "no-store", [SNAPSHOT_HEADER]: snapshot.generated_at },
  });
}

async function forward(req: NextRequest, path: string[], body?: string) {
  const saved = () => fromSnapshot(req, path, body);
  if (!ORIGIN) {
    return saved() ?? Response.json({ detail: "This deployment has no backend configured. Set NIGHTWATCH_API_ORIGIN." }, { status: 503 });
  }
  const isRead = req.method === "GET";
  // With a saved answer in hand there is no point waiting out the restart backoff.
  const hasSaved = isRead && snapshotGet(snapshot, path.join("/"), req.nextUrl.search) !== null;
  try {
    const res = await withRetry(
      () =>
        fetch(target(req, path), {
          method: req.method,
          headers: upstreamHeaders(req),
          body,
          cache: "no-store",
          // Keep the backend's own error bodies intact so the UI can show them.
          redirect: "manual",
          signal: AbortSignal.timeout(isRead ? GET_TIMEOUT_MS : POST_TIMEOUT_MS),
        }),
      isRead,
      hasSaved ? 0 : undefined,
    );
    if (shouldFallback(res.status)) {
      const s = saved();
      if (s) return s;
    }
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: {
        "content-type": res.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
        // A 429's wait time, so the browser knows when to try again.
        ...(res.headers.get("retry-after") ? { "retry-after": res.headers.get("retry-after") as string } : {}),
      },
    });
  } catch {
    return saved() ?? Response.json({ detail: "The desk is busy right now. Please try again in a minute." }, { status: 502 });
  }
}

/** The chat's live progress (Server-Sent Events). Unlike every other call it must not be
 *  read to the end here: the upstream body is handed straight back so each step reaches
 *  the browser as the backend writes it. A failure to start is a plain JSON error, which
 *  the client takes as the cue to ask /chat instead (that route also has the saved-answer
 *  fallback, so this one deliberately has none). */
async function forwardStream(req: NextRequest, path: string[], body: string) {
  if (!ORIGIN) return Response.json({ detail: "This deployment has no backend configured. Set NIGHTWATCH_API_ORIGIN." }, { status: 503 });
  try {
    const res = await withRetry(
      () =>
        fetch(target(req, path), {
          method: "POST",
          headers: { ...upstreamHeaders(req), accept: "text/event-stream" },
          body,
          cache: "no-store",
          redirect: "manual",
          signal: AbortSignal.timeout(STREAM_TIMEOUT_MS),
        }),
      false,
    );
    const type = res.headers.get("content-type") ?? "";
    if (!res.ok || !type.startsWith("text/event-stream") || !res.body) {
      return new Response(await res.text(), {
        status: res.ok ? 502 : res.status,
        headers: { "content-type": type || "application/json", "cache-control": "no-store" },
      });
    }
    return new Response(res.body, {
      status: 200,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache, no-transform",
        "x-accel-buffering": "no",
      },
    });
  } catch {
    return Response.json({ detail: "Cannot reach the Nightwatch API from the server. Is the backend running?" }, { status: 502 });
  }
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const body = await req.text();
  if (path.length === 2 && path[0] === "chat" && path[1] === "stream") return forwardStream(req, path, body);
  return forward(req, path, body);
}
