#!/usr/bin/env node
/**
 * verify-edgar-ciks.mjs
 *
 * Confirms what entity each CIK belongs to by hitting SEC EDGAR's submissions
 * JSON API.  Run this once to check for conflicts before adding new institutions.
 *
 * Usage: node scripts/verify-edgar-ciks.mjs
 */

const CHECK = [
  // Existing — verify no conflicts
  { cik: "0001109448", expectedName: "Viking Global Investors" },

  // New institutions to add
  { cik: "0000315066", expectedName: "Fidelity Management & Research / FMR LLC" },
  { cik: "0001535323", expectedName: "PIMCO" },
  { cik: "0000080255", expectedName: "T. Rowe Price Associates" },
  { cik: "0001214717", expectedName: "Geode Capital Management" },
  { cik: "0000902219", expectedName: "Wellington Management" },
  { cik: "0000354204", expectedName: "Dimensional Fund Advisors" },
  { cik: "0000914208", expectedName: "Invesco" },
  { cik: "0000038777", expectedName: "Franklin Resources" },
  { cik: "0001137774", expectedName: "PGIM / Prudential" },
  { cik: "0001390777", expectedName: "Mellon Investments / BNY Mellon" },
  { cik: "0000912938", expectedName: "Massachusetts Financial Services (MFS)" },
  { cik: "0001890906", expectedName: "Allspring Global Investments" },
  { cik: "0000861177", expectedName: "UBS Asset Management Americas" },
  { cik: "0001055964", expectedName: "Nomura Asset Management" },
  { cik: "0001512024", expectedName: "CAPTRUST / CapFinancial Partners" },
  { cik: "0001529735", expectedName: "MetLife Investment Management" },

  // CIKs needing verification (may conflict with existing entries or be wrong)
  { cik: "0002012383", expectedName: "BlackRock Inc" },
  { cik: "0001364742", expectedName: "BlackRock Inc (alternate?)" },
  { cik: "0000886982", expectedName: "Goldman Sachs Asset Management" },
  { cik: "0000895421", expectedName: "Morgan Stanley Investment Management" },
  { cik: "0001389418", expectedName: "Viking Global (alternate CIK?)" },
  { cik: "0000031235", expectedName: "Capital Group / Capital Research" },
  { cik: "0000072971", expectedName: "Neuberger Berman" },
  { cik: "0000029226", expectedName: "Dodge & Cox" },
  { cik: "0001459486", expectedName: "Arrowstreet Capital" },
  { cik: "0000873860", expectedName: "Fisher Investments" },
  { cik: "0000060714", expectedName: "Lord Abbett" },
  { cik: "0000055528", expectedName: "Jennison Associates" },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

console.log("\n🔍  SEC EDGAR CIK Verification\n");
console.log("CIK            | EDGAR Name                              | Expected");
console.log("─".repeat(90));

for (const { cik, expectedName } of CHECK) {
  const url = `https://data.sec.gov/submissions/${cik.replace(/^0+/, "CIK").padStart(13, "0")}.json`;
  // Correct URL format: CIK + zero-padded to 10 digits
  const paddedCik = cik.replace(/\D/g, "").padStart(10, "0");
  const apiUrl = `https://data.sec.gov/submissions/CIK${paddedCik}.json`;

  try {
    const res = await fetch(apiUrl, {
      headers: { "User-Agent": "TradingDesk/1.0 (research; contact: research@example.com)" },
    });
    if (!res.ok) {
      console.log(`${cik} | HTTP ${res.status}                                  | ${expectedName}`);
    } else {
      const data = await res.json();
      const name = data.name ?? "—";
      const match = name.toLowerCase().includes(expectedName.split(" ")[0].toLowerCase());
      const flag = match ? "✅" : "⚠️ ";
      console.log(`${cik} | ${name.padEnd(40)} | ${flag} ${expectedName}`);
    }
  } catch (e) {
    console.log(`${cik} | ERROR: ${e.message.slice(0, 35).padEnd(40)} | ${expectedName}`);
  }

  await sleep(200); // stay under SEC rate limit
}

console.log("\n✨  Done. Check ⚠️  rows — the CIK maps to a different entity than expected.\n");
