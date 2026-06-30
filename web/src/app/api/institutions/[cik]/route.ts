/**
 * GET /api/institutions/[cik]
 *
 * Serves 13F holdings data with a three-tier cache:
 *   1. File cache  — web/.edgar-cache/{cik}.json, written by scripts/prefetch-edgar.mjs
 *                    90-day TTL (13F data changes quarterly)
 *   2. Next.js fetch cache — 1-hour revalidation (production builds only)
 *   3. Live SEC EDGAR fetch — fallback when both caches are cold
 *
 * SEC rate limit: 10 req/s.  The prefetch script fetches one institution
 * every 10 seconds; live fallback uses 150 ms inter-request delays.
 */

import { NextRequest, NextResponse } from "next/server";
import { readFileSync, existsSync } from "fs";
import { join } from "path";
import { INSTITUTIONS } from "@/lib/institutions";
import type { ProcessedHolding, HoldingsPayload } from "@/lib/holdings-types";

// Force dynamic so Next.js never serves a stale cached response for this route
export const dynamic = "force-dynamic";

// ── File cache ────────────────────────────────────────────────────────────────

const CACHE_DIR = join(process.cwd(), ".edgar-cache");
const CACHE_MAX_AGE_MS = 90 * 24 * 60 * 60 * 1000; // 90 days

function readFileCache(cik: string): HoldingsPayload | null {
  try {
    const id = String(parseInt(cik, 10)); // strip leading zeros
    const path = join(CACHE_DIR, `${id}.json`);
    if (!existsSync(path)) return null;
    const raw = JSON.parse(readFileSync(path, "utf8")) as HoldingsPayload & { _cachedAt?: number };
    const age = Date.now() - (raw._cachedAt ?? 0);
    if (age > CACHE_MAX_AGE_MS) return null;
    const { _cachedAt: _, ...payload } = raw as typeof raw & { _cachedAt: number };
    return payload;
  } catch {
    return null;
  }
}

export type { ProcessedHolding, HoldingsPayload };

// ── Constants ─────────────────────────────────────────────────────────────────

const USER_AGENT =
  "OasisTradingDesk/1.0 (research tool; contact: research@example.com)";
const RATE_DELAY = 150; // ms between SEC requests

// ── Internal types ────────────────────────────────────────────────────────────

