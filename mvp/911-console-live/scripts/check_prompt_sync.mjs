// Verify scripts/rubric-shared.mjs's RUBRIC_SYSTEM_PROMPT matches
// lib/openai.ts's export of the same name.
//
// Run: node scripts/check_prompt_sync.mjs
// Exit 0 if identical, 1 if drift detected.

import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { RUBRIC_SYSTEM_PROMPT as SHARED } from "./rubric-shared.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const openaiTs = readFileSync(
  resolve(__dirname, "..", "lib", "openai.ts"),
  "utf8",
);

// Extract the template-literal body.
const match = openaiTs.match(
  /export const RUBRIC_SYSTEM_PROMPT\s*=\s*`([\s\S]*?)`;/,
);
if (!match) {
  console.error(
    "FAIL: could not locate RUBRIC_SYSTEM_PROMPT in lib/openai.ts",
  );
  process.exit(1);
}
const libPrompt = match[1];

if (libPrompt === SHARED) {
  console.log("[check_prompt_sync] OK — prompt bodies identical.");
  process.exit(0);
} else {
  console.error("[check_prompt_sync] FAIL — prompt bodies differ.");
  console.error(
    `lib/openai.ts length: ${libPrompt.length}; shared length: ${SHARED.length}`,
  );
  // Print first diverging character for debugging.
  let i = 0;
  while (i < libPrompt.length && i < SHARED.length && libPrompt[i] === SHARED[i]) i++;
  console.error(
    `first divergence at char ${i}: libChar=${JSON.stringify(libPrompt[i])}, sharedChar=${JSON.stringify(SHARED[i])}`,
  );
  process.exit(1);
}
