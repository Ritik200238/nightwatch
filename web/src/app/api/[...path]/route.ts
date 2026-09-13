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

export const dynamic = "force-dynamic"; // every call is live data
export const maxDuration = 120; // an analysis takes seconds; a cold backend can take longer

const ORIGIN = (process.env.NIGHTWATCH_API_ORIGIN ?? "").replace(/\/$/, "");

function target(req: NextRequest, path: string[]): string {
  const qs = req.nextUrl.search;
  return `${ORIGIN}/${path.map(encodeURIComponent).join("/")}${qs}`;
}

/** The backend restarts on every deploy and takes a few seconds to answer again. A read
 *  that lands in that window should wait rather than show a judge an error page. Only
 *  reads are retried: a write that may have been applied is never sent twice. */
async function withRetry(fn: () => Promise<Response>, retry: boolean): Promise<Response> {
  try {
    const res = await fn();
    if (retry && (res.status === 502 || res.status === 503 || res.status === 504)) {
      await new Promise((r) => setTimeout(r, 2500));
      return await fn();
    }
    return res;
  } catch (e) {
    if (!retry) throw e;
    await new Promise((r) => setTimeout(r, 2500));
    return await fn();
  }
}

async function forward(req: NextRequest, path: string[], body?: string) {
  if (!ORIGIN) {
    return Response.json({ detail: "This deployment has no backend configured. Set NIGHTWATCH_API_ORIGIN." }, { status: 503 });
  }
  try {
    const res = await withRetry(
      () =>
        fetch(target(req, path), {
          method: req.method,
          headers: { "content-type": "application/json", accept: "application/json" },
          body,
          cache: "no-store",
          // Keep the backend's own error bodies intact so the UI can show them.
          redirect: "manual",
        }),
      req.method === "GET",
    );
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json", "cache-control": "no-store" },
    });
  } catch {
    return Response.json({ detail: "Cannot reach the Nightwatch API from the server. Is the backend running?" }, { status: 502 });
  }
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path, await req.text());
}
