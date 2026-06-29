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

  // 1. Try common infotable filenames (covers >90% of large filers)
  const candidates = [
    "infotable.xml",
    "form13fInfoTable.xml",
    "form13f_infotable.xml",
    "wf-form13f_infotable.xml",
    "xslForm13F_X02/infotable.xml",
  ];

  for (const fname of candidates) {
    try {
      const res = await secFetch(`${base}/${fname}`);
      if (res.ok) {
        const text = await res.text();
        if (/<infoTable/i.test(text)) return text;
      }
    } catch {
      // try next candidate
    }
  }

  // 2. Fall back: parse filing index HTML to locate the INFORMATION TABLE doc
  try {
    const indexRes = await secFetch(`${base}/${accNodashes}-index.htm`);
    if (indexRes.ok) {
      const html = await indexRes.text();
      // The index table has rows like:
      //   <td>INFORMATION TABLE</td>  ... nearby <a href="someFile.xml">
      const rows = html.split(/<tr[\s>]/i);
      for (const row of rows) {
        if (/INFORMATION TABLE/i.test(row)) {
          const hrefMatch = row.match(/href="([^"]+\.xml)"/i);
          if (hrefMatch) {
            const xmlRes = await secFetch(`${base}/${hrefMatch[1]}`);
            if (xmlRes.ok) {
              const text = await xmlRes.text();
              if (/<infoTable/i.test(text)) return text;
            }
          }
        }
      }
    }
  } catch {
    // give up gracefully
  }

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

    const currentRaw = parseInfotable(currentXml);
    const totalValue = currentRaw.reduce((s, h) => s + h.value, 0);

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
          parseInfotable(prevXml).forEach((h) => prevByCusip.set(h.cusip, h));
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

      return {
        rank: i + 1,
        name: h.name,
        cusip: h.cusip,
        value: h.value,
        valueMM: Math.round(h.value / 1000),
        shares: h.shares,
        pctPortfolio: totalValue > 0 ? (h.value / totalValue) * 100 : 0,
        change,
        changePctShares,
      };
    });

    const payload: HoldingsPayload = {
      filingDate: filings[0].date,
      quarter: dateToQuarter(filings[0].date),
      totalValueMM: Math.round(totalValue / 1000),
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