interface RawHolding {
  name: string;
  cusip: string;
  value: number;   // in thousands of dollars (as reported in 13F)
  shares: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

async function secFetch(url: string): Promise<Response> {
  await sleep(RATE_DELAY);
  return fetch(url, {
    headers: {
      "User-Agent": USER_AGENT,
      Accept: "application/json, text/xml, text/html, */*",
    },
    // Skip Next.js data cache so we always get a fresh response.
    // Persistence is handled by the file cache (prefetch-edgar.mjs).
    cache: "no-store",
  });
}

function extractTag(xml: string, tag: string): string {
  const m = xml.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`, "i"));
  return m ? m[1].trim() : "";
}

function parseInfotable(xml: string): RawHolding[] {
  const holdings: RawHolding[] = [];
  const blockRe = /<infoTable>([\s\S]*?)<\/infoTable>/gi;
  let m: RegExpExecArray | null;
  while ((m = blockRe.exec(xml)) !== null) {
    const b = m[1];
    const name   = extractTag(b, "nameOfIssuer");
    const cusip  = extractTag(b, "cusip");
    const value  = parseInt(extractTag(b, "value")      || "0", 10);
    const shares = parseInt(extractTag(b, "sshPrnamt")  || "0", 10);
    if (name && value > 0) holdings.push({ name, cusip, value, shares });
  }
  return holdings;
}

function dateToQuarter(date: string): string {
  const d = new Date(date);
  const q = Math.ceil((d.getMonth() + 1) / 3);
  return `Q${q} ${d.getFullYear()}`;
}

// ── SEC EDGAR fetching ────────────────────────────────────────────────────────

interface FilingMeta {
  date: string;
  accNodashes: string; // accession number without dashes, e.g. 000123456724000001
}

/**
 * Fetch the N most-recent 13F-HR filings for a CIK.
 *
 * Primary:  SEC submissions JSON API (structured, reliable, no HTML parsing)
 * Fallback: browse-edgar HTML scrape (catches filings not yet in submissions JSON)
 */
async function getRecentFilings(cik: string, count: number): Promise<FilingMeta[]> {
  const cikInt = parseInt(cik, 10);
  const results: FilingMeta[] = [];

  // ── Primary: submissions JSON ─────────────────────────────────────────────
  // data.sec.gov/submissions/CIK{10-digit-padded}.json contains recent filings.
  // `cik` is already zero-padded to 10 digits (e.g. "0001336528").
  const subUrl = `https://data.sec.gov/submissions/CIK${cik}.json`;
  console.log(`[13F] submissions JSON → ${subUrl}`);
  try {
    const subRes = await secFetch(subUrl);
    console.log(`[13F] submissions status: ${subRes.status} (CIK ${cik})`);
    if (subRes.ok) {
      const data = await subRes.json();
      const recent = data?.filings?.recent ?? {};
      const forms  = recent.form            ?? [];
      const dates  = recent.filingDate      ?? [];
      const accs   = recent.accessionNumber ?? [];
      console.log(`[13F] recent array length: ${forms.length}, entity: ${data?.name ?? "?"}`);
      // Log first few form types to catch whitespace/variant surprises
      console.log(`[13F] first 5 form types: ${forms.slice(0, 5).join(", ")}`);

      for (let i = 0; i < forms.length && results.length < count; i++) {
        // .trim() handles trailing spaces that occasionally appear in the API
        if ((forms[i] as string).trim() === "13F-HR") {
          results.push({
            date: dates[i],
            accNodashes: (accs[i] as string).replace(/-/g, ""),
          });
        }
      }
      console.log(`[13F] 13F-HR filings found via submissions JSON: ${results.length}`);
    }
  } catch (e) {
    console.error(`[13F] submissions JSON error for CIK ${cik}:`, e);
  }

  if (results.length >= count) return results;

  // ── Fallback: browse-edgar HTML scrape ────────────────────────────────────
  // Catches filings not yet indexed in submissions JSON (very recent).
  console.log(`[13F] falling back to browse-edgar HTML scrape (CIK ${cik})`);
  try {
    const url =
      `https://www.sec.gov/cgi-bin/browse-edgar` +
      `?action=getcompany&CIK=${cikInt}&type=13F-HR` +
      `&dateb=&owner=include&count=${count * 2 + 2}&search_text=`;

    const res = await secFetch(url);
    console.log(`[13F] browse-edgar status: ${res.status}`);
    if (!res.ok) throw new Error(`browse-edgar HTTP ${res.status}`);

    const html = await res.text();
    const rows = html.split(/<tr[\s>]/i);
    const seen = new Set(results.map((r) => r.accNodashes));

    for (const row of rows) {
      if (results.length >= count) break;
      if (!/13F-HR/i.test(row)) continue;

      const accMatch = row.match(/\/Archives\/edgar\/data\/\d+\/([\d]{18,})\//);
      if (!accMatch || seen.has(accMatch[1])) continue;

      const dateMatch = row.match(/(\d{4}-\d{2}-\d{2})/);
      if (!dateMatch) continue;

      results.push({ date: dateMatch[1], accNodashes: accMatch[1] });
      seen.add(accMatch[1]);
    }
    console.log(`[13F] browse-edgar added ${results.length} total filings`);
  } catch (e) {
    console.error(`[13F] browse-edgar error for CIK ${cik}:`, e);
  }

  return results;
}

async function fetchInfotableXml(
  cikInt: number,
  accNodashes: string
): Promise<string | null> {
  const base = `https://www.sec.gov/Archives/edgar/data/${cikInt}/${accNodashes}`;

  // Reconstruct dashed accession for index file name:
  // "000106798326000020" → "0001067983-26-000020"
  const accDashes = accNodashes.replace(/^(\d{10})(\d{2})(\d{6})$/, "$1-$2-$3");

  // Helper: resolve a possible absolute or relative href
  const resolveHref = (href: string) =>
    href.startsWith("/") ? `https://www.sec.gov${href}` : `${base}/${href}`;

  // 1. Try common infotable filenames (covers ~90% of large filers)
  const candidates = [
    "infotable.xml",
    "form13fInfoTable.xml",
    "form13f_infotable.xml",
    "wf-form13f_infotable.xml",
    "xslForm13F_X02/infotable.xml",
    "13f.xml",
    "13finfo.xml",
    "information_table.xml",
    "13F_HR.xml",
  ];

  for (const fname of candidates) {
    try {
      const res = await secFetch(`${base}/${fname}`);
      if (res.ok) {
        const text = await res.text();
        if (/<infoTable/i.test(text)) return text;
      }
    } catch { /* try next */ }
  }

  // 2. Parse the filing index HTML to find the INFORMATION TABLE document.
  //    EDGAR index URL uses the DASHED accession in the filename.
  const indexUrls = [
    `${base}/${accDashes}-index.htm`,   // correct EDGAR format
    `${base}/${accNodashes}-index.htm`, // legacy fallback
  ];

  for (const indexUrl of indexUrls) {
    try {
      const indexRes = await secFetch(indexUrl);
      if (!indexRes.ok) continue;
      const html = await indexRes.text();

      // Collect XML/TXT hrefs — prioritise rows containing "INFORMATION TABLE"
      const prioritised: string[] = [];
      const fallback: string[] = [];

      const rows = html.split(/<tr[\s>]/i);
      for (const row of rows) {
        const isInfoTable = /information.{0,5}table/i.test(row);
        const hrefs = [...row.matchAll(/href="([^"]+)"/gi)].map(m => m[1]);
        for (const href of hrefs) {
          if (!/\.(xml|txt)$/i.test(href)) continue;
          if (/index|submission|header/i.test(href)) continue;
          (isInfoTable ? prioritised : fallback).push(href);
        }
      }

      // Also catch any XML link not already found
      const allXml = [...html.matchAll(/href="([^"]+\.xml)"/gi)].map(m => m[1]);
      for (const href of allXml) {
        if (!prioritised.includes(href) && !fallback.includes(href) &&
            !/index|submission|header/i.test(href)) {
          fallback.push(href);
        }
      }

      for (const href of [...prioritised, ...fallback]) {
        try {
          const xmlRes = await secFetch(resolveHref(href));
          if (xmlRes.ok) {
            const text = await xmlRes.text();
            if (/<infoTable/i.test(text)) return text;
          }
        } catch { /* try next */ }
      }
    } catch { /* try next index URL */ }
  }

  // 3. Last resort: fetch the complete SGML submission text (e.g. 0001061768-25-000003.txt).
  //    EDGAR embeds every filing document in that file inside <TEXT>…</TEXT> wrappers,
  //    so <infoTable> blocks appear regardless of the infotable's XML filename.
  //    Covers filers like Baupost (bgllcq12025.xml) whose custom names don't match any
  //    candidate and whose index page is JavaScript-rendered (our HTML parser can't see it).
  try {
    const submissionRes = await secFetch(`${base}/${accDashes}.txt`);
    if (submissionRes.ok) {
      const text = await submissionRes.text();
      if (/<infoTable/i.test(text)) {
        console.log(`[13F] found infoTable in complete submission text for acc ${accDashes}`);
        return text;
      }
    }
  } catch { /* give up */ }

  return null;
}

// ── Route handler ─────────────────────────────────────────────────────────────

export async function GET(
  _req: NextRequest,
  { params }: { params: { cik: string } }
) {
  const { cik } = params;

  const institution = INSTITUTIONS.find((i) => i.id === cik);
  if (!institution) {
    return NextResponse.json({ error: "Institution not found" }, { status: 404 });
  }

  console.log(`[13F] GET /api/institutions/${cik} → entity: ${institution.name}, cik: ${institution.cik}`);

  const NO_CACHE = { "Cache-Control": "no-store, must-revalidate" };

  // ── Tier 1: file cache (written by prefetch-edgar.mjs) ──────────────────────
  const cached = readFileCache(institution.cik);
  if (cached) {
    console.log(`[13F] file cache HIT for CIK ${institution.cik}`);
    return NextResponse.json(cached, {
      headers: { ...NO_CACHE, "X-Cache": "HIT", "X-Cache-Source": "file" },
    });
  }
  console.log(`[13F] file cache MISS — hitting SEC EDGAR live`);

  // ── Live SEC EDGAR ────────────────────────────────────────────────────────
  try {
    // Fetch the two most-recent 13F-HR filings
    const filings = await getRecentFilings(institution.cik, 2);
    console.log(`[13F] getRecentFilings returned ${filings.length} result(s)`);
    if (filings.length === 0) {
      return NextResponse.json(
        { error: "No 13F-HR filings found for this institution — check terminal logs" },
        { status: 404, headers: NO_CACHE }
      );
    }

    const cikInt = parseInt(institution.cik, 10);

    // Fetch current infotable
    const currentXml = await fetchInfotableXml(cikInt, filings[0].accNodashes);
    if (!currentXml) {
      return NextResponse.json(
        { error: "Could not retrieve holdings data from SEC EDGAR" },
        { status: 502, headers: NO_CACHE }
      );
    }

    // Deduplicate by CUSIP — some filers (e.g. Berkshire Hathaway) report the
    // same security across multiple sub-managers (NEAM, etc.) in the same 13F.
    // Summing values + shares gives the correct consolidated position.
    const byCusip = new Map<string, RawHolding>();
    for (const h of parseInfotable(currentXml)) {
      const existing = byCusip.get(h.cusip);
      if (existing) {
        existing.value  += h.value;
        existing.shares += h.shares;
      } else {
        byCusip.set(h.cusip, { ...h });
      }
    }
    const currentRaw = [...byCusip.values()];
    const totalValue = currentRaw.reduce((s, h) => s + h.value, 0);

    // Auto-detect value unit.
    // SEC spec says <value> is in thousands of dollars, but many filers report
    // in full dollars (e.g. <value>2415946008</value> = $2.4B).
    // Heuristic: if the largest position exceeds 500,000,000 raw units, the values
    // are in dollars (500M dollars is a plausible position; 500M thousands = $500T
    // which is impossible). Use 1,000,000 divisor for dollars, 1,000 for thousands.
    const maxRawValue = currentRaw.reduce((m, h) => Math.max(m, h.value), 0);
    const valueDivisor = maxRawValue > 500_000_000 ? 1_000_000 : 1_000;
    console.log(`[13F] value unit: ${valueDivisor === 1_000_000 ? "dollars" : "thousands"} (max raw=${maxRawValue})`);

    // Fetch previous infotable for QoQ comparison
    let prevByCusip = new Map<string, RawHolding>();
    let prevFilingDate: string | null = null;
    let prevQuarter: string | null = null;

    if (filings.length >= 2) {
      prevFilingDate = filings[1].date;
      prevQuarter = dateToQuarter(filings[1].date);
      try {
        const prevXml = await fetchInfotableXml(cikInt, filings[1].accNodashes);
        if (prevXml) {
          // Same CUSIP dedup as current: sum sub-manager positions
          for (const h of parseInfotable(prevXml)) {
            const existing = prevByCusip.get(h.cusip);
            if (existing) {
              existing.value  += h.value;
              existing.shares += h.shares;
            } else {
              prevByCusip.set(h.cusip, { ...h });
            }
          }
        }
      } catch {
        // QoQ comparison is best-effort
      }
    }

    // Sort by value descending, assign rank, compute QoQ
    const sorted = [...currentRaw].sort((a, b) => b.value - a.value);

    const holdings: ProcessedHolding[] = sorted.map((h, i) => {
      const prev = prevByCusip.get(h.cusip);
      let change: ProcessedHolding["change"] = "unchanged";
      let changePctShares: number | null = null;

      if (!prev) {
        change = "new";
      } else if (h.shares > prev.shares) {
        change = "increased";
        changePctShares =
          prev.shares > 0
            ? ((h.shares - prev.shares) / prev.shares) * 100
            : null;
      } else if (h.shares < prev.shares) {
        change = "decreased";
        changePctShares =
          prev.shares > 0
            ? ((h.shares - prev.shares) / prev.shares) * 100
            : null;
      }

      // A legitimate quarterly position change cannot exceed ±1000%.
      // Anything beyond that indicates a share-count unit mismatch between
      // the two filings (e.g. one uses hundreds-of-shares, the other uses
      // actual shares). Nulling it out preserves the direction badge ("↑")
      // without showing a meaningless 5-digit number.
      if (changePctShares !== null && Math.abs(changePctShares) > 1000) {
        changePctShares = null;
      }

      return {
        rank: i + 1,
        name: h.name,
        cusip: h.cusip,
        value: h.value,
        valueMM: Math.round(h.value / valueDivisor),
        shares: h.shares,
        pctPortfolio: totalValue > 0 ? (h.value / totalValue) * 100 : 0,
        change,
        changePctShares,
      };
    });

    const payload: HoldingsPayload = {
      filingDate: filings[0].date,
      quarter: dateToQuarter(filings[0].date),
      totalValueMM: Math.round(totalValue / valueDivisor),
      positionCount: holdings.length,
      prevFilingDate,
      prevQuarter,
      holdings,
    };

    return NextResponse.json(payload, { headers: NO_CACHE });
  } catch (err) {
    console.error(`13F API error for CIK ${cik}:`, err);
    return NextResponse.json(
      { error: "Failed to fetch SEC EDGAR data" },
      { status: 502, headers: NO_CACHE }
    );
  }
}
