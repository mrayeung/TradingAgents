# Oasis Terminal — Institutional Holdings Intelligence (13F Watcher)

**Feature:** Automated 13F-HR Filing Detection & Holdings Diff Engine  
**Module:** `trading_desk/scripts/edgar_13f_watcher.py`  
**Status:** Active Development  
**Last Updated:** 2026-09-29

---

## Overview

The 13F Watcher is an event-driven automation layer that monitors the SEC EDGAR database for new quarterly institutional holdings disclosures (Form 13F-HR). When a new filing drops for any tracked institution, the watcher automatically:

1. Detects the new filing via the EDGAR Submissions API
2. Fetches and parses the holdings XML table
3. Diffs against the prior quarter's snapshot
4. Outputs a structured alert — new positions, exits, significant adds/trims

This powers the **Institutional Portfolios** module in the TradingDesk GUI (`/institutional`), which displays: *"Live 13F-HR holdings from SEC EDGAR · updated quarterly."*

---

## What is a 13F-HR?

SEC Form 13F-HR is a mandatory quarterly disclosure for institutional investment managers with $100M+ in assets under management. It reports every equity position held at quarter-end.

**Key facts:**
- Covers long equity positions only (no short positions, no bonds, no cash)
- Reported at quarter-end, filed 45 days after quarter-end
- Filed electronically on EDGAR — publicly available and machine-readable

**Filing deadlines:**

| Quarter End | Filing Deadline |
|-------------|-----------------|
| March 31    | May 15          |
| June 30     | August 14       |
| September 30| November 14     |
| December 31 | February 14     |

**Important:** Not all institutions file on the same day. Filings trickle in over the 45-day window. The watcher runs daily during each filing window to catch new filings as they appear.

---

## What is a CIK?

**CIK (Central Index Key)** is the unique, permanent identifier EDGAR assigns to every filer. It never changes. All filings from an institution are indexed under its CIK.

The watcher uses CIK as the primary key to:
- Track which institutions to watch
- Store per-institution state (last seen accession number)
- Trigger single-institution processing when called by cron with `--cik`

**Finding a CIK:** Search at `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=berkshire&CIK=&type=13F-HR`

### Currently Tracked Institutions

| Institution | CIK |
|-------------|-----|
| Berkshire Hathaway | 0001067983 |
| Bridgewater Associates | 0001350694 |
| Pershing Square (Ackman) | 0001336528 |
| Tiger Global Management | 0001167483 |
| Point72 Asset Management | 0001603466 |
| Renaissance Technologies | 0001037389 |
| Citadel Advisors | 0001423298 |
| Coatue Management | 0001649339 |
| Third Point (Loeb) | 0001569022 |
| D1 Capital Partners | 0001418819 |

Add new institutions in `WATCHED_CIKS` dict at the top of `edgar_13f_watcher.py`.

---

## Architecture

```
EDGAR EFTS / Submissions API
          │
          ▼
┌─────────────────────┐
│  edgar_13f_watcher  │  ← polls daily via cron during filing windows
│  .py                │
└─────────┬───────────┘
          │ new accession detected for CIK
          ▼
┌─────────────────────┐
│  fetch_holdings()   │  ← downloads XML infotable from EDGAR
└─────────┬───────────┘
          │ list[dict] of positions
          ▼
┌─────────────────────┐
│  diff_holdings()    │  ← compares vs prior quarter JSON snapshot
└─────────┬───────────┘
          │ { new, exited, added, trimmed, unchanged }
          ▼
┌─────────────────────┐
│  Alert output       │  → terminal print (current)
│                     │  → JSON alert file in data/13f/
│                     │  → TradingDesk GUI feed (future)
└─────────────────────┘
```

### State Files

All state lives in `trading_desk/data/13f/`:

| File | Purpose |
|------|---------|
| `seen_filings.json` | Maps CIK → last processed accession number. Prevents reprocessing. |
| `{cik}_prior.json` | Prior quarter holdings snapshot for a given institution. Used for diffing. |
| `{cik}_{accession}_alert.json` | Structured diff output — archived per filing. |

---

## Usage

### Manual Run (all institutions)
```bash
cd /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk
python scripts/edgar_13f_watcher.py
```

### Single CIK (manual or triggered by cron)
```bash
python scripts/edgar_13f_watcher.py --cik 0001067983
```

### First Run Behavior
On first run, there are no prior-quarter snapshots in `data/13f/`. The diff engine will classify every position as "new" since there's nothing to compare against. After the first successful run, subsequent runs will produce meaningful diffs.

To bootstrap with historical data: manually download a prior quarter's 13F XML from EDGAR and run `python scripts/bootstrap_snapshot.py --cik {cik} --accession {accession}` (future utility).

---

## Cron Setup

The filing windows are: mid-October through mid-November (Q3), mid-January through mid-February (Q4), mid-April through mid-May (Q1), mid-July through mid-August (Q2).

Add these to `crontab -e` (checks daily at 7am during each filing window):

