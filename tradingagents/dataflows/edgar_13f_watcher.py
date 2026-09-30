"""
edgar_13f_watcher.py
Oasis Terminal — Institutional Holdings Intelligence

Polls SEC EDGAR for new 13F-HR filings from tracked institutions.
When a new filing is detected for a watched CIK, it:
  1. Fetches and parses the holdings XML
  2. Diffs against the stored prior quarter snapshot
  3. Outputs a structured alert (new positions, exits, adds, trims)

Usage:
  python edgar_13f_watcher.py              # check all watched CIKs
  python edgar_13f_watcher.py --cik 0001067983  # check single CIK

Cron (daily during filing windows):
  0 7 15-31 10 * python /path/to/edgar_13f_watcher.py
  0 7 1-14  11 * python /path/to/edgar_13f_watcher.py
"""

import argparse
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

WATCHED_CIKS = {
    "0001067983": "Berkshire Hathaway",
    "0001350694": "Bridgewater Associates",
    "0001336528": "Pershing Square (Ackman)",
    "0001167483": "Tiger Global Management",
    "0001603466": "Point72 Asset Management",
    "0001037389": "Renaissance Technologies",
    "0001423298": "Citadel Advisors",
    "0001649339": "Coatue Management",
    "0001569022": "Third Point (Loeb)",
    "0001418819": "D1 Capital Partners",
}

# Where to store prior quarter snapshots and the seen-filings log
DATA_DIR = Path(__file__).parent / "data" / "13f"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SEEN_FILE = DATA_DIR / "seen_filings.json"

EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{doc}"

HEADERS = {"User-Agent": "Oasis Terminal allan.yeung@gmail.com"}  # SEC requires a real User-Agent

# ─────────────────────────────────────────────────────────────
# SEEN FILINGS LOG
# ─────────────────────────────────────────────────────────────

def load_seen() -> dict:
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text())
    return {}

def save_seen(seen: dict):
    SEEN_FILE.write_text(json.dumps(seen, indent=2))

# ─────────────────────────────────────────────────────────────
# EDGAR — DETECT NEW FILINGS FOR A CIK
# ─────────────────────────────────────────────────────────────

def get_latest_13f(cik: str) -> dict | None:
    """
    Hit EDGAR submissions API for a CIK, return the most recent 13F-HR filing.
    Returns: { accession_number, filing_date, document_url } or None
    """
    url = EDGAR_SUBMISSIONS_URL.format(cik=cik.lstrip("0"))
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        print(f"  [WARN] Could not fetch submissions for CIK {cik}: {resp.status_code}")
        return None

    data = resp.json()
    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    accessions = filings.get("accessionNumber", [])
    dates = filings.get("filingDate", [])
    docs = filings.get("primaryDocument", [])

    for i, form in enumerate(forms):
        if form in ("13F-HR", "13F-HR/A"):
            return {
                "cik": cik,
                "form": form,
                "accession_number": accessions[i],
                "filing_date": dates[i],
                "primary_document": docs[i],
            }

    return None

# ─────────────────────────────────────────────────────────────
# EDGAR — FETCH AND PARSE HOLDINGS XML
# ─────────────────────────────────────────────────────────────

