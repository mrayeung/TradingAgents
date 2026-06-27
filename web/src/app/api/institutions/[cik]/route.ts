/**
 * GET /api/institutions/[cik]
 *
 * Fetches the two most recent 13F-HR filings for the given SEC CIK from
 * EDGAR, parses the infotable XML holdings, computes quarter-over-quarter
 * changes, and returns a structured JSON payload.
 *
 * SEC rate limit: 10 req/s.  We stay well under with 150 ms inter-request
 * delays and Next.js fetch caching (1 h TTL).
 */

import { NextRequest, NextResponse } from "next/server";
import { INSTITUTIONS } from "@/lib/institutions";
import type { ProcessedHolding, HoldingsPayload } from "@/lib/holdings-types";

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
    // Cache responses for 1 hour — 13F data only changes quarterly
    next: { revalidate: 3600 },
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
 * Fetch the N most-recent 13F-HR filings for a CIK using the EDGAR
 * company search endpoint with type=13F-HR filter.
 *
 * This is more reliable than scanning filings.recent from the submissions
 * JSON, which only holds ~40 entries across ALL form types and can miss
 * recent 13F-HR filings for high-volume filers (BlackRock advisors, etc.).
 */
async function getRecentFilings(cik: string, count: number): Promise<FilingMeta[]> {
  const cikInt = parseInt(cik, 10);

  // The browse-edgar endpoint with type=13F-HR returns ONLY 13F-HR results,
  // regardless of total filing volume for the entity.
  const url =
    `https://www.sec.gov/cgi-bin/browse-edgar` +
    `?action=getcompany&CIK=${cikInt}&type=13F-HR` +
    `&dateb=&owner=include&count=${count * 2 + 2}&search_text=`;

  const res = await secFetch(url);
  if (!res.ok) throw new Error(`SEC EDGAR browse HTTP ${res.status} for CIK ${cik}`);

  const html = await res.text();
  const results: FilingMeta[] = [];

  // Parse table rows — each row with a 13F-HR link looks like:
  //   <td>13F-HR</td> ... href="/Archives/edgar/data/{cik}/{accNodashes}/..."
  //   with a date string YYYY-MM-DD somewhere in the row
  const rows = html.split(/<tr[\s>]/i);
  for (const row of rows) {
    if (results.length >= count) break;
    if (!/13F-HR/i.test(row)) continue;

    const accMatch = row.match(/\/Archives\/edgar\/data\/\d+\/([\d]{18,})\//);
    if (!accMatch) continue;

    const dateMatch = row.match(/(\d{4}-\d{2}-\d{2})/);
    if (!dateMatch) continue;

    results.push({ date: dateMatch[1], accNodashes: accMatch[1] });
  }

  // Fallback: try submissions JSON if browse-edgar returned nothing
  // (e.g. when the entity has no 13F-HR, this surfaces a clear empty result
  //  rather than masking the real problem with an HTML parse failure)
  if (results.length === 0) {
    const subUrl = `https://data.sec.gov/submissions/CIK${cik}.json`;
    try {
      const subRes = await secFetch(subUrl);
      if (subRes.ok) {
        const data = await subRes.json();
        const recent    = data?.filings?.recent ?? {};
        const forms     = recent.form            ?? [];
        const dates     = recent.filingDate      ?? [];
        const accs      = recent.accessionNumber ?? [];
        for (let i = 0; i < forms.length && results.length < count; i++) {
          if (forms[i] === "13F-HR") {
            results.push({
              date: dates[i],
              accNodashes: (accs[i] as string).replace(/-/g, ""),
            });
          }
        }
      }
    } catch { /* ignore */ }
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

  try {
    // Fetch the two most-recent 13F-HR filings
    const filings = await getRecentFilings(institution.cik, 2);
    if (filings.length === 0) {
      return NextResponse.json(
        { error: "No 13F-HR filings found for this institution" },
        { status: 404 }
      );
    }

    const cikInt = parseInt(institution.cik, 10);

    // Fetch current infotable
    const currentXml = await fetchInfotableXml(cikInt, filings[0].accNodashes);
    if (!currentXml) {
      return NextResponse.json(
        { error: "Could not retrieve holdings data from SEC EDGAR" },
        { status: 502 }
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

    return NextResponse.json(payload);
  } catch (err) {
    console.error(`13F API error for CIK ${cik}:`, err);
    return NextResponse.json(
      { error: "Failed to fetch SEC EDGAR data" },
      { status: 502 }
    );
  }
}