```cron
# Q1 filings (April 15 – May 15)
0 7 15-30 4 * /usr/bin/python3 /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/scripts/edgar_13f_watcher.py >> /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/logs/13f_watcher.log 2>&1
0 7 1-15  5 * /usr/bin/python3 /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/scripts/edgar_13f_watcher.py >> /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/logs/13f_watcher.log 2>&1

# Q2 filings (July 15 – August 14)
0 7 15-31 7 * /usr/bin/python3 /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/scripts/edgar_13f_watcher.py >> /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/logs/13f_watcher.log 2>&1
0 7 1-14  8 * /usr/bin/python3 /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/scripts/edgar_13f_watcher.py >> /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/logs/13f_watcher.log 2>&1

# Q3 filings (October 15 – November 14)
0 7 15-31 10 * /usr/bin/python3 /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/scripts/edgar_13f_watcher.py >> /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/logs/13f_watcher.log 2>&1
0 7 1-14  11 * /usr/bin/python3 /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/scripts/edgar_13f_watcher.py >> /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/logs/13f_watcher.log 2>&1

# Q4 filings (January 15 – February 14)
0 7 15-31 1 * /usr/bin/python3 /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/scripts/edgar_13f_watcher.py >> /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/logs/13f_watcher.log 2>&1
0 7 1-14  2 * /usr/bin/python3 /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/scripts/edgar_13f_watcher.py >> /Volumes/SSD_Dock/Projects/TradingDesk-preview/trading_desk/logs/13f_watcher.log 2>&1
```

### Alternative: macOS LaunchAgent (more reliable than cron on Mac)

Create `~/Library/LaunchAgents/com.oasis.13f-watcher.plist` — runs daily at 7am.
(Future: add LaunchAgent plist to repo as `trading_desk/config/com.oasis.13f-watcher.plist`)

---

## Diff Engine — Classification Logic

Positions are classified by comparing share count quarter-over-quarter:

| Change | Classification | Threshold |
|--------|---------------|-----------|
| CUSIP not in prior | New Position | — |
| CUSIP not in current | Exit | — |
| Shares up ≥ 10% | Significant Add | ≥ +10% |
| Shares down ≥ 10% | Significant Trim | ≤ -10% |
| Within ±10% | Unchanged | — |

The 10% threshold filters noise from routine rebalancing. Large adds/trims represent meaningful conviction shifts.

---

## Alert Output Format

```
============================================================
📋  NEW 13F-HR: Berkshire Hathaway
    Filed: 2026-08-14 | Accession: 0001067983-26-000999
============================================================

🟢  NEW POSITIONS (2)
    + Domino's Pizza Inc                   $   1,200,000,000  CUSIP:25754A201
    + Sirius XM Holdings Inc               $     800,000,000  CUSIP:82968B103

🔴  EXITS (1)
    - Paramount Global                     $     150,000,000  (prior quarter)

🔼  SIGNIFICANT ADDS (3)
    ▲ Apple Inc                            +15.2%  $ 158,000,000,000
    ▲ Occidental Petroleum                 +12.1%  $  14,500,000,000
    ▲ Chevron Corp                         +10.8%  $  19,000,000,000

🔽  SIGNIFICANT TRIMS (1)
    ▼ HP Inc                               -22.4%  $   1,800,000,000

    Unchanged positions: 38
============================================================
```

---

## EDGAR API Reference

**Submissions API** (primary — paginated, recent filings only):
```
GET https://data.sec.gov/submissions/CIK{cik_no_leading_zeros}.json
```
Returns all recent filings with form type, accession number, filing date, and primary document.

**Full-Text Search API** (alternative — real-time detection):
```
GET https://efts.sec.gov/LATEST/search-index?q=%2213F-HR%22&dateRange=custom&startdt={today}&enddt={today}&forms=13F-HR
```
Can detect filings the same day they're indexed.

**Holdings XML** (after accession known):
```
https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodashes}/infotable.xml
```

**SEC Rate Limit:** Max 10 requests/second. The watcher is designed for daily batch runs, not real-time scraping. Always include a `User-Agent` header with a real email address per SEC fair-access guidelines.

---

## File Structure

```
trading_desk/
├── scripts/
│   └── edgar_13f_watcher.py        ← main watcher + diff engine
├── data/
│   └── 13f/
│       ├── seen_filings.json        ← CIK → last accession (state)
│       ├── {cik}_prior.json         ← prior quarter snapshot per CIK
│       └── {cik}_{accession}_alert.json  ← archived diff output
└── logs/
    └── 13f_watcher.log              ← cron output log
```

---

## Known Limitations

- **45-day lag:** 13F data is 45 days stale by the time it's filed. This is a regulatory constraint, not a technical one. Use it for pattern recognition and conviction mapping, not for trade timing.
- **Long-only:** 13Fs only show equity longs. Short books, derivatives (except some options), and non-US holdings may be omitted or reported differently.
- **Amended filings:** Form 13F-HR/A is an amendment to a prior filing. The watcher captures these but the diff may be partial. Future: detect amendments and re-diff against the original.
- **XML format variance:** Some filers use slightly non-standard XML structures. The parser handles the two most common formats with namespace stripping and fallback index parsing.
- **No GUI integration yet:** Alert output currently goes to terminal + JSON files. Next phase: feed into TradingDesk API endpoint for the Institutional Portfolios dashboard.

---

## Roadmap

- [ ] LaunchAgent plist for macOS background scheduling
- [ ] Bootstrap utility to seed prior-quarter snapshots from historical filings
- [ ] REST API endpoint in `desk_server` to serve diff data to the GUI
- [ ] Cross-reference diff against Portfolio Manager holdings and Trading Desk watchlist
- [ ] Email/push notification on new filing detection
- [ ] Amendment (13F-HR/A) handling with re-diff against original
- [ ] Aggregate view: which positions appear across multiple tracked institutions (conviction clusters)

---

## Dependencies

```
requests          # HTTP — already in TradingAgents requirements.txt
xml.etree         # stdlib — no install needed
pathlib           # stdlib
json              # stdlib
```

No additional packages needed beyond what's already in the project.
