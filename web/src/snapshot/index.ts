/**
 * Loads the snapshot written by scripts/snapshot.mjs at build time. The JSON is
 * gitignored, so on a fresh checkout it is absent and this resolves to null.
 */
import type { SnapshotData } from "@/lib/snapshot";

let data: SnapshotData | null = null;
try {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const mod = require("./generated.json") as Partial<SnapshotData>;
  if (mod && mod.generated_at && mod.gets && mod.reports && Object.keys(mod.reports).length) data = mod as SnapshotData;
} catch {
  /* no snapshot built */
}

export const snapshot: SnapshotData | null = data;
