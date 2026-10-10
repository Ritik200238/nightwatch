/**
 * One id per user send, kept for that send's whole life: the stream asks with it, and so does
 * the plain retry if the stream is cut. The server uses it to answer a retry with the first
 * run's result instead of analysing (and journalling) the same trade a second time.
 *
 * It is random and means nothing: no visitor id, no address, nothing typed. It matches the
 * server's `^[A-Za-z0-9_-]{8,64}$`, and an id that does not is simply ignored there.
 */
export function newRequestId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  if (c && typeof c.getRandomValues === "function") {
    const b = new Uint8Array(16);
    c.getRandomValues(b);
    return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
