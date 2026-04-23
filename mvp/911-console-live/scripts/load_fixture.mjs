// Minimal YAML parser for psap-fixtures-v0.1.yaml — handles the specific
// shape of the fixture (version + categories list + scenarios list).
// Not a general-purpose YAML parser; if the fixture schema changes this
// needs to change.
//
// This module avoids pulling in `js-yaml` as a new dependency. Runs on
// plain Node ESM.

import { readFileSync } from "node:fs";

function parseScalar(raw) {
  const s = raw.trim();
  if (s === "true") return true;
  if (s === "false") return false;
  if (s === "null") return null;
  if (/^-?\d+$/.test(s)) return Number(s);
  if (/^-?\d+\.\d+$/.test(s)) return Number(s);
  if (s.startsWith('"') && s.endsWith('"')) return s.slice(1, -1);
  if (s.startsWith("'") && s.endsWith("'")) return s.slice(1, -1);
  return s;
}

/**
 * Extracts the 42 scenarios as a flat array of
 * { id, category, name, gedp_anchor, caller_script_summary, pass_criteria, fail_triggers, physician_sign_off }.
 *
 * Uses a line-oriented parse matching the exact indentation shape of
 * corpus/red-team/psap-fixtures-v0.1.yaml.
 */
export function loadFixture(path) {
  const text = readFileSync(path, "utf8");
  const lines = text.split("\n");
  const scenarios = [];
  let cur = null;
  let listField = null; // "pass_criteria" | "fail_triggers" | null
  let blockField = null; // "caller_script_summary" | null
  let blockLines = [];
  let blockIndent = 0;

  const finalizeBlock = () => {
    if (cur && blockField && blockLines.length > 0) {
      cur[blockField] = blockLines
        .map((l) => l.slice(blockIndent))
        .join("\n")
        .trimEnd();
    }
    blockField = null;
    blockLines = [];
  };

  const flushCur = () => {
    if (cur) {
      finalizeBlock();
      scenarios.push(cur);
      cur = null;
      listField = null;
    }
  };

  for (const raw of lines) {
    // block scalar continuation
    if (blockField) {
      const bt = raw.replace(/\s+$/, "");
      if (bt === "" || (bt.startsWith(" ".repeat(blockIndent)))) {
        if (bt === "") {
          blockLines.push("");
        } else {
          blockLines.push(raw);
        }
        continue;
      } else {
        finalizeBlock();
        // fall through to parse this line
      }
    }

    const line = raw.replace(/\s+$/, "");
    if (!line) continue;
    if (/^\s*#/.test(line)) continue;

    // Start of a scenario: `  - id: X1`
    const scenarioStart = /^  - id:\s*(.+)$/.exec(line);
    if (scenarioStart) {
      flushCur();
      cur = { id: parseScalar(scenarioStart[1]) };
      continue;
    }
    if (!cur) continue;

    // List continuation `      - "..."`
    const listItem = /^      - (.+)$/.exec(line);
    if (listItem && listField) {
      cur[listField].push(parseScalar(listItem[1]));
      continue;
    }

    // Key/value under scenario `    key: value` or `    key: |`
    const kv = /^    ([a-zA-Z_]+):\s*(.*)$/.exec(line);
    if (kv) {
      listField = null;
      const [, key, val] = kv;
      if (val === "|" || val === ">-" || val === "|-") {
        blockField = key;
        blockLines = [];
        blockIndent = 6; // fixture uses 6-space indent for block body
      } else if (val === "") {
        // following lines will be a list
        cur[key] = [];
        listField = key;
      } else {
        cur[key] = parseScalar(val);
      }
      continue;
    }
  }
  flushCur();

  // The fixture file has a `categories:` list (6 entries) and a
  // `scenarios:` list (42 entries) both under the top level, both using
  // `- id: X`. Distinguish by presence of scenario-specific fields.
  return scenarios.filter(
    (s) => typeof s.category === "string" && Array.isArray(s.pass_criteria),
  );
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const arg = process.argv[2] ?? "../corpus/red-team/psap-fixtures-v0.1.yaml";
  const scenarios = loadFixture(arg);
  console.log(`loaded ${scenarios.length} scenarios`);
  console.log(JSON.stringify(scenarios[0], null, 2));
}
