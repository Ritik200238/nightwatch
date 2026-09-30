/**
 * The anonymous id, and how it travels with a request.
 *
 * The id is random text made in this browser and kept in localStorage. It is not tied to
 * an account, a name or an address, and the server keeps only a salted hash of it. Set
 * localStorage["nightwatch.internal"]="1" in your own browser to be left out of the counts.
 */

const ID_KEY = "nightwatch.client";
const LANG_KEY = "nightwatch.lang";
const INTERNAL_KEY = "nightwatch.internal";

export function clientId(): string {
  try {
    let id = localStorage.getItem(ID_KEY);
    if (!id || !/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
      const bytes = new Uint8Array(16);
      crypto.getRandomValues(bytes);
      id = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
      localStorage.setItem(ID_KEY, id);
    }
    return id;
  } catch {
    return ""; // storage blocked: the server then falls back to a hash of the address
  }
}

/** Identity as a query string, so it survives a proxy that drops custom headers. */
export function identityQuery(): string {
  if (typeof window === "undefined") return "";
  const q = new URLSearchParams();
  const id = clientId();
  if (id) q.set("nw_client", id);
  try {
    const lang = localStorage.getItem(LANG_KEY);
    if (lang === "en" || lang === "zh") q.set("nw_lang", lang);
    if (localStorage.getItem(INTERNAL_KEY) === "1") q.set("nw_internal", "1");
  } catch {
    /* no storage */
  }
  const s = q.toString();
  return s ? s : "";
}

export function withIdentity(path: string): string {
  const q = identityQuery();
  if (!q) return path;
  return `${path}${path.includes("?") ? "&" : "?"}${q}`;
}
