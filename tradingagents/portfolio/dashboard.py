"""Live HTML dashboard for the Portfolio Construction pipeline.

Opens a self-refreshing page in the default browser that updates as each
pipeline stage completes. Styled in a Robinhood-inspired dark theme with
Chart.js for the screener ranking chart and portfolio weight donut.

Usage (handled automatically by PortfolioGraph):
    dash = PortfolioDashboard(output_dir, trade_date)
    dash.open_browser()
    dash.update_screener(passed, filtered)        # → screener tab populates
    dash.pause_for_input()                        # → terminal: press Enter
    dash.update_ticker_start(ticker, i, n)        # → card goes yellow
    dash.update_ticker_done(ticker, rating, md)   # → card goes green
    dash.update_portfolio(view)                   # → portfolio tab populates
    dash.update_rebalance(rec)                    # → rebalance tab populates
    dash.finalize()                               # → auto-refresh disabled
"""

from __future__ import annotations

import json
import os
import webbrowser
from datetime import datetime
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# CSS — Robinhood-inspired dark theme
# ---------------------------------------------------------------------------
_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
    --bg:        #0a0e0a;
    --surface:   #111611;
    --card:      #161e16;
    --border:    #1e2d1e;
    --green:     #00d632;
    --green-dim: #00a828;
    --red:       #ff5000;
    --yellow:    #f5a623;
    --blue:      #4f9cf9;
    --text:      #eaf4ea;
    --sub:       #7a9a7a;
    --pill-buy:  rgba(0,214,50,.15);
    --pill-ow:   rgba(79,156,249,.15);
    --pill-hold: rgba(245,166,35,.15);
    --pill-uw:   rgba(255,80,0,.15);
    --pill-sell: rgba(255,80,0,.25);
}

body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif;
    display: flex;
    height: 100vh;
    overflow: hidden;
    font-size: 14px;
}

/* ── Sidebar ─────────────────────────────────────────────────────────── */
.sidebar {
    width: 220px;
    min-width: 220px;
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 0;
}
.logo {
    padding: 24px 20px 16px;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: var(--green);
    border-bottom: 1px solid var(--border);
}
.logo span { color: var(--text); }
.trade-date {
    padding: 8px 20px 12px;
    font-size: 11px;
    color: var(--sub);
    border-bottom: 1px solid var(--border);
}
nav { flex: 1; padding: 12px 0; overflow-y: auto; }
.tab-btn {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 11px 20px;
    background: none;
    border: none;
    color: var(--sub);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    text-align: left;
    transition: all .15s;
    position: relative;
}
.tab-btn:hover { color: var(--text); background: rgba(255,255,255,.03); }
.tab-btn.active {
    color: var(--green);
    background: rgba(0,214,50,.06);
}
.tab-btn.active::before {
    content: '';
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 3px;
    background: var(--green);
    border-radius: 0 2px 2px 0;
}
.tab-icon { font-size: 16px; width: 20px; text-align: center; }
.tab-badge {
    margin-left: auto;
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 10px;
    font-weight: 600;
}
.badge-done  { background: var(--pill-buy);  color: var(--green); }
.badge-run   { background: var(--pill-hold); color: var(--yellow); }
.badge-wait  { background: rgba(255,255,255,.05); color: var(--sub); }

.sidebar-footer {
    padding: 16px 20px;
    border-top: 1px solid var(--border);
    font-size: 11px;
    color: var(--sub);
}
.stage-pill {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 600;
    margin-top: 4px;
    background: rgba(0,214,50,.12);
    color: var(--green);
}

/* ── Main content ───────────────────────────────────────────────────── */
.content {
    flex: 1;
    overflow-y: auto;
    padding: 28px 32px;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
}
.panel { display: none; }
.panel.active { display: block; }

/* ── Headers ────────────────────────────────────────────────────────── */
.panel-header {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 24px;
}
.panel-title {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.4px;
}
.panel-sub { font-size: 13px; color: var(--sub); }

/* ── Stat cards ─────────────────────────────────────────────────────── */
.stats-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
}
.stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
}
.stat-label { font-size: 11px; color: var(--sub); text-transform: uppercase; letter-spacing: .5px; }
.stat-value { font-size: 24px; font-weight: 700; margin-top: 4px; }
.stat-value.green { color: var(--green); }
.stat-value.red   { color: var(--red); }
.stat-value.yellow { color: var(--yellow); }

/* ── Chart container ────────────────────────────────────────────────── */
.chart-wrap {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px 24px;
    margin-bottom: 20px;
    position: relative;
}
.chart-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--sub);
    text-transform: uppercase;
    letter-spacing: .5px;
    margin-bottom: 16px;
}
.chart-container { position: relative; }

/* ── Two-column layout ──────────────────────────────────────────────── */
.two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
}
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }

/* ── Table ──────────────────────────────────────────────────────────── */
.data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
.data-table th {
    text-align: left;
    padding: 8px 12px;
    color: var(--sub);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .5px;
    border-bottom: 1px solid var(--border);
}
.data-table td {
    padding: 10px 12px;
    border-bottom: 1px solid rgba(30,45,30,.6);
}
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: rgba(255,255,255,.02); }

/* ── Rating pills ───────────────────────────────────────────────────── */
.pill {
    display: inline-block;
    padding: 3px 9px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .3px;
}
.pill-buy       { background: var(--pill-buy);  color: var(--green); }
.pill-overweight { background: var(--pill-ow);  color: var(--blue); }
.pill-hold      { background: var(--pill-hold); color: var(--yellow); }
.pill-underweight { background: var(--pill-uw); color: var(--red); }
.pill-sell      { background: var(--pill-sell); color: var(--red); }
.pill-pending   { background: rgba(255,255,255,.06); color: var(--sub); }
.pill-running   { background: rgba(245,166,35,.2); color: var(--yellow); }
.pill-failed    { background: rgba(255,80,0,.15); color: var(--red); }

