// The conversation and the report on screen, kept for the tab so a refresh or the Back button
// brings the desk back as it was. sessionStorage is per tab and gone when the tab closes; every
// access is wrapped, because it can be blocked or full (private windows, embedded previews).

const CHAT_KEY = "nw-desk-chat-v1";
const REPORT_KEY = "nw-desk-report-v1";
const MAX_MESSAGES = 60;
const MAX_CHARS = 600_000;

export interface SavedChat<M> {
  messages: M[];
  contextId: number | null;
  side: string | null;
}

export function loadChat<M>(): SavedChat<M> | null {
  try {
    const raw = window.sessionStorage.getItem(CHAT_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<SavedChat<M>>;
    if (!v || !Array.isArray(v.messages) || v.messages.length === 0) return null;
    return { messages: v.messages, contextId: typeof v.contextId === "number" ? v.contextId : null, side: typeof v.side === "string" ? v.side : null };
  } catch {
    return null;
  }
}

export function saveChat<M>(chat: SavedChat<M>): void {
  try {
    if (chat.messages.length === 0) {
      window.sessionStorage.removeItem(CHAT_KEY);
      return;
    }
    const text = JSON.stringify({ ...chat, messages: chat.messages.slice(-MAX_MESSAGES) });
    if (text.length <= MAX_CHARS) window.sessionStorage.setItem(CHAT_KEY, text);
  } catch {
    /* blocked or full: the desk simply starts empty next time */
  }
}

/** The id of the stored report on screen, when it has one (a what-if has no stored copy to reload). */
export function loadReportId(): number | null {
  try {
    const n = Number(window.sessionStorage.getItem(REPORT_KEY));
    return Number.isInteger(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}

export function saveReportId(id: number | null): void {
  try {
    if (id != null && id > 0) window.sessionStorage.setItem(REPORT_KEY, String(id));
    else window.sessionStorage.removeItem(REPORT_KEY);
  } catch {
    /* ignore */
  }
}
