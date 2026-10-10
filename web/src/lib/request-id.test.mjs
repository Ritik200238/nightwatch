// Run: node --experimental-strip-types src/lib/request-id.test.mjs   (Node >= 22.6)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { newRequestId } from "./request-id.ts";

const SERVER_PATTERN = /^[A-Za-z0-9_-]{8,64}$/;
const ids = new Set();
for (let i = 0; i < 200; i++) {
  const id = newRequestId();
  assert.match(id, SERVER_PATTERN, `an id the server would ignore: ${id}`);
  ids.add(id);
}
assert.equal(ids.size, 200, "every send has its own id");

// Without the browser's crypto the id is still valid and still varies.
const real = globalThis.crypto;
Object.defineProperty(globalThis, "crypto", { value: undefined, configurable: true });
try {
  const a = newRequestId();
  const b = newRequestId();
  assert.match(a, SERVER_PATTERN);
  assert.notEqual(a, b);
} finally {
  Object.defineProperty(globalThis, "crypto", { value: real, configurable: true });
}

// The stream and its plain retry carry the SAME id, made once per send. Two bodies, one id.
const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const stream = api.slice(api.indexOf("chatStream: async ("), api.indexOf("calibration: (ticker?: string"));
assert.equal((stream.match(/const requestId = newRequestId\(\);/g) ?? []).length, 1, "one id per send");
assert.equal((stream.match(/request_id: requestId/g) ?? []).length, 2, "on the stream and on the retry");
console.log("request-id ok");