/* ── Research grid ──────────────────────────────────────────────────── */
.ticker-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 10px;
    margin-bottom: 24px;
}
.ticker-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px;
    transition: border-color .2s;
}
.ticker-card.running {
    border-color: var(--yellow);
    box-shadow: 0 0 12px rgba(245,166,35,.15);
}
.ticker-card.complete { border-color: rgba(0,214,50,.25); }
.ticker-card.failed   { border-color: rgba(255,80,0,.2); }
.ticker-sym { font-size: 15px; font-weight: 700; margin-bottom: 6px; }
.ticker-status { font-size: 11px; color: var(--sub); margin-bottom: 6px; }
.ticker-elapsed { font-size: 11px; color: var(--sub); }

/* ── Report viewer ──────────────────────────────────────────────────── */
.report-controls {
    display: flex;
    gap: 12px;
    align-items: center;
    margin-bottom: 20px;
}
.report-select {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 8px 14px;
    font-size: 13px;
    cursor: pointer;
    outline: none;
    min-width: 200px;
}
.report-select:focus { border-color: var(--green); }
.report-body {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 28px 32px;
    max-height: calc(100vh - 220px);
    overflow-y: auto;
    line-height: 1.7;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
}
/* Markdown rendering styles */
.report-body h1 { font-size: 20px; font-weight: 700; margin-bottom: 8px; color: var(--text); }
.report-body h2 { font-size: 15px; font-weight: 700; margin: 20px 0 8px; color: var(--green); padding-bottom: 4px; border-bottom: 1px solid var(--border); }
.report-body h3 { font-size: 13px; font-weight: 700; margin: 14px 0 6px; color: var(--yellow); }
.report-body p  { margin-bottom: 10px; color: var(--text); }
.report-body hr { border: none; border-top: 1px solid var(--border); margin: 16px 0; }
.report-body strong { color: var(--text); font-weight: 700; }
.report-body blockquote { border-left: 3px solid var(--green); padding-left: 12px; margin: 8px 0; color: var(--sub); }
.report-body table { width: 100%; border-collapse: collapse; margin: 12px 0; }
.report-body th { border-bottom: 1px solid var(--border); padding: 6px 10px; text-align: left; font-size: 11px; color: var(--sub); }
.report-body td { padding: 6px 10px; border-bottom: 1px solid rgba(30,45,30,.5); }
.report-body code { background: rgba(255,255,255,.06); padding: 1px 5px; border-radius: 4px; font-size: 12px; }

/* ── Progress bar ───────────────────────────────────────────────────── */
.progress-bar-wrap {
    background: rgba(255,255,255,.06);
    border-radius: 6px;
    height: 6px;
    margin: 8px 0 4px;
    overflow: hidden;
}
.progress-bar-fill {
    height: 100%;
    background: var(--green);
    border-radius: 6px;
    transition: width .4s ease;
}

/* ── Correlation heatmap ─────────────────────────────────────────────── */
.corr-wrap {
    overflow-x: auto;
    margin-bottom: 20px;
}
.corr-table {
    border-collapse: separate;
    border-spacing: 2px;
    font-size: 11px;
}
.corr-table th {
    padding: 4px 6px;
    color: var(--sub);
    font-weight: 600;
    text-align: center;
    white-space: nowrap;
    font-size: 10px;
}
.corr-table th.row-label {
    text-align: right;
    padding-right: 8px;
    font-size: 10px;
    color: var(--text);
}
.corr-cell {
    width: 46px;
    height: 34px;
    text-align: center;
    vertical-align: middle;
    border-radius: 4px;
    font-weight: 600;
    font-size: 10px;
    transition: opacity .15s;
    cursor: default;
}
.corr-cell:hover { opacity: .8; }
.corr-legend {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 10px;
    font-size: 11px;
    color: var(--sub);
}
.corr-legend-bar {
    flex: 1;
    max-width: 200px;
    height: 8px;
    border-radius: 4px;
    background: linear-gradient(to right,
        rgba(255,80,0,.85) 0%,
        rgba(255,80,0,.2) 35%,
        rgba(255,255,255,.06) 50%,
        rgba(0,214,50,.2) 65%,
        rgba(0,214,50,.85) 100%);
}

/* ── No-data placeholder ────────────────────────────────────────────── */
.placeholder {
    text-align: center;
    padding: 60px 20px;
    color: var(--sub);
}
.placeholder-icon { font-size: 40px; margin-bottom: 12px; }
.placeholder-text { font-size: 14px; }

