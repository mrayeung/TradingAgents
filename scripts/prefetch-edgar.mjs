#!/usr/bin/env node
/**
 * prefetch-edgar.mjs
 *
 * Pre-fetches 13F holdings for every institution in the registry and stores
 * the result in web/.edgar-cache/{cik}.json.  Run this before starting the
 * dev server so the institutions page loads instantly without hitting SEC EDGAR
 * live on every request.
 *
 * Schedule: quarterly, ~2 weeks after quarter-end (13F deadline is 45 days
 * after quarter close, so run around mid-February, mid-May, mid-August,
 * mid-November).
 *
 * Usage:
 *   node scripts/prefetch-edgar.mjs          # fetch all
 *   node scripts/prefetch-edgar.mjs AAPL     # won't do anything — pass a CIK
 *   node scripts/prefetch-edgar.mjs 102909   # fetch only Vanguard
 *
 * Rate limit: SEC EDGAR allows ~10 req/s sustained; we fetch one institution
 * at a time with a 10-second gap between each (each institution = 2–3 EDGAR
 * requests internally), keeping us well under the limit.
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dir = dirname(fileURLToPath(import.meta.url));
const ROOT  = join(__dir, "..");
const CACHE_DIR = join(ROOT, "web", ".edgar-cache");
const WEB_PORT  = process.env.WEB_PORT ?? "3000";

// ── Helpers ───────────────────────────────────────────────────────────────────

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function loadInstitutions() {
  // Read the raw TS file and extract the INSTITUTIONS array via regex.
  // Avoids needing to compile TypeScript just for the IDs.
  const src = readFileSync(join(ROOT, "web", "src", "lib", "institutions.ts"), "utf8");
  const ids = [...src.matchAll(/id:\s*"(\d+)"/g)].map((m) => m[1]);
  const names = [...src.matchAll(/name:\s*"([^"]+)"/g)].map((m) => m[1]);
  return ids.map((id, i) => ({ id, name: names[i] ?? id }));
}

function cacheFile(id) {
  return join(CACHE_DIR, `${id}.json`);
}

function isFresh(id, maxAgeMs = 90 * 24 * 60 * 60 * 1000) {
  const f = cacheFile(id);
  if (!existsSync(f)) return false;
  try {
    const data = JSON.parse(readFileSync(f, "utf8"));
    const age = Date.now() - (data._cachedAt ?? 0);
    return age < maxAgeMs;
  } catch {
    return false;
  }
}

async function fetchAndCache(id, name) {
  const url = `http://localhost:${WEB_PORT}/api/institutions/${id}`;
  let resp;
  try {
    resp = await fetch(url, { signal: AbortSignal.timeout(60_000) });
  } catch (e) {
    return { ok: false, reason: `Network error: ${e.message}` };
  }

  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    return { ok: false, reason: `HTTP ${resp.status} — ${body.slice(0, 120)}` };
  }

  const data = await resp.json();
  data._cachedAt = Date.now();

  writeFileSync(cacheFile(id), JSON.stringify(data, null, 2), "utf8");
  return { ok: true, quarter: data.quarter, positions: data.positionCount };
}

// ── Main ──────────────────────────────────────────────────────────────────────

const DELAY_MS   = 10_000; // 10 s between institutions
const FORCE      = process.argv.includes("--force");
const TARGET_ID  = process.argv.find((a) => /^\d+$/.test(a));

mkdirSync(CACHE_DIR, { recursive: true });

const institutions = loadInstitutions();
const toFetch = TARGET_ID
  ? institutions.filter((i) => i.id === TARGET_ID)
  : institutions;

if (toFetch.length === 0) {
  console.error(`No institution found for ID "${TARGET_ID}"`);
  process.exit(1);
}

console.log(`\n📥  Edgar prefetch — ${toFetch.length} institution(s), ${DELAY_MS / 1000}s apart`);
console.log(`🌐  Hitting http://localhost:${WEB_PORT}/api/institutions/{cik}`);
console.log(`📁  Cache: ${CACHE_DIR}\n`);

let ok = 0, skipped = 0, failed = 0;

for (let i = 0; i < toFetch.length; i++) {
  const { id, name } = toFetch[i];

  if (!FORCE && isFresh(id)) {
    console.log(`  [${i + 1}/${toFetch.length}] ⏭  ${name} (${id}) — cache fresh, skipping`);
    skipped++;
    continue;
  }

  process.stdout.write(`  [${i + 1}/${toFetch.length}] ⏳  ${name} (${id}) … `);

  const result = await fetchAndCache(id, name);

  if (result.ok) {
    console.log(`✅  ${result.quarter}  (${result.positions} positions)`);
    ok++;
  } else {
    console.log(`❌  ${result.reason}`);
    failed++;
  }

  // Delay between institutions (skip after last one)
  if (i < toFetch.length - 1) {
    await sleep(DELAY_MS);
  }
}

console.log(`\n✨  Done — ${ok} fetched, ${skipped} skipped (fresh), ${failed} failed`);
if (failed > 0) {
  console.log(`⚠️   Run with --force to retry cached-but-stale entries`);
  process.exit(1);
}