def fetch_holdings(cik: str, accession_number: str, primary_doc: str) -> list[dict]:
    """
    Fetch the 13F holdings XML from EDGAR and parse into a list of positions.
    Each position: { cusip, name, shares, value_usd, position_type }
    """
    accession_clean = accession_number.replace("-", "")
    cik_clean = cik.lstrip("0")

    # The primary doc is usually the index page — find the infotable XML
    index_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_clean}&type=13F-HR&dateb=&owner=include&count=1&search_text="

    # Directly construct the infotable URL (standard naming convention)
    # Try primary_doc first, then common fallback names
    for doc_name in [primary_doc, "infotable.xml", "form13fInfoTable.xml"]:
        doc_url = EDGAR_FILING_URL.format(
            cik=cik_clean,
            accession_clean=accession_clean,
            doc=doc_name
        )
        resp = requests.get(doc_url, headers=HEADERS, timeout=20)
        if resp.status_code == 200 and "<informationTable" in resp.text:
            return _parse_holdings_xml(resp.text)

    # Fallback: fetch the filing index to find the XML
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/{accession_clean}/{accession_number}-index.htm"
    resp = requests.get(index_url, headers=HEADERS, timeout=15)
    if resp.status_code == 200:
        # Find XML document link in the index
        match = re.search(r'href="([^"]+\.xml)"', resp.text, re.IGNORECASE)
        if match:
            xml_url = "https://www.sec.gov" + match.group(1)
            resp = requests.get(xml_url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return _parse_holdings_xml(resp.text)

    print(f"  [WARN] Could not fetch holdings XML for {accession_number}")
    return []


def _parse_holdings_xml(xml_text: str) -> list[dict]:
    """Parse 13F infotable XML into structured holdings list."""
    # Strip namespace for easier parsing
    xml_clean = re.sub(r' xmlns[^"]*"[^"]*"', '', xml_text)
    xml_clean = re.sub(r'<[^>]+:([^>]+)>', r'<\1>', xml_clean)

    try:
        root = ET.fromstring(xml_clean)
    except ET.ParseError as e:
        print(f"  [WARN] XML parse error: {e}")
        return []

    holdings = []
    for entry in root.findall(".//infoTable"):
        def get(tag):
            el = entry.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        shares_el = entry.find(".//sshPrnamt")
        shares = int(shares_el.text.strip()) if shares_el is not None and shares_el.text else 0
        value_el = entry.find("value")
        value = int(value_el.text.strip()) * 1000 if value_el is not None and value_el.text else 0  # 13F values in thousands

        holdings.append({
            "cusip": get("cusip"),
            "name": get("nameOfIssuer"),
            "shares": shares,
            "value_usd": value,
            "position_type": get("putCall") or "SH",  # SH=shares, PUT, CALL
        })

    return sorted(holdings, key=lambda x: x["value_usd"], reverse=True)

# ─────────────────────────────────────────────────────────────
# DIFF ENGINE
# ─────────────────────────────────────────────────────────────

def diff_holdings(current: list[dict], prior: list[dict]) -> dict:
    """
    Compare current quarter holdings against prior quarter.
    Returns: { new, exited, added, trimmed, unchanged }
    """
    current_map = {h["cusip"]: h for h in current}
    prior_map = {h["cusip"]: h for h in prior}

    new_positions = []
    exited = []
    added = []
    trimmed = []
    unchanged = []

    for cusip, curr in current_map.items():
        if cusip not in prior_map:
            new_positions.append(curr)
        else:
            prev = prior_map[cusip]
            if prev["shares"] == 0:
                new_positions.append(curr)
                continue
            change_pct = (curr["shares"] - prev["shares"]) / prev["shares"] * 100
            curr["shares_change_pct"] = round(change_pct, 1)
            curr["shares_prior"] = prev["shares"]
            curr["value_prior"] = prev["value_usd"]
            if change_pct >= 10:
                added.append(curr)
            elif change_pct <= -10:
                trimmed.append(curr)
            else:
                unchanged.append(curr)

    for cusip, prev in prior_map.items():
        if cusip not in current_map:
            exited.append(prev)

    return {
        "new_positions": sorted(new_positions, key=lambda x: x["value_usd"], reverse=True),
        "exited": sorted(exited, key=lambda x: x["value_usd"], reverse=True),
        "added": sorted(added, key=lambda x: x.get("shares_change_pct", 0), reverse=True),
        "trimmed": sorted(trimmed, key=lambda x: x.get("shares_change_pct", 0)),
        "unchanged_count": len(unchanged),
    }

# ─────────────────────────────────────────────────────────────
# ALERT FORMATTER
# ─────────────────────────────────────────────────────────────

def format_alert(institution: str, filing: dict, diff: dict) -> str:
    lines = [
        f"\n{'='*60}",
        f"📋  NEW 13F-HR: {institution}",
        f"    Filed: {filing['filing_date']} | Accession: {filing['accession_number']}",
        f"{'='*60}",
    ]

    if diff["new_positions"]:
        lines.append(f"\n🟢  NEW POSITIONS ({len(diff['new_positions'])})")
        for p in diff["new_positions"][:10]:
            lines.append(f"    + {p['name']:35s}  ${p['value_usd']:>14,.0f}  CUSIP:{p['cusip']}")

    if diff["exited"]:
        lines.append(f"\n🔴  EXITS ({len(diff['exited'])})")
        for p in diff["exited"][:10]:
            lines.append(f"    - {p['name']:35s}  ${p['value_usd']:>14,.0f}  (prior quarter)")

    if diff["added"]:
        lines.append(f"\n🔼  SIGNIFICANT ADDS ({len(diff['added'])})")
        for p in diff["added"][:10]:
            chg = p.get("shares_change_pct", 0)
            lines.append(f"    ▲ {p['name']:35s}  +{chg:5.1f}%  ${p['value_usd']:>12,.0f}")

    if diff["trimmed"]:
        lines.append(f"\n🔽  SIGNIFICANT TRIMS ({len(diff['trimmed'])})")
        for p in diff["trimmed"][:10]:
            chg = p.get("shares_change_pct", 0)
            lines.append(f"    ▼ {p['name']:35s}  {chg:6.1f}%  ${p['value_usd']:>12,.0f}")

    lines.append(f"\n    Unchanged positions: {diff['unchanged_count']}")
    lines.append(f"{'='*60}\n")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────
# SNAPSHOT STORAGE
# ─────────────────────────────────────────────────────────────

def load_prior_snapshot(cik: str) -> list[dict]:
    snap_file = DATA_DIR / f"{cik}_prior.json"
    if snap_file.exists():
        return json.loads(snap_file.read_text())
    return []

def save_snapshot(cik: str, holdings: list[dict]):
    snap_file = DATA_DIR / f"{cik}_prior.json"
    snap_file.write_text(json.dumps(holdings, indent=2))

# ─────────────────────────────────────────────────────────────
# MAIN — PROCESS A SINGLE CIK
# ─────────────────────────────────────────────────────────────

def process_cik(cik: str, institution: str, seen: dict) -> dict | None:
    print(f"\n[{institution}] Checking CIK {cik}...")

    filing = get_latest_13f(cik)
    if not filing:
        print(f"  No 13F found.")
        return None

    accession = filing["accession_number"]

    # Already processed this filing?
    if seen.get(cik) == accession:
        print(f"  Already processed {accession} (filed {filing['filing_date']})")
        return None

    print(f"  🆕 New filing: {accession} (filed {filing['filing_date']})")

    # Fetch current holdings
    current_holdings = fetch_holdings(cik, accession, filing["primary_document"])
    if not current_holdings:
        print(f"  [WARN] No holdings parsed.")
        return None

    print(f"  Parsed {len(current_holdings)} positions.")

    # Load prior snapshot and diff
    prior_holdings = load_prior_snapshot(cik)
    diff = diff_holdings(current_holdings, prior_holdings)

    # Format and print alert
    alert = format_alert(institution, filing, diff)
    print(alert)

    # Save results
    save_snapshot(cik, current_holdings)

    alert_file = DATA_DIR / f"{cik}_{accession.replace('-','_')}_alert.json"
    alert_file.write_text(json.dumps({
        "institution": institution,
        "cik": cik,
        "filing": filing,
        "diff": diff,
        "current_holdings": current_holdings,
        "generated_at": datetime.now().isoformat(),
    }, indent=2))

    return {"cik": cik, "accession": accession, "diff": diff}

# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Oasis 13F Watcher")
    parser.add_argument("--cik", help="Process a single CIK (optional)")
    parser.add_argument("--output-json", metavar="PATH",
                        help="Write machine-readable results to this JSON file (used by GitHub Actions)")
    args = parser.parse_args()

    seen = load_seen()
    results = []

    if args.cik:
        # Single CIK mode — triggered manually or by CI with a specific CIK
        cik = args.cik.zfill(10)
        institution = WATCHED_CIKS.get(cik, f"Unknown ({cik})")
        result = process_cik(cik, institution, seen)
        if result:
            seen[cik] = result["accession"]
            results.append(result)
    else:
        # Full scan — all watched CIKs
        for cik, institution in WATCHED_CIKS.items():
            result = process_cik(cik, institution, seen)
            if result:
                seen[cik] = result["accession"]
                results.append(result)

    save_seen(seen)

    # Write machine-readable output for GitHub Actions / downstream consumers
    if args.output_json:
        output = {
            "run_at": datetime.now().isoformat(),
            "new_filings": [
                {
                    "institution": WATCHED_CIKS.get(r["cik"], r["cik"]),
                    "cik": r["cik"],
                    "filing": {"accession_number": r["accession"],
                               "filing_date": r.get("filing_date", "")},
                    "diff": r["diff"],
                }
                for r in results
            ],
            "total_new": len(results),
        }
        Path(args.output_json).write_text(json.dumps(output, indent=2))
        print(f"  Results written to {args.output_json}")

    if results:
        print(f"\n✅  Processed {len(results)} new filing(s).")
    else:
        print(f"\n  No new filings found across watched institutions.")

if __name__ == "__main__":
    main()