/* ── Scrollbar ──────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
"""

# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------
_JS = """
const D = window.__DATA__;

// ── Tab switching ─────────────────────────────────────────────────────
function showTab(id) {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    const panel = document.getElementById('panel-' + id);
    if (panel) panel.classList.add('active');
    const btn = document.getElementById('tab-' + id);
    if (btn) btn.classList.add('active');
}

// ── Rating pill helper ────────────────────────────────────────────────
function ratingPill(r) {
    if (!r || r === '—') return `<span class="pill pill-pending">—</span>`;
    const key = r.toLowerCase().replace(/\\s+/g,'');
    const cls = {buy:'pill-buy', overweight:'pill-overweight', hold:'pill-hold',
                 underweight:'pill-underweight', sell:'pill-sell',
                 pending:'pill-pending', running:'pill-running', failed:'pill-failed'}[key] || 'pill-pending';
    return `<span class="pill ${cls}">${r}</span>`;
}

function fmtPct(v) { return v != null ? (v * 100).toFixed(1) + '%' : '—'; }
function fmtNum(v, d=2) { return v != null ? v.toFixed(d) : '—'; }

// ── Screener tab ──────────────────────────────────────────────────────
function renderScreener() {
    const s = D.screener;
    if (!s || !s.passed || s.passed.length === 0) {
        document.getElementById('screener-content').innerHTML =
            `<div class="placeholder"><div class="placeholder-icon">📊</div>
             <div class="placeholder-text">Screener results will appear here once the screener runs.</div></div>`;
        return;
    }

    const passed   = s.passed;
    const filtered = s.filtered || [];
    const all      = [...passed, ...filtered];
    const cut      = passed.length;

    // Stats
    document.getElementById('screener-stat-universe').textContent = s.n_universe || all.length;
    document.getElementById('screener-stat-passed').textContent   = passed.length;
    document.getElementById('screener-stat-filtered').textContent = filtered.length;

    // ── Screener ranking chart ────────────────────────────────────────
    const chartData = [...passed, ...filtered.slice(0, 20)]
        .sort((a,b) => (b.composite_score||0) - (a.composite_score||0));

    const labels  = chartData.map(r => r.ticker);
    const scores  = chartData.map(r => r.composite_score != null ? +r.composite_score.toFixed(3) : 0);
    const colors  = chartData.map((r,i) => i < cut ? 'rgba(0,214,50,0.75)' : 'rgba(122,154,122,0.35)');
    const borders = chartData.map((r,i) => i < cut ? 'rgba(0,214,50,1)' : 'rgba(122,154,122,0.5)');

    const ctx = document.getElementById('screener-chart').getContext('2d');
    if (window._screenerChart) window._screenerChart.destroy();
    window._screenerChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Composite Score',
                data: scores,
                backgroundColor: colors,
                borderColor: borders,
                borderWidth: 1,
                borderRadius: 3,
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const r = chartData[ctx.dataIndex];
                            const tag = ctx.dataIndex < cut ? '✓ SELECTED' : '✗ filtered';
                            return [
                                ` Score: ${ctx.parsed.x.toFixed(3)}  ${tag}`,
                                ` Quality: ${fmtNum(r.quality_score)} | Growth: ${fmtNum(r.growth_score)}`,
                                ` Valuation: ${fmtNum(r.valuation_score)} | Momentum: ${fmtNum(r.momentum_score)}`,
                                ` Analyst: ${fmtNum(r.analyst_score)}`,
                            ];
                        }
                    },
                    backgroundColor: '#1c2a1c',
                    borderColor: '#2a3d2a',
                    borderWidth: 1,
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255,255,255,.04)' },
                    ticks: { color: '#7a9a7a', font: { size: 11 } }
                },
                y: {
                    grid: { display: false },
                    ticks: { color: ctx => {
                        const idx = labels.indexOf(ctx.tick.label);
                        return idx < cut ? '#eaf4ea' : '#4a6a4a';
                    }, font: { size: 11, weight: ctx => {
                        const idx = labels.indexOf(ctx.tick.label);
                        return idx < cut ? '700' : '400';
                    }}},
                }
            },
            // Draw cut-off annotation line
            animation: { onComplete: (anim) => drawCutLine(anim.chart, cut) },
        },
        plugins: [{
            id: 'cutLine',
            afterDraw: chart => drawCutLine(chart, cut)
        }]
    });
}

function drawCutLine(chart, cut) {
    if (cut <= 0 || cut >= chart.data.labels.length) return;
    const meta = chart.getDatasetMeta(0);
    if (!meta.data[cut]) return;
    const y = (meta.data[cut - 1].y + meta.data[cut].y) / 2;
    const { ctx, chartArea: { left, right } } = chart;
    ctx.save();
    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = 'rgba(0,214,50,0.5)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
    ctx.fillStyle = 'rgba(0,214,50,0.8)';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.fillText('▲ Top ' + cut + ' selected', right - 90, y - 4);
    ctx.restore();
}

// ── Factor score table for screener ──────────────────────────────────
function renderScreenerTable() {
    const s = D.screener;
    if (!s || !s.passed) return;
    const all = [...(s.passed||[]), ...(s.filtered||[])];
    const rows = all.map(r => `
        <tr>
            <td><strong>${r.ticker}</strong></td>
            <td>${r.passed_hard_filters ? '<span class="pill pill-buy">✓</span>' : '<span class="pill pill-sell">✗</span>'}</td>
            <td>${fmtNum(r.composite_score,3)}</td>
            <td>${fmtNum(r.quality_score,3)}</td>
            <td>${fmtNum(r.growth_score,3)}</td>
            <td>${fmtNum(r.valuation_score,3)}</td>
            <td>${fmtNum(r.momentum_score,3)}</td>
            <td>${fmtNum(r.analyst_score,3)}</td>
            <td style="color:var(--sub);font-size:11px">${r.filter_reason||''}</td>
        </tr>`).join('');
    document.getElementById('screener-table-body').innerHTML = rows;
}

// ── Research tab ──────────────────────────────────────────────────────
function renderResearch() {
    const a = D.analysis;
    if (!a || !a.tickers || Object.keys(a.tickers).length === 0) {
        document.getElementById('research-content').innerHTML =
            `<div class="placeholder"><div class="placeholder-icon">🔬</div>
             <div class="placeholder-text">Analysis will begin after screener completes.</div></div>`;
        return;
    }

    const total = a.total || 0;
    const done  = a.complete || 0;
    const pct   = total > 0 ? (done / total * 100) : 0;

    document.getElementById('research-stat-done').textContent    = done;
    document.getElementById('research-stat-total').textContent   = total;
    document.getElementById('research-stat-running').textContent =
        Object.values(a.tickers).filter(t => t.status === 'running').length;
    document.getElementById('research-progress-fill').style.width = pct + '%';
    document.getElementById('research-pct').textContent = pct.toFixed(0) + '%';

    const cards = Object.entries(a.tickers).map(([sym, t]) => {
        const cls   = t.status === 'running' ? 'running' : t.status === 'complete' ? 'complete' : t.status === 'failed' ? 'failed' : '';
        const badge = t.status === 'complete' ? ratingPill(t.rating || '—') : ratingPill(t.status);
        const secs  = t.elapsed ? `${t.elapsed.toFixed(0)}s` : '';
        return `<div class="ticker-card ${cls}">
            <div class="ticker-sym">${sym}</div>
            <div>${badge}</div>
            <div class="ticker-elapsed" style="margin-top:6px">${secs}</div>
        </div>`;
    }).join('');
    document.getElementById('ticker-grid').innerHTML = cards;
}

// ── Reports tab ───────────────────────────────────────────────────────
function renderReports() {
    const a = D.analysis;
    const select = document.getElementById('report-select');
    const body   = document.getElementById('report-body');
    const done   = Object.entries((a && a.tickers) || {})
                         .filter(([,t]) => t.status === 'complete' && t.report_md)
                         .map(([sym]) => sym);
    // Populate dropdown
    const prev = select.value;
    select.innerHTML = '<option value="">— Select a stock —</option>' +
        done.map(sym => `<option value="${sym}">${sym}</option>`).join('');
    if (prev && done.includes(prev)) select.value = prev;

    if (!select.value) {
        body.innerHTML = `<div class="placeholder"><div class="placeholder-icon">📄</div>
            <div class="placeholder-text">Select a stock above to view its full research report.</div></div>`;
        return;
    }
    const md = a.tickers[select.value]?.report_md || '';
    body.innerHTML = marked.parse ? marked.parse(md) : marked(md);
}

function onReportSelect() {
    renderReports();
}

// ── Portfolio tab ─────────────────────────────────────────────────────
function renderPortfolio() {
    const p = D.portfolio;
    if (!p || !p.holdings || p.holdings.length === 0) {
        document.getElementById('portfolio-content').innerHTML =
            `<div class="placeholder"><div class="placeholder-icon">💼</div>
             <div class="placeholder-text">Portfolio view will appear after construction completes.</div></div>`;
        return;
    }

    const holdings = [...p.holdings].sort((a,b) => b.target_weight - a.target_weight);
    const cash     = p.cash_weight || 0;
    const invested = holdings.reduce((s,h) => s + h.target_weight, 0);

    // Stats
    document.getElementById('port-stat-holdings').textContent = holdings.length;
    document.getElementById('port-stat-invested').textContent  = fmtPct(invested);
    document.getElementById('port-stat-cash').textContent      = fmtPct(cash);

    // ── Donut chart ───────────────────────────────────────────────────
    const PALETTE = [
        '#00d632','#4f9cf9','#f5a623','#ff5000','#a78bfa',
        '#34d399','#fb923c','#60a5fa','#f472b6','#facc15',
        '#818cf8','#2dd4bf','#fb7185','#a3e635','#38bdf8',
    ];
    const donut_labels = [...holdings.map(h=>h.ticker), 'CASH'];
    const donut_data   = [...holdings.map(h=>h.target_weight*100), cash*100];
    const donut_colors = [...holdings.map((_,i)=>PALETTE[i%PALETTE.length]), 'rgba(255,255,255,.1)'];

    const dctx = document.getElementById('weight-donut').getContext('2d');
    if (window._donutChart) window._donutChart.destroy();
    window._donutChart = new Chart(dctx, {
        type: 'doughnut',
        data: { labels: donut_labels, datasets: [{ data: donut_data, backgroundColor: donut_colors, borderWidth: 0, hoverOffset: 6 }] },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '62%',
            plugins: {
                legend: { position: 'right', labels: { color: '#7a9a7a', font: { size: 11 }, padding: 10, boxWidth: 12 } },
                tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%` },
                    backgroundColor: '#1c2a1c', borderColor: '#2a3d2a', borderWidth: 1 }
            }
        }
    });

    // ── Sector chart ──────────────────────────────────────────────────
    const sw = p.sector_weights || {};
    if (Object.keys(sw).length) {
        const sLabels = Object.keys(sw).sort((a,b) => sw[b]-sw[a]);
        const sData   = sLabels.map(k => +(sw[k]*100).toFixed(1));
        const sctx    = document.getElementById('sector-chart').getContext('2d');
        if (window._sectorChart) window._sectorChart.destroy();
        window._sectorChart = new Chart(sctx, {
            type: 'bar',
            data: { labels: sLabels, datasets: [{ data: sData, backgroundColor: 'rgba(0,214,50,0.6)', borderColor: 'rgba(0,214,50,1)', borderWidth: 1, borderRadius: 4 }] },
            options: {
                indexAxis: 'y',
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false },
                    tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.x.toFixed(1)}%` },
                        backgroundColor: '#1c2a1c', borderColor: '#2a3d2a', borderWidth: 1 }},
                scales: {
                    x: { grid: { color: 'rgba(255,255,255,.04)' }, ticks: { color: '#7a9a7a', callback: v => v + '%' } },
                    y: { grid: { display: false }, ticks: { color: '#eaf4ea', font: { size: 11 } } }
                }
            }
        });
    }

    // ── Holdings table ────────────────────────────────────────────────
    const rows = holdings.map((h,i) => {
        const color = PALETTE[i % PALETTE.length];
        return `<tr>
            <td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:6px;vertical-align:middle"></span><strong>${h.ticker}</strong></td>
            <td>${ratingPill(h.rating)}</td>
            <td style="font-weight:700;color:var(--green)">${fmtPct(h.target_weight)}</td>
            <td><span class="pill ${h.conviction==='High'?'pill-buy':h.conviction==='Medium'?'pill-overweight':'pill-hold'}">${h.conviction||'—'}</span></td>
            <td>${h.price_target ? '$' + h.price_target.toFixed(0) : '—'}</td>
            <td style="color:var(--sub);font-size:11px">${h.time_horizon||'—'}</td>
            <td style="color:var(--sub);font-size:11px;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(h.investment_thesis||'').replace(/"/g,"'")}">${h.investment_thesis||''}</td>
        </tr>`;
    }).join('');
    document.getElementById('holdings-table-body').innerHTML = rows;

    // Rationale text
    if (p.construction_rationale) {
        document.getElementById('port-rationale').textContent = p.construction_rationale;
        document.getElementById('port-overweights').textContent = p.top_overweights || '';
        document.getElementById('port-underweights').textContent = p.top_underweights || '';
    }
}

// ── Rebalance tab ─────────────────────────────────────────────────────
function renderRebalance() {
    const r = D.rebalance;
    if (!r || !r.trades || r.trades.length === 0) {
        document.getElementById('rebalance-content').innerHTML =
            `<div class="placeholder"><div class="placeholder-icon">🔄</div>
             <div class="placeholder-text">Rebalance recommendations will appear here if current holdings were provided.</div></div>`;
        return;
    }
    document.getElementById('reb-stat-trades').textContent    = r.trades.filter(t=>t.action!=='Hold').length;
    document.getElementById('reb-stat-turnover').textContent  = fmtPct(r.rebalance_turnover);
    document.getElementById('reb-stat-new').textContent       = (r.new_positions||[]).length;
    document.getElementById('reb-stat-exits').textContent     = (r.exited_positions||[]).length;
    document.getElementById('reb-summary').textContent        = r.summary || '';
    document.getElementById('reb-macro').textContent          = r.macro_context || '';

    const actionColor = a => ({Buy:'var(--green)',Trim:'var(--yellow)',Sell:'var(--red)',Hold:'var(--sub)'}[a]||'var(--sub)');
    const rows = r.trades.filter(t=>t.action!=='Hold').map(t => `
        <tr>
            <td><strong>${t.ticker}</strong></td>
            <td style="color:${actionColor(t.action)};font-weight:700">${t.action}</td>
            <td>${fmtPct(t.current_weight)}</td>
            <td>${fmtPct(t.target_weight)}</td>
            <td style="color:${t.weight_delta>=0?'var(--green)':'var(--red)'};font-weight:600">${t.weight_delta>=0?'+':''}${fmtPct(t.weight_delta)}</td>
            <td>${fmtPct(t.drift_pct)}</td>
            <td><span class="pill ${t.priority==='High'?'pill-sell':t.priority==='Medium'?'pill-hold':'pill-pending'}">${t.priority}</span></td>
            <td style="color:var(--sub);font-size:11px">${t.rationale||''}</td>
        </tr>`).join('');
    document.getElementById('rebalance-table-body').innerHTML = rows;
}

// ── Correlation heatmap ───────────────────────────────────────────────
function corrColor(v) {
    if (v === null || v === undefined) return 'rgba(255,255,255,.04)';
    // -1 → red, 0 → neutral, +1 → green; diagonal (1.0) special
    const abs  = Math.abs(v);
    const sign = v >= 0 ? 1 : -1;
    if (sign > 0) {
        const a = v >= 0.99 ? 0.55 : 0.12 + abs * 0.65;
        return `rgba(0,214,50,${a.toFixed(2)})`;
    } else {
        const a = 0.12 + abs * 0.65;
        return `rgba(255,80,0,${a.toFixed(2)})`;
    }
}
function corrTextColor(v) {
    if (v === null) return 'var(--sub)';
    return Math.abs(v) > 0.5 ? '#fff' : 'var(--sub)';
}

function renderCorrelation() {
    const c = D.correlation;
    const el = document.getElementById('corr-container');
    if (!el) return;
    if (!c || !c.tickers || c.tickers.length < 2) {
        el.innerHTML = `<div class="placeholder"><div class="placeholder-icon">🔗</div>
            <div class="placeholder-text">Correlation matrix will appear after portfolio construction.<br>
            Requires at least 2 holdings with price history.</div></div>`;
        return;
    }

    const tickers = c.tickers;
    const matrix  = c.matrix;
    const n       = tickers.length;

    // Update meta line
    const meta = document.getElementById('corr-meta');
    if (meta && c.start_date) {
        meta.textContent = `${n} holdings · ${c.n_obs} trading days · ${c.start_date} → ${c.end_date}`;
    }

    // Build table
    let html = '<div class="corr-wrap"><table class="corr-table"><thead><tr><th></th>';
    tickers.forEach(t => { html += `<th>${t}</th>`; });
    html += '</tr></thead><tbody>';

    for (let i = 0; i < n; i++) {
        html += `<tr><th class="row-label">${tickers[i]}</th>`;
        for (let j = 0; j < n; j++) {
            const v   = matrix[i][j];
            const bg  = corrColor(v);
            const fc  = corrTextColor(v);
            const lbl = v !== null ? v.toFixed(2) : '—';
            const diag = i === j ? 'font-weight:900;' : '';
            html += `<td class="corr-cell" style="background:${bg};color:${fc};${diag}" title="${tickers[i]} / ${tickers[j]}: ${lbl}">${lbl}</td>`;
        }
        html += '</tr>';
    }
    html += '</tbody></table></div>';

    // Legend
    html += `<div class="corr-legend">
        <span style="color:rgba(255,80,0,.85)">−1.0</span>
        <div class="corr-legend-bar"></div>
        <span style="color:rgba(0,214,50,.85)">+1.0</span>
        <span style="margin-left:12px">· Highly correlated positions reduce diversification benefit</span>
    </div>`;

    // High-correlation warnings
    const warnings = [];
    for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
            const v = matrix[i][j];
            if (v !== null && v >= 0.85) {
                warnings.push(`<span style="color:var(--yellow)">⚠ ${tickers[i]} ↔ ${tickers[j]}: ${v.toFixed(2)}</span>`);
            }
        }
    }
    if (warnings.length) {
        html += `<div class="chart-wrap" style="margin-top:14px;padding:14px 20px">
            <div class="chart-title">High Correlation Pairs (≥ 0.85) — consider reducing overlap</div>
            <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px">${warnings.join('')}</div>
        </div>`;
    }

    el.innerHTML = html;
}

// ── Sidebar badges ────────────────────────────────────────────────────
function updateSidebarBadges() {
    const s  = D.screener;
    const a  = D.analysis;
    const p  = D.portfolio;
    const rb = D.rebalance;

    setBadge('screener', s && s.passed && s.passed.length > 0);
    if (a && a.total > 0) {
        const el = document.getElementById('badge-research');
        if (el) {
            const done = a.complete || 0;
            el.textContent = `${done}/${a.total}`;
            el.className   = 'tab-badge ' + (done === a.total ? 'badge-done' : 'badge-run');
        }
    }
    setBadge('reports', a && a.complete > 0);
    setBadge('portfolio',    p  && p.holdings  && p.holdings.length > 0);
    setBadge('correlation',  D.correlation && D.correlation.tickers && D.correlation.tickers.length > 1);
    setBadge('rebalance',    rb && rb.trades   && rb.trades.length > 0);

    // Stage pill
    const sp = document.getElementById('stage-pill');
    if (sp) sp.textContent = D.meta.stage || 'running';
}

function setBadge(id, done) {
    const el = document.getElementById('badge-' + id);
    if (!el) return;
    if (done) { el.textContent = '✓'; el.className = 'tab-badge badge-done'; }
}

// ── Auto-refresh ──────────────────────────────────────────────────────
function maybeAutoRefresh() {
    const ri = D.meta.refresh_interval;
    if (!ri || ri <= 0) return;
    setTimeout(() => location.reload(), ri * 1000);
}

// ── Init ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    renderScreener();
    renderScreenerTable();
    renderResearch();
    renderReports();
    renderPortfolio();
    renderCorrelation();
    renderRebalance();
    updateSidebarBadges();
    maybeAutoRefresh();
    // Auto-switch to first relevant tab
    const stage = D.meta.stage || '';
    if      (stage === 'screener_done' || stage === 'screener')  showTab('screener');
    else if (stage === 'analysis')  showTab('research');
    else if (stage === 'portfolio') showTab('portfolio');
    else if (stage === 'rebalance') showTab('rebalance');
    else if (stage === 'complete')  showTab('portfolio');
});
"""

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------
_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{refresh_tag}
<title>TradingAgents · Portfolio Dashboard</title>
<style>{css}</style>
</head>
<body>

<!-- ════ Sidebar ════════════════════════════════════════════════════════ -->
<aside class="sidebar">
  <div class="logo">📈 <span>TradingAgents</span></div>
  <div class="trade-date">Portfolio · {trade_date}</div>
  <nav>
    <button id="tab-screener"  class="tab-btn active" onclick="showTab('screener')">
      <span class="tab-icon">📊</span> Screener
      <span id="badge-screener" class="tab-badge badge-wait">·</span>
    </button>
    <button id="tab-research"  class="tab-btn" onclick="showTab('research')">
      <span class="tab-icon">🔬</span> Research
      <span id="badge-research" class="tab-badge badge-wait">·</span>
    </button>
    <button id="tab-reports"   class="tab-btn" onclick="showTab('reports')">
      <span class="tab-icon">📄</span> Reports
      <span id="badge-reports" class="tab-badge badge-wait">·</span>
    </button>
    <button id="tab-portfolio" class="tab-btn" onclick="showTab('portfolio')">
      <span class="tab-icon">💼</span> Portfolio
      <span id="badge-portfolio" class="tab-badge badge-wait">·</span>
    </button>
    <button id="tab-correlation" class="tab-btn" onclick="showTab('correlation')">
      <span class="tab-icon">🔗</span> Correlation
      <span id="badge-correlation" class="tab-badge badge-wait">·</span>
    </button>
    <button id="tab-rebalance" class="tab-btn" onclick="showTab('rebalance')">
      <span class="tab-icon">🔄</span> Rebalance
      <span id="badge-rebalance" class="tab-badge badge-wait">·</span>
    </button>
  </nav>
  <div class="sidebar-footer">
    Stage<br>
    <span class="stage-pill" id="stage-pill">initializing</span>
  </div>
</aside>

<!-- ════ Main content ═══════════════════════════════════════════════════ -->
<main class="content">

  <!-- ── Screener ─────────────────────────────────────────────────── -->
  <div id="panel-screener" class="panel active">
    <div class="panel-header">
      <div class="panel-title">Screener</div>
      <div class="panel-sub">5-factor institutional model · Quality · Growth · Valuation · Momentum · Analyst</div>
    </div>
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-label">Universe</div>
        <div class="stat-value" id="screener-stat-universe">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Selected</div>
        <div class="stat-value green" id="screener-stat-passed">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Filtered Out</div>
        <div class="stat-value red" id="screener-stat-filtered">—</div>
      </div>
    </div>
    <div id="screener-content">
      <div class="chart-wrap">
        <div class="chart-title">Composite Score Ranking — green bars selected · gray bars filtered</div>
        <div class="chart-container" style="height:600px">
          <canvas id="screener-chart"></canvas>
        </div>
      </div>
      <div class="chart-wrap">
        <div class="chart-title">All Tickers — Factor Breakdown</div>
        <div style="overflow-x:auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>Ticker</th><th>Passed</th><th>Composite</th><th>Quality</th>
                <th>Growth</th><th>Valuation</th><th>Momentum</th><th>Analyst</th><th>Filter Reason</th>
              </tr>
            </thead>
            <tbody id="screener-table-body"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- ── Research ─────────────────────────────────────────────────── -->
  <div id="panel-research" class="panel">
    <div class="panel-header">
      <div class="panel-title">Research Progress</div>
      <div class="panel-sub">Market · News · Sentiment · Fundamentals · Bull/Bear Debate · Trader · Risk · PM</div>
    </div>
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-label">Completed</div>
        <div class="stat-value green"><span id="research-stat-done">0</span> <span style="font-size:14px;color:var(--sub)">/ <span id="research-stat-total">—</span></span></div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Running Now</div>
        <div class="stat-value yellow" id="research-stat-running">0</div>
      </div>
    </div>
    <div class="chart-wrap" style="padding:16px 24px">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <div class="chart-title" style="margin:0">Analysis Progress</div>
        <div style="font-size:12px;color:var(--green);font-weight:700" id="research-pct">0%</div>
      </div>
      <div class="progress-bar-wrap">
        <div class="progress-bar-fill" id="research-progress-fill" style="width:0%"></div>
      </div>
    </div>
    <div id="research-content">
      <div id="ticker-grid" class="ticker-grid"></div>
    </div>
  </div>

  <!-- ── Reports ──────────────────────────────────────────────────── -->
  <div id="panel-reports" class="panel">
    <div class="panel-header">
      <div class="panel-title">Research Reports</div>
      <div class="panel-sub">Full per-ticker report — all analyst sections</div>
    </div>
    <div class="report-controls">
      <select class="report-select" id="report-select" onchange="onReportSelect()">
        <option value="">— Select a stock —</option>
      </select>
    </div>
    <div class="report-body" id="report-body">
      <div class="placeholder">
        <div class="placeholder-icon">📄</div>
        <div class="placeholder-text">Select a stock above to view its full research report.</div>
      </div>
    </div>
  </div>

  <!-- ── Portfolio ────────────────────────────────────────────────── -->
  <div id="panel-portfolio" class="panel">
    <div class="panel-header">
      <div class="panel-title">Portfolio View</div>
      <div class="panel-sub">Momentum + Quality · Risk-aware weights · OW/UW rationale</div>
    </div>
    <div id="portfolio-content">
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-label">Holdings</div>
          <div class="stat-value green" id="port-stat-holdings">—</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Invested</div>
          <div class="stat-value" id="port-stat-invested">—</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Cash</div>
          <div class="stat-value yellow" id="port-stat-cash">—</div>
        </div>
      </div>
      <div class="two-col">
        <div class="chart-wrap">
          <div class="chart-title">Portfolio Weights</div>
          <div class="chart-container" style="height:280px">
            <canvas id="weight-donut"></canvas>
          </div>
        </div>
        <div class="chart-wrap">
          <div class="chart-title">Sector Exposure</div>
          <div class="chart-container" style="height:280px">
            <canvas id="sector-chart"></canvas>
          </div>
        </div>
      </div>
      <div class="chart-wrap">
        <div class="chart-title">Holdings</div>
        <div style="overflow-x:auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>Ticker</th><th>Rating</th><th>Weight</th><th>Conviction</th>
                <th>Price Target</th><th>Horizon</th><th>Thesis</th>
              </tr>
            </thead>
            <tbody id="holdings-table-body"></tbody>
          </table>
        </div>
      </div>
      <div class="two-col">
        <div class="chart-wrap">
          <div class="chart-title">Construction Rationale</div>
          <p id="port-rationale" style="color:var(--text);line-height:1.6;font-size:13px"></p>
        </div>
        <div>
          <div class="chart-wrap" style="margin-bottom:12px">
            <div class="chart-title">Top Overweights</div>
            <p id="port-overweights" style="color:var(--green);line-height:1.6;font-size:13px"></p>
          </div>
          <div class="chart-wrap">
            <div class="chart-title">Top Underweights / Exclusions</div>
            <p id="port-underweights" style="color:var(--red);line-height:1.6;font-size:13px"></p>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ── Correlation ──────────────────────────────────────────────── -->
  <div id="panel-correlation" class="panel">
    <div class="panel-header">
      <div class="panel-title">Return Correlation Matrix</div>
      <div class="panel-sub" id="corr-meta">Pairwise Pearson correlation of daily log returns · ~1 trading year</div>
    </div>
    <div class="chart-wrap" style="margin-bottom:16px;padding:16px 20px">
      <div class="chart-title">How to read this</div>
      <p style="color:var(--sub);font-size:12px;line-height:1.6;margin-top:4px">
        Each cell shows the Pearson correlation of daily returns between two stocks over the past year.
        <strong style="color:var(--green)">+1.0</strong> (dark green) = move in lockstep.
        <strong style="color:rgba(255,80,0,.9)">−1.0</strong> (dark red) = move opposite.
        <strong style="color:var(--text)">0.0</strong> = uncorrelated — best for diversification.
        Pairs above <strong style="color:var(--yellow)">0.85</strong> are flagged as high-overlap.
      </p>
    </div>
    <div id="corr-container"></div>
  </div>

  <!-- ── Rebalance ────────────────────────────────────────────────── -->
  <div id="panel-rebalance" class="panel">
    <div class="panel-header">
      <div class="panel-title">Rebalance Recommendations</div>
      <div class="panel-sub">Drift-aware trade list</div>
    </div>
    <div id="rebalance-content">
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-label">Trades</div>
          <div class="stat-value" id="reb-stat-trades">—</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Turnover</div>
          <div class="stat-value yellow" id="reb-stat-turnover">—</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">New Positions</div>
          <div class="stat-value green" id="reb-stat-new">—</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Exits</div>
          <div class="stat-value red" id="reb-stat-exits">—</div>
        </div>
      </div>
      <div class="chart-wrap">
        <div class="chart-title">Summary</div>
        <p id="reb-summary" style="color:var(--text);line-height:1.6;font-size:13px;margin-bottom:10px"></p>
        <p id="reb-macro" style="color:var(--sub);line-height:1.6;font-size:12px"></p>
      </div>
      <div class="chart-wrap">
        <div class="chart-title">Trade List</div>
        <div style="overflow-x:auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>Ticker</th><th>Action</th><th>Current</th><th>Target</th>
                <th>Δ Weight</th><th>Drift</th><th>Priority</th><th>Rationale</th>
              </tr>
            </thead>
            <tbody id="rebalance-table-body"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

</main>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.0/marked.min.js"></script>
<script>window.__DATA__ = {data_json};</script>
<script>{js}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Dashboard class
# ---------------------------------------------------------------------------

class PortfolioDashboard:
    """Live HTML dashboard written to disk and auto-refreshed in the browser."""

    def __init__(self, output_dir: str, trade_date: str) -> None:
        self.output_dir  = output_dir
        self.trade_date  = trade_date
        self.path        = os.path.join(output_dir, f"dashboard_{trade_date.replace('-','')}.html")
        self._data: Dict[str, Any] = {
            "meta": {
                "trade_date":       trade_date,
                "generated_at":     datetime.now().isoformat(timespec="seconds"),
                "stage":            "initializing",
                "refresh_interval": 4,   # seconds; set to 0 when done
            },
            "screener": {
                "n_universe": 0,
                "n_passed":   0,
                "n_filtered": 0,
                "passed":     [],
                "filtered":   [],
            },
            "analysis": {
                "total":    0,
                "complete": 0,
                "tickers":  {},
            },
            "portfolio":    {},
            "correlation":  {},
            "rebalance":    {},
        }
        os.makedirs(output_dir, exist_ok=True)
        self._write()

    # ------------------------------------------------------------------
    # Public API (called by PortfolioGraph)
    # ------------------------------------------------------------------

    def open_browser(self) -> None:
        """Open the dashboard in the default system browser."""
        webbrowser.open(f"file://{os.path.abspath(self.path)}")

    def update_screener(
        self,
        passed:   List[Any],   # List[ScreenerResult]
        filtered: List[Any],   # List[ScreenerResult]
    ) -> None:
        """Populate the screener tab and switch stage to screener_done."""
        self._data["screener"] = {
            "n_universe": len(passed) + len(filtered),
            "n_passed":   len(passed),
            "n_filtered": len(filtered),
            "passed":  [self._sr_dict(r) for r in passed],
            "filtered": [self._sr_dict(r) for r in filtered],
        }
        self._data["analysis"]["total"] = len(passed)
        for r in passed:
            self._data["analysis"]["tickers"].setdefault(
                r.ticker, {"status": "pending"}
            )
        self._set_stage("screener_done")

    def update_ticker_start(self, ticker: str, i: int, n: int) -> None:
        t = self._data["analysis"]["tickers"].setdefault(ticker, {})
        t.update({"status": "running"})
        self._data["analysis"]["total"] = n
        self._set_stage("analysis")

    def update_ticker_done(
        self,
        ticker:    str,
        rating:    str,
        elapsed:   float,
        report_md: str = "",
    ) -> None:
        t = self._data["analysis"]["tickers"].setdefault(ticker, {})
        t.update({"status": "complete", "rating": rating,
                  "elapsed": round(elapsed, 1), "report_md": report_md})
        done = sum(1 for v in self._data["analysis"]["tickers"].values()
                   if v.get("status") == "complete")
        self._data["analysis"]["complete"] = done
        self._write()

    def update_ticker_failed(self, ticker: str, elapsed: float) -> None:
        t = self._data["analysis"]["tickers"].setdefault(ticker, {})
        t.update({"status": "failed", "elapsed": round(elapsed, 1)})
        self._write()

    def update_portfolio(self, view: Any) -> None:
        """Populate the portfolio tab from a PortfolioView."""
        self._data["portfolio"] = {
            "holdings": [
                {
                    "ticker":            h.ticker,
                    "rating":            h.rating,
                    "target_weight":     h.target_weight,
                    "conviction":        h.conviction.value if hasattr(h.conviction, "value") else h.conviction,
                    "price_target":      h.price_target,
                    "time_horizon":      h.time_horizon,
                    "investment_thesis": h.investment_thesis,
                    "overweight_reason": h.overweight_reason,
                    "underweight_reason": h.underweight_reason,
                }
                for h in view.holdings
            ],
            "cash_weight":            view.cash_weight,
            "sector_weights":         view.sector_weights or {},
            "construction_rationale": view.construction_rationale,
            "top_overweights":        view.top_overweights,
            "top_underweights":       view.top_underweights,
            "methodology":            view.methodology,
        }
        self._set_stage("portfolio")

    def update_correlation(self, corr_data: Optional[dict]) -> None:
        """Embed a precomputed correlation matrix (from correlation.py)."""
        if corr_data:
            self._data["correlation"] = corr_data
            self._write()

    def update_rebalance(self, rec: Any) -> None:
        """Populate the rebalance tab from a RebalanceRecommendation."""
        self._data["rebalance"] = {
            "trade_date":          rec.trade_date,
            "rebalance_type":      rec.rebalance_type,
            "rebalance_turnover":  rec.portfolio_turnover_pct,
            "new_positions":       rec.new_positions,
            "exited_positions":    rec.exited_positions,
            "summary":             rec.summary,
            "macro_context":       rec.macro_context,
            "trades": [
                {
                    "ticker":         t.ticker,
                    "action":         t.action.value if hasattr(t.action, "value") else t.action,
                    "current_weight": t.current_weight,
                    "target_weight":  t.target_weight,
                    "weight_delta":   t.weight_delta,
                    "drift_pct":      t.drift_pct,
                    "priority":       t.priority,
                    "rationale":      t.rationale,
                }
                for t in rec.trades
            ],
        }
        self._set_stage("rebalance")

    def finalize(self) -> None:
        """Disable auto-refresh — run is complete."""
        self._data["meta"]["refresh_interval"] = 0
        self._data["meta"]["stage"] = "complete"
        self._write()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sr_dict(self, r: Any) -> Dict[str, Any]:
        """Convert a ScreenerResult to a plain dict for JSON embedding."""
        return {
            "ticker":              r.ticker,
            "sector":              r.sector,
            "market_cap":          r.market_cap,
            "composite_score":     r.composite_score,
            "composite_rank":      r.composite_rank,
            "quality_score":       r.quality_score,
            "growth_score":        r.growth_score,
            "valuation_score":     r.valuation_score,
            "momentum_score":      r.momentum_score,
            "analyst_score":       r.analyst_score,
            "passed_hard_filters": r.passed_hard_filters,
            "filter_reason":       r.filter_reason,
        }

    def _set_stage(self, stage: str) -> None:
        self._data["meta"]["stage"] = stage
        self._data["meta"]["generated_at"] = datetime.now().isoformat(timespec="seconds")
        self._write()

    def _write(self) -> None:
        """Regenerate the HTML file from current data."""
        ri = self._data["meta"].get("refresh_interval", 4)
        refresh_tag = (
            f'<meta http-equiv="refresh" content="{ri}">' if ri > 0 else ""
        )
        html = _HTML.format(
            css         = _CSS,
            js          = _JS,
            refresh_tag = refresh_tag,
            trade_date  = self.trade_date,
            data_json   = json.dumps(self._data, ensure_ascii=False, default=str),
        )
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(html)
        os.replace(tmp, self.path)   # atomic replace — no partial reads
