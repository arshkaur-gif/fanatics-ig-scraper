"""Web UI for the Instagram Followers Scraper."""

import os
import time

from apify_client import ApifyClient
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request

load_dotenv()

app = Flask(__name__)

FOLLOWERS_ACTOR = "scraping_solutions/instagram-scraper-followers-following-no-cookies"
PROFILE_ACTOR = "apify/instagram-profile-scraper"

# The Leaderboard UI scrapes a bounded page range; the full multi-day harvest
# is the CLI's job (scraper.harvest).
MAX_UI_PAGES = 10

# Approximate Apify pricing per result (used for client-side cost preview)
COST_PER_FOLLOWER = 0.002
COST_PER_PROFILE = 0.0023


HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reach · Instagram</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg:            #070809;
      --bg-elev:       #0e1014;
      --panel:         #11141a;
      --panel-2:       #161a22;
      --border:        #1f232c;
      --border-strong: #2a2f3a;
      --text:          #e7e9ee;
      --text-muted:    #8b92a0;
      --text-dim:      #5c6370;
      --accent:        #6366f1;
      --accent-2:      #8b5cf6;
      --success:       #10b981;
      --danger:        #ef4444;
      --warning:       #f59e0b;
      --ig-1:          #f09433;
      --ig-2:          #dc2743;
      --ig-3:          #bc1888;
      --radius:        10px;
      --radius-lg:     14px;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { height: 100%; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      font-feature-settings: "cv11", "ss01";
      -webkit-font-smoothing: antialiased;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      line-height: 1.5;
      background-image:
        radial-gradient(1200px 600px at 20% -10%, rgba(99,102,241,0.08), transparent 60%),
        radial-gradient(1000px 500px at 110% 10%, rgba(220,39,67,0.06), transparent 60%);
      background-attachment: fixed;
    }

    .topbar {
      position: sticky; top: 0; z-index: 50;
      backdrop-filter: blur(14px);
      background: rgba(7,8,9,0.7);
      border-bottom: 1px solid var(--border);
    }
    .topbar-inner {
      max-width: 1320px; margin: 0 auto;
      padding: 14px 28px;
      display: flex; align-items: center; gap: 24px;
    }
    .brand { display: flex; align-items: center; gap: 10px; }
    .brand-mark {
      width: 28px; height: 28px; border-radius: 8px;
      background: linear-gradient(135deg, var(--ig-1), var(--ig-2), var(--ig-3));
      display: grid; place-items: center;
      box-shadow: 0 4px 20px -6px rgba(220,39,67,0.5);
    }
    .brand-mark svg { width: 16px; height: 16px; color: white; }
    .brand-title { font-weight: 700; font-size: 15px; letter-spacing: -0.01em; }
    .brand-title span { color: var(--text-muted); font-weight: 500; }

    .container { max-width: 1320px; margin: 0 auto; padding: 32px 28px 80px; }

    .hero {
      background: linear-gradient(180deg, var(--panel) 0%, var(--bg-elev) 100%);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 28px;
      margin-bottom: 24px;
      position: relative;
      overflow: hidden;
    }
    .hero::before {
      content: "";
      position: absolute; inset: 0;
      background: radial-gradient(600px 200px at 85% -40%, rgba(99,102,241,0.14), transparent 60%);
      pointer-events: none;
    }
    .hero h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 4px; }
    .hero p { color: var(--text-muted); font-size: 14px; margin-bottom: 20px; }

    .form-grid {
      display: grid;
      grid-template-columns: minmax(240px,1fr) 120px 160px auto;
      gap: 10px;
      position: relative;
      z-index: 1;
    }
    @media (max-width: 820px) { .form-grid { grid-template-columns: 1fr; } }

    .field {
      display: flex; flex-direction: column;
      background: var(--bg-elev);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 8px 14px;
      transition: border-color 150ms, background 150ms;
    }
    .field:focus-within { border-color: var(--accent); background: #0b0d12; box-shadow: 0 0 0 4px rgba(99,102,241,0.08); }
    .field label { font-size: 11px; font-weight: 500; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.06em; }
    .field input, .field select {
      background: transparent; border: none; outline: none; color: var(--text);
      font-family: inherit; font-size: 14px; font-weight: 500;
      padding: 2px 0; width: 100%;
    }
    .field select { appearance: none; background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238b92a0' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>"); background-repeat: no-repeat; background-position: right center; padding-right: 16px; cursor: pointer; }

    .form-meta { margin-top: 10px; font-size: 12px; color: var(--text-dim); display: flex; gap: 14px; align-items: center; flex-wrap: wrap; position: relative; z-index: 1; }
    .cost-tag { font-family: 'JetBrains Mono', monospace; color: #a7f3d0; background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.25); padding: 3px 9px; border-radius: 999px; font-size: 11.5px; }

    button { font-family: inherit; cursor: pointer; border: none; }

    .btn {
      display: inline-flex; align-items: center; justify-content: center; gap: 8px;
      padding: 11px 18px; border-radius: var(--radius);
      font-weight: 600; font-size: 14px;
      transition: all 150ms;
      white-space: nowrap;
    }
    .btn[disabled] { opacity: 0.5; cursor: not-allowed; }
    .btn svg { width: 16px; height: 16px; }

    .btn-primary { background: var(--accent); color: white; }
    .btn-primary:hover:not([disabled]) { background: #7275f5; transform: translateY(-1px); box-shadow: 0 8px 24px -8px rgba(99,102,241,0.5); }

    .btn-accent-2 { background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: white; }
    .btn-accent-2:hover:not([disabled]) { opacity: 0.92; transform: translateY(-1px); }

    .btn-muted { background: var(--panel); color: var(--text); border: 1px solid var(--border); }
    .btn-muted:hover:not([disabled]) { background: var(--panel-2); }

    .btn-sm { padding: 7px 12px; font-size: 13px; }
    .btn-xs { padding: 5px 10px; font-size: 12px; border-radius: 8px; }

    .status {
      margin: 16px 0;
      padding: 12px 16px;
      border: 1px solid var(--border);
      background: var(--panel);
      border-radius: var(--radius);
      font-size: 13px; color: var(--text-muted);
      display: none;
    }
    .status.visible { display: flex; align-items: center; gap: 10px; }
    .status.error { border-color: rgba(239,68,68,0.4); background: rgba(239,68,68,0.06); color: #fecaca; }
    .status.success { border-color: rgba(16,185,129,0.4); background: rgba(16,185,129,0.06); color: #a7f3d0; }

    .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.15); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.7s linear infinite; flex-shrink: 0; }
    @keyframes spin { to { transform: rotate(360deg); } }

    .results-card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      overflow: hidden;
      display: none;
    }
    .results-card.visible { display: block; }
    .results-head { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
    .results-head h2 { font-size: 15px; font-weight: 600; display: flex; align-items: center; gap: 10px; }
    .chip { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 999px; background: var(--panel-2); color: var(--text-muted); font-size: 12px; font-weight: 500; border: 1px solid var(--border); }
    .chip.success { border-color: rgba(16,185,129,0.4); background: rgba(16,185,129,0.08); color: #a7f3d0; }

    .toolbar { display: flex; gap: 8px; flex-wrap: wrap; }

    /* Filter bar */
    .filter-bar { display: flex; align-items: center; gap: 10px; padding: 12px 22px; background: var(--bg-elev); border-bottom: 1px solid var(--border); flex-wrap: wrap; }
    .search-input {
      background: var(--panel);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 7px 12px 7px 32px;
      border-radius: 8px;
      font-family: inherit;
      font-size: 13px;
      outline: none;
      width: 240px;
      background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%238b92a0' stroke-width='2'><circle cx='11' cy='11' r='8'/><line x1='21' y1='21' x2='16.65' y2='16.65'/></svg>");
      background-repeat: no-repeat;
      background-position: 10px center;
    }
    .search-input:focus { border-color: var(--accent); }
    .search-input.bio { width: 200px; background-image: none; padding-left: 12px; }
    .filter-pill { padding: 6px 12px; font-size: 12px; border: 1px solid var(--border); background: var(--panel); color: var(--text-muted); border-radius: 999px; cursor: pointer; user-select: none; transition: all 120ms; }
    .filter-pill:hover { border-color: var(--border-strong); color: var(--text); }
    .filter-pill.active { background: rgba(99,102,241,0.1); border-color: rgba(99,102,241,0.5); color: #c7d2fe; }
    .filter-divider { width: 1px; height: 20px; background: var(--border); margin: 0 4px; }
    .filter-stat { font-size: 12px; color: var(--text-dim); margin-left: auto; }

    /* Selection bar */
    .select-bar { display: none; padding: 10px 22px; background: rgba(99,102,241,0.06); border-bottom: 1px solid var(--border); align-items: center; gap: 12px; font-size: 12px; flex-wrap: wrap; }
    .select-bar.visible { display: flex; }
    .select-count { font-weight: 600; color: var(--text); }

    /* Table */
    .table-wrap { overflow-x: auto; max-height: 70vh; }
    table { width: 100%; border-collapse: collapse; }
    thead th {
      text-align: left;
      padding: 10px 14px;
      font-size: 10.5px;
      text-transform: uppercase;
      color: var(--text-dim);
      font-weight: 600;
      letter-spacing: 0.08em;
      border-bottom: 1px solid var(--border);
      background: var(--bg-elev);
      position: sticky; top: 0; z-index: 1;
      user-select: none;
    }
    thead th.sortable { cursor: pointer; }
    thead th.sortable:hover { color: var(--text); }
    thead th .sort-arrow { display: inline-block; margin-left: 4px; opacity: 0.4; font-size: 9px; }
    thead th.sorted .sort-arrow { opacity: 1; color: var(--accent); }
    tbody td { padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 13px; vertical-align: middle; }
    tbody tr { transition: background 120ms; }
    tbody tr:hover { background: var(--panel-2); }
    tbody tr.selected { background: rgba(99,102,241,0.08); }

    .avatar { width: 32px; height: 32px; border-radius: 50%; object-fit: cover; background: var(--panel-2); }
    .avatar-fallback { width: 32px; height: 32px; border-radius: 50%; background: var(--panel-2); display: grid; place-items: center; color: var(--text-dim); font-size: 11px; font-weight: 600; }

    .handle { color: var(--text); text-decoration: none; font-weight: 500; }
    .handle:hover { color: var(--accent); }
    .sub-handle { color: var(--text-muted); font-size: 12px; }
    .sub-handle:hover { color: var(--accent); }

    .badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 500; margin: 1px 2px; line-height: 1.4; }
    .badge.verified { background: rgba(59,130,246,0.14); color: #93c5fd; border: 1px solid rgba(59,130,246,0.3); }
    .badge.private { background: rgba(245,158,11,0.1); color: #fcd34d; border: 1px solid rgba(245,158,11,0.3); }
    .badge.public { background: rgba(16,185,129,0.1); color: #6ee7b7; border: 1px solid rgba(16,185,129,0.3); }

    .bio-cell { color: var(--text-muted); font-size: 12px; max-width: 360px; line-height: 1.4; }
    .num-cell { font-family: 'JetBrains Mono', monospace; color: var(--text); font-size: 12px; text-align: right; }

    input[type="checkbox"].row-check { width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer; }

    .empty {
      padding: 80px 20px;
      text-align: center;
      border: 1px dashed var(--border);
      border-radius: var(--radius-lg);
      color: var(--text-dim);
      background: var(--bg-elev);
    }
    .empty svg { width: 40px; height: 40px; stroke: var(--text-dim); margin-bottom: 12px; }
    .empty-title { font-size: 14px; color: var(--text); font-weight: 500; margin-bottom: 4px; }
    .empty-sub { font-size: 13px; }

    .dim { color: var(--text-dim); }

    /* Modal */
    .modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.55); backdrop-filter: blur(8px); display: none; align-items: center; justify-content: center; z-index: 100; }
    .modal-backdrop.visible { display: flex; animation: fadeIn 140ms ease-out; }
    .modal { background: var(--panel); border: 1px solid var(--border-strong); border-radius: var(--radius-lg); padding: 22px 24px; max-width: 440px; width: 92%; box-shadow: 0 20px 60px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.02); animation: scaleIn 150ms ease-out; }
    .modal.large { max-width: 720px; padding: 0; }
    .modal.large .modal-head { padding: 22px 24px 14px; border-bottom: 1px solid var(--border); }
    .modal.large .modal-content { padding: 18px 24px; max-height: 65vh; overflow-y: auto; }
    .modal.large .modal-foot { padding: 14px 24px; border-top: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
    .modal.large textarea { width: 100%; background: var(--bg-elev); border: 1px solid var(--border); color: var(--text); padding: 10px 12px; border-radius: var(--radius); font-family: inherit; font-size: 13px; resize: vertical; min-height: 80px; outline: none; }
    .modal.large textarea:focus { border-color: var(--accent); }
    .dm-row { display: grid; grid-template-columns: 24px 1fr 1fr auto auto; gap: 12px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border); }
    .dm-row:last-child { border-bottom: none; }
    .dm-row.sent { opacity: 0.45; }
    .dm-row .dm-num { color: var(--text-dim); font-size: 11px; font-family: 'JetBrains Mono', monospace; text-align: center; }
    .dm-row .dm-handle { color: var(--text); font-weight: 500; font-size: 13px; }
    .dm-row .dm-handle a { color: inherit; text-decoration: none; }
    .dm-row .dm-handle a:hover { color: var(--accent); }
    .dm-row .dm-msg { color: var(--text-muted); font-size: 12px; line-height: 1.4; max-width: 280px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: 'JetBrains Mono', monospace; }
    .dm-row .dm-actions { display: flex; gap: 6px; }
    .dm-row .dm-status { color: var(--success); font-size: 11px; font-weight: 600; }
    .dm-row .dm-status.skipped { color: var(--text-dim); }
    .dm-toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: var(--panel); border: 1px solid var(--border-strong); padding: 12px 18px; border-radius: var(--radius); color: var(--text); font-size: 13px; box-shadow: 0 10px 40px rgba(0,0,0,0.6); z-index: 200; display: none; animation: fadeIn 150ms ease-out; }
    .dm-toast.visible { display: flex; align-items: center; gap: 10px; }
    .dm-toast.success { border-color: rgba(16,185,129,0.5); color: #a7f3d0; }
    .dm-toast .toast-key { background: var(--bg-elev); border: 1px solid var(--border); padding: 2px 7px; border-radius: 5px; font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text); }

    /* Bulk DM link grid */
    .bulk-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
    .bulk-link {
      display: flex; align-items: center; gap: 10px;
      padding: 9px 12px;
      background: var(--bg-elev); border: 1px solid var(--border);
      border-radius: var(--radius); color: var(--text);
      text-decoration: none; font-size: 13px; font-weight: 500;
      transition: all 130ms;
      position: relative;
    }
    .bulk-link:hover { border-color: var(--accent); background: var(--panel-2); transform: translateY(-1px); }
    .bulk-link.opened { opacity: 0.5; border-color: rgba(16,185,129,0.4); }
    .bulk-link.opened::after { content: '✓'; color: var(--success); font-weight: 700; margin-left: auto; }
    .bulk-link svg { width: 14px; height: 14px; opacity: 0.6; flex-shrink: 0; }
    .bulk-link .name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
    .modal-title { font-size: 15px; font-weight: 600; margin-bottom: 8px; color: var(--text); }
    .modal-body { color: var(--text-muted); font-size: 13.5px; line-height: 1.55; margin-bottom: 18px; }
    .modal-body b { color: var(--text); font-weight: 600; }
    .modal-cost { display: inline-block; margin-top: 6px; font-family: 'JetBrains Mono', monospace; color: #a7f3d0; background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.25); padding: 3px 10px; border-radius: 999px; font-size: 12px; }
    .modal-actions { display: flex; gap: 8px; justify-content: flex-end; }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    @keyframes scaleIn { from { opacity: 0; transform: translateY(6px) scale(0.97); } to { opacity: 1; transform: translateY(0) scale(1); } }

    /* Tabs */
    .tab-nav { display: flex; gap: 2px; margin-bottom: 24px; border-bottom: 1px solid var(--border); }
    .tab-btn { background: none; border: none; color: var(--text-muted); font-family: inherit; font-size: 14px; font-weight: 500; padding: 10px 18px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; transition: color 150ms, border-color 150ms; }
    .tab-btn:hover { color: var(--text); }
    .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }

    /* Leaderboard form */
    .lb-form-grid { display: grid; grid-template-columns: minmax(280px,2fr) 100px 160px auto; gap: 10px; position: relative; z-index: 1; }
    @media (max-width: 820px) { .lb-form-grid { grid-template-columns: 1fr; } }
    .lb-meta { margin-top: 10px; font-size: 12px; color: var(--text-dim); display: flex; align-items: center; gap: 14px; flex-wrap: wrap; position: relative; z-index: 1; }
    .lb-meta label { display: flex; align-items: center; gap: 6px; cursor: pointer; color: var(--text-muted); }
    .lb-meta input[type="checkbox"] { accent-color: var(--accent); width: 13px; height: 13px; }

    /* Leaderboard table extras */
    .earnings-cell { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #a7f3d0; text-align: right; }
    .search-link { color: var(--accent); text-decoration: none; font-size: 12px; opacity: 0.8; }
    .search-link:hover { opacity: 1; }
    .year-cell { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted); }
    .stale-year { color: var(--warning); }

    /* Contact enrichment */
    .email-cell { font-size: 12px; color: #a5b4fc; max-width: 220px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .phone-cell { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted); }
    .conf-badge { display: inline-flex; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 500; }
    .conf-high   { background: rgba(16,185,129,0.1);  color: #6ee7b7; border: 1px solid rgba(16,185,129,0.3); }
    .conf-medium { background: rgba(245,158,11,0.1);  color: #fcd34d; border: 1px solid rgba(245,158,11,0.3); }
    .conf-low    { background: rgba(99,102,241,0.1);  color: #c7d2fe; border: 1px solid rgba(99,102,241,0.3); }

    /* Lookup tab */
    .lk-form { display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: start; position: relative; z-index: 1; }
    @media (max-width: 640px) { .lk-form { grid-template-columns: 1fr; } }
    .lk-textarea {
      width: 100%; background: var(--bg-elev); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 10px 14px; color: var(--text);
      font-family: 'JetBrains Mono', monospace; font-size: 13px; resize: vertical;
      outline: none; transition: border-color 150ms, background 150ms;
      min-height: 110px;
    }
    .lk-textarea:focus { border-color: var(--accent); background: #0b0d12; box-shadow: 0 0 0 4px rgba(99,102,241,0.08); }
    .lk-textarea::placeholder { color: var(--text-dim); }
    .lk-hint-row { display: flex; gap: 10px; align-items: center; margin-top: 8px; }
    .lk-hint-row .field { flex: 1; flex-direction: row; align-items: center; }
    .lk-hint-row .field label { white-space: nowrap; margin-right: 8px; }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">
        <div class="brand-mark">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1.2" fill="currentColor"/></svg>
        </div>
        <div class="brand-title">Reach <span id="brandSub">· Instagram outreach</span></div>
      </div>
    </div>
  </header>

  <main class="container">
    <div class="tab-nav">
      <button class="tab-btn active" data-tab="ig" onclick="switchTab('ig')">
        <svg style="width:13px;height:13px;vertical-align:-2px;margin-right:6px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1.2" fill="currentColor"/></svg>
        Instagram
      </button>
      <button class="tab-btn" data-tab="lb" onclick="switchTab('lb')">
        <svg style="width:13px;height:13px;vertical-align:-2px;margin-right:6px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        Leaderboards
      </button>
    </div>

    <div id="igTab">
    <section class="hero">
      <h1>Scrape a handle's audience</h1>
      <p>Pull followers or following from any public Instagram profile. Export to CSV or JSON.</p>
      <form id="scrapeForm" class="form-grid">
        <div class="field">
          <label for="usernames">Handle or URL</label>
          <input id="usernames" name="usernames" placeholder="dynastyrewards  (or paste IG URL)" required autocomplete="off">
        </div>
        <div class="field">
          <label for="limit">Limit</label>
          <input id="limit" name="limit" type="number" min="100" max="90000" value="200" title="Apify actor minimum is 100">
        </div>
        <div class="field">
          <label for="type">Direction</label>
          <select id="type" name="type">
            <option value="Followers">Followers</option>
            <option value="Followings">Following</option>
          </select>
        </div>
        <button type="submit" id="submitBtn" class="btn btn-primary">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="13 17 18 12 13 7"/><polyline points="6 17 11 12 6 7"/></svg>
          Scrape
        </button>
      </form>
      <div class="form-meta">
        <span>Estimated cost</span>
        <span class="cost-tag" id="costTag">~$0.40</span>
        <span class="dim">·</span>
        <span class="dim">≈ $""" + f"{COST_PER_FOLLOWER:.4f}" + """ per result · Apify actor min limit 100</span>
      </div>
    </section>

    <div class="status" id="status"></div>

    <section class="results-card" id="resultsCard">
      <div class="results-head">
        <h2>
          Results
          <span class="chip" id="resultChip">0</span>
          <span class="chip success" id="detailsChip" style="display:none;">profile details</span>
        </h2>
        <div class="toolbar">
          <button class="btn btn-accent-2 btn-sm" onclick="fetchProfileDetails()" id="detailsBtn">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            Get profile details
          </button>
          <button class="btn btn-muted btn-sm" onclick="enrichIgContacts()" id="igEnrichBtn">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            Enrich Contacts
          </button>
          <button class="btn btn-muted btn-sm" onclick="exportCSV()">CSV</button>
          <button class="btn btn-muted btn-sm" onclick="exportJSON()">JSON</button>
        </div>
      </div>

      <div class="filter-bar">
        <input type="text" class="search-input" id="searchInput" placeholder="Search handle or name..." oninput="renderTable()">
        <div class="filter-divider"></div>
        <span class="filter-pill active" data-status="all" onclick="setStatusFilter('all')">All</span>
        <span class="filter-pill" data-status="public" onclick="setStatusFilter('public')">Public</span>
        <span class="filter-pill" data-status="verified" onclick="setStatusFilter('verified')">Verified</span>
        <span class="filter-pill" data-status="private" onclick="setStatusFilter('private')">Private</span>
        <input type="text" class="search-input bio" id="bioInput" placeholder="Bio keyword..." oninput="renderTable()" style="display:none;">
        <span class="filter-stat" id="filterStat"></span>
      </div>

      <div class="select-bar" id="selectBar">
        <span class="select-count"><span id="selectedCount">0</span> selected</span>
        <button class="btn btn-muted btn-xs" onclick="selectAll()">All</button>
        <button class="btn btn-muted btn-xs" onclick="deselectAll()">None</button>
        <button class="btn btn-muted btn-xs" onclick="openSelectedInIG()">Open profiles</button>
        <button class="btn btn-muted btn-xs" onclick="bulkDmOpen()" style="background:linear-gradient(135deg,#dc2743,#bc1888); color:white; border:none;">Bulk DM</button>
        <button class="btn btn-muted btn-xs" onclick="openDmLauncher()">DM Launcher</button>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr id="tableHeader"></tr>
          </thead>
          <tbody id="resultsBody"></tbody>
        </table>
      </div>
    </section>

    <div class="modal-backdrop" id="modalBackdrop">
      <div class="modal">
        <div class="modal-title" id="modalTitle"></div>
        <div class="modal-body" id="modalBody"></div>
        <div class="modal-actions">
          <button class="btn btn-muted btn-sm" id="modalCancel">Cancel</button>
          <button class="btn btn-primary btn-sm" id="modalOk">OK</button>
        </div>
      </div>
    </div>

    <!-- DM Launcher modal -->
    <div class="modal-backdrop" id="dmModalBackdrop">
      <div class="modal large">
        <div class="modal-head">
          <div class="modal-title" style="margin-bottom:6px;">DM Launcher</div>
          <div class="modal-body" style="margin-bottom:12px; font-size:13px;">
            Type a message, then click <b>Open + Copy</b> on each row. The IG DM tab opens and your personalized message is copied to your clipboard — paste with <span style="font-family:'JetBrains Mono',monospace; background:var(--bg-elev); border:1px solid var(--border); padding:1px 6px; border-radius:5px; font-size:11px;">Cmd+V</span> and hit Enter.
          </div>
          <textarea id="dmTemplate" placeholder="Hey {name}! Saw you follow some cool accounts — would love to connect.">Hey {name}! Saw you follow some cool accounts — would love to connect.</textarea>
          <div class="dim tiny" style="font-size:11px; margin-top:6px;">Variables: <code>{name}</code> first name · <code>{username}</code> handle</div>
        </div>
        <div class="modal-content" id="dmQueueList"></div>
        <div class="modal-foot">
          <div class="dim" style="font-size:12px;"><span id="dmProgress">0 of 0 sent</span></div>
          <div style="display:flex; gap:8px;">
            <button class="btn btn-muted btn-sm" onclick="closeDmLauncher()">Done</button>
            <button class="btn btn-primary btn-sm" onclick="dmOpenAll()">Open all (sequential)</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Bulk DM modal (shared message for all selected) -->
    <div class="modal-backdrop" id="bulkDmBackdrop">
      <div class="modal large">
        <div class="modal-head">
          <div class="modal-title" style="margin-bottom:6px;">Bulk DM <span id="bulkDmCount" style="color:var(--text-muted); font-weight:500;"></span></div>
          <div class="modal-body" style="font-size:13px; margin-bottom:12px;" id="bulkDmIntro">
            Type the message. We'll copy it to your clipboard and show one link per profile — click each to open the IG tab, paste with <span style="font-family:'JetBrains Mono',monospace; background:var(--bg-elev); border:1px solid var(--border); padding:1px 6px; border-radius:5px; font-size:11px;">Cmd+V</span>, hit Enter.
          </div>
          <textarea id="bulkDmMessage" placeholder="Hey! Saw you and wanted to connect."></textarea>
          <div class="dim tiny" style="font-size:11px; margin-top:6px;">Same message for all — no personalization. Use <b>DM Launcher</b> for per-recipient {name} substitution. Saved automatically.</div>
        </div>
        <div class="modal-content" id="bulkDmList" style="display:none;"></div>
        <div class="modal-foot">
          <div class="dim" style="font-size:12px;" id="bulkDmFootNote"></div>
          <div style="display:flex; gap:8px;">
            <button class="btn btn-muted btn-sm" id="bulkDmCancel">Close</button>
            <button class="btn btn-primary btn-sm" id="bulkDmGo">Prepare links</button>
            <button class="btn btn-muted btn-sm" id="bulkDmTryAll" style="display:none;">Try opening all (popups must be allowed)</button>
          </div>
        </div>
      </div>
    </div>

    <div class="dm-toast" id="dmToast"></div>

    <div class="empty" id="emptyState">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <div class="empty-title">Enter a handle to get started</div>
      <div class="empty-sub">Try <span style="color:var(--accent);">dynastyrewards</span>, <span style="color:var(--accent);">humansofny</span>, or any public IG account.</div>
    </div>
    </div><!-- /igTab -->

    <!-- Leaderboard tab -->
    <div id="lbTab" style="display:none;">
      <section class="hero">
        <h1>Scrape a leaderboard</h1>
        <p>Pull player data from any public rankings page. Filter by country and activity, then export to CSV.</p>
        <form id="lbForm">
          <div class="lb-form-grid">
            <div class="field">
              <label for="lbUrl">Leaderboard URL</label>
              <input id="lbUrl" name="lbUrl" placeholder="https://pokerdb.thehendonmob.com/ranking/all-time-money-list/" value="https://pokerdb.thehendonmob.com/ranking/all-time-money-list/" required autocomplete="off">
            </div>
            <div class="field">
              <label for="lbMax">Max players</label>
              <input id="lbMax" name="lbMax" type="number" min="10" max="200" value="50">
            </div>
            <div class="field">
              <label for="lbStartPage">Start page</label>
              <input id="lbStartPage" name="lbStartPage" type="number" min="1" value="1" title="Or put the page number in the URL, e.g. .../all-time-money-list/3">
            </div>
            <div class="field">
              <label for="lbPages"># Pages (max 10)</label>
              <select id="lbPages" name="lbPages">
                <option value="1">1 page (~100)</option>
                <option value="2">2 pages (~200)</option>
                <option value="3">3 pages (~300)</option>
                <option value="5">5 pages (~500)</option>
                <option value="10">10 pages (~1000)</option>
              </select>
            </div>
            <div class="field">
              <label for="lbMonths">Active within</label>
              <select id="lbMonths" name="lbMonths">
                <option value="12">1 year</option>
                <option value="24">2 years</option>
                <option value="36">3 years</option>
                <option value="0">Any time</option>
              </select>
            </div>
            <button type="submit" id="lbBtn" class="btn btn-primary">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
              Scrape
            </button>
          </div>
          <div class="lb-meta">
            <label>
              <input type="checkbox" id="lbUsOnly" checked> US players only
            </label>
            <span class="dim">·</span>
            <label>
              <input type="checkbox" id="lbProfiles"> Visit each profile for city/state &amp; social links
            </label>
            <span class="dim">·</span>
            <span class="dim">Profile visits add ~3s per player. A page number in the URL overrides “Start page”. For the full list use the harvest CLI.</span>
          </div>
        </form>
      </section>

      <div class="status" id="lbStatus"></div>

      <section class="results-card" id="lbResultsCard">
        <div class="results-head">
          <h2>
            Results
            <span class="chip" id="lbChip">0</span>
          </h2>
          <div class="toolbar">
            <button class="btn btn-muted btn-sm" onclick="enrichLbContacts()" id="lbEnrichBtn">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
              Enrich Contacts
            </button>
            <button class="btn btn-muted btn-sm" onclick="exportLbCSV()">CSV</button>
          </div>
        </div>
        <div class="filter-bar">
          <input type="text" class="search-input" id="lbSearch" placeholder="Search name..." oninput="renderLbTable()">
          <span class="filter-stat" id="lbFilterStat"></span>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr id="lbTableHead"></tr></thead>
            <tbody id="lbTableBody"></tbody>
          </table>
        </div>
      </section>
    </div><!-- /lbTab -->
  </main>

  <script>
    const COST_PER_FOLLOWER = """ + f"{COST_PER_FOLLOWER}" + """;
    const COST_PER_PROFILE = """ + f"{COST_PER_PROFILE}" + """;

    let currentData = [];
    let hasDetails = false;
    let statusFilter = 'all';
    let sortCol = null;
    let sortDir = 'asc';
    let lastCheckedIdx = null;
    let igEnrichData = {};
    let lbEnrichData = {};

    // --- Modal ---
    function appConfirm({ title, body, okLabel = 'Confirm', cancelLabel = 'Cancel' }) {
      return new Promise(resolve => {
        const backdrop = document.getElementById('modalBackdrop');
        const ok = document.getElementById('modalOk');
        const cancel = document.getElementById('modalCancel');
        document.getElementById('modalTitle').textContent = title;
        document.getElementById('modalBody').innerHTML = body;
        ok.textContent = okLabel;
        cancel.textContent = cancelLabel;
        backdrop.classList.add('visible');

        const close = (val) => {
          backdrop.classList.remove('visible');
          ok.removeEventListener('click', okHandler);
          cancel.removeEventListener('click', cancelHandler);
          backdrop.removeEventListener('click', bgHandler);
          document.removeEventListener('keydown', keyHandler);
          resolve(val);
        };
        const okHandler = () => close(true);
        const cancelHandler = () => close(false);
        const bgHandler = (e) => { if (e.target === backdrop) close(false); };
        const keyHandler = (e) => {
          if (e.key === 'Escape') close(false);
          else if (e.key === 'Enter') close(true);
        };
        ok.addEventListener('click', okHandler);
        cancel.addEventListener('click', cancelHandler);
        backdrop.addEventListener('click', bgHandler);
        document.addEventListener('keydown', keyHandler);
        ok.focus();
      });
    }

    // --- Cost preview (live) ---
    function updateCostTag() {
      const limit = parseInt(document.getElementById('limit').value) || 0;
      const cost = limit * COST_PER_FOLLOWER;
      document.getElementById('costTag').textContent = '~$' + cost.toFixed(2);
    }
    document.getElementById('limit').addEventListener('input', updateCostTag);
    updateCostTag();

    // --- Scrape ---
    document.getElementById('scrapeForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const usernames = document.getElementById('usernames').value.trim();
      const limit = parseInt(document.getElementById('limit').value) || 200;
      const type = document.getElementById('type').value;
      if (!usernames) return;

      const btn = document.getElementById('submitBtn');
      const status = document.getElementById('status');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Scraping';
      status.className = 'status visible';
      status.innerHTML = '<span class="spinner"></span><span>Calling Apify — this usually takes 10–60 seconds...</span>';
      document.getElementById('emptyState').style.display = 'none';
      document.getElementById('resultsCard').classList.remove('visible');
      document.getElementById('detailsChip').style.display = 'none';
      document.getElementById('bioInput').style.display = 'none';
      hasDetails = false;

      try {
        const res = await fetch('/api/scrape', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ usernames, limit, type })
        });
        const data = await res.json();
        if (data.error) {
          status.className = 'status visible error';
          status.textContent = data.error;
        } else {
          currentData = data.results;
          status.className = 'status visible success';
          status.innerHTML = `<span>✓ Scraped <b>${data.results.length}</b> ${type.toLowerCase()} in ${data.elapsed}s</span>`;
          renderTable();
          document.getElementById('resultsCard').classList.add('visible');
        }
      } catch (err) {
        status.className = 'status visible error';
        status.textContent = 'Request failed: ' + err.message;
      } finally {
        btn.disabled = false;
        btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="13 17 18 12 13 7"/><polyline points="6 17 11 12 6 7"/></svg> Scrape`;
      }
    });

    // --- Profile details ---
    async function fetchProfileDetails() {
      const selected = getSelectedFromVisible();
      const targets = selected.length ? selected : currentData.map(r => r.username);
      if (!targets.length) return;

      const cost = (targets.length * COST_PER_PROFILE).toFixed(2);
      const scope = selected.length ? `<b>${selected.length} selected</b>` : `<b>all ${targets.length}</b>`;
      const ok = await appConfirm({
        title: 'Fetch profile details',
        body: `Pull bio, follower count, and post count for ${scope} profile${targets.length === 1 ? '' : 's'}.<br><span class="modal-cost">Estimated cost ~$${cost}</span>`,
        okLabel: 'Fetch details',
      });
      if (!ok) return;

      const btn = document.getElementById('detailsBtn');
      const status = document.getElementById('status');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Fetching';
      status.className = 'status visible';
      status.innerHTML = `<span class="spinner"></span><span>Fetching profile details for ${targets.length} handles...</span>`;

      try {
        const res = await fetch('/api/profile-details', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ usernames: targets })
        });
        const data = await res.json();
        if (data.error) {
          status.className = 'status visible error';
          status.textContent = data.error;
        } else {
          // Merge details into currentData by username (case-insensitive)
          const map = {};
          (data.results || []).forEach(d => { if (d.username) map[d.username.toLowerCase()] = d; });
          let matched = 0;
          currentData.forEach(row => {
            const d = map[(row.username || '').toLowerCase()];
            if (d) {
              row.biography = d.biography || row.biography || '';
              row.followers_count = d.followersCount ?? d.followers_count ?? row.followers_count;
              row.follows_count = d.followsCount ?? d.follows_count ?? row.follows_count;
              row.posts_count = d.postsCount ?? d.posts_count ?? row.posts_count;
              row.external_url = d.externalUrl || d.external_url || row.external_url;
              matched++;
            }
          });
          hasDetails = true;
          document.getElementById('detailsChip').style.display = 'inline-flex';
          document.getElementById('bioInput').style.display = 'inline-block';
          status.className = 'status visible success';
          status.innerHTML = `<span>✓ Got profile details for <b>${matched}</b> of ${targets.length} in ${data.elapsed}s</span>`;
          renderTable();
        }
      } catch (err) {
        status.className = 'status visible error';
        status.textContent = 'Request failed: ' + err.message;
      } finally {
        btn.disabled = false;
        btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg> Get profile details`;
      }
    }

    // --- Filter / sort ---
    function setStatusFilter(s) {
      statusFilter = s;
      document.querySelectorAll('.filter-pill').forEach(p => p.classList.toggle('active', p.dataset.status === s));
      renderTable();
    }

    function applyFilters(rows) {
      const search = document.getElementById('searchInput').value.toLowerCase().trim();
      const bioKw = document.getElementById('bioInput').value.toLowerCase().trim();
      return rows.filter(r => {
        if (statusFilter === 'public' && r.is_private) return false;
        if (statusFilter === 'private' && !r.is_private) return false;
        if (statusFilter === 'verified' && !r.is_verified) return false;
        if (search) {
          const hay = (r.username + ' ' + (r.full_name || '')).toLowerCase();
          if (!hay.includes(search)) return false;
        }
        if (bioKw) {
          const bio = (r.biography || '').toLowerCase();
          if (!bio.includes(bioKw)) return false;
        }
        return true;
      });
    }

    function applySort(rows) {
      if (!sortCol) return rows;
      const col = sortCol, dir = sortDir === 'asc' ? 1 : -1;
      const get = r => {
        switch (col) {
          case 'username': return (r.username || '').toLowerCase();
          case 'full_name': return (r.full_name || '').toLowerCase();
          case 'is_verified': return r.is_verified ? 1 : 0;
          case 'is_private': return r.is_private ? 1 : 0;
          case 'followers_count': return r.followers_count ?? -1;
          case 'posts_count': return r.posts_count ?? -1;
          default: return '';
        }
      };
      return [...rows].sort((a, b) => {
        const av = get(a), bv = get(b);
        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;
        return 0;
      });
    }

    function clickSort(col) {
      if (sortCol === col) sortDir = (sortDir === 'asc') ? 'desc' : 'asc';
      else { sortCol = col; sortDir = 'asc'; }
      renderTable();
    }

    // --- Selection ---
    function getSelectedFromVisible() {
      return [...document.querySelectorAll('.row-check:checked')]
        .map(cb => cb.dataset.username).filter(Boolean);
    }

    function updateSelectCount() {
      const n = getSelectedFromVisible().length;
      document.getElementById('selectedCount').textContent = n;
      document.getElementById('selectBar').classList.toggle('visible', n > 0);
    }

    function onRowCheck(ev, cb) {
      const allRows = [...document.querySelectorAll('tbody tr')];
      const tr = cb.closest('tr');
      const idx = allRows.indexOf(tr);

      if (ev.shiftKey && lastCheckedIdx !== null && lastCheckedIdx !== idx) {
        const [a, b] = idx < lastCheckedIdx ? [idx, lastCheckedIdx] : [lastCheckedIdx, idx];
        for (let i = a; i <= b; i++) {
          const c = allRows[i].querySelector('.row-check');
          if (c) {
            c.checked = cb.checked;
            allRows[i].classList.toggle('selected', cb.checked);
          }
        }
      } else {
        tr.classList.toggle('selected', cb.checked);
      }
      lastCheckedIdx = idx;
      updateSelectCount();
    }

    function toggleSelectAll(el) {
      document.querySelectorAll('tbody .row-check').forEach(cb => { cb.checked = el.checked; cb.closest('tr').classList.toggle('selected', el.checked); });
      lastCheckedIdx = null;
      updateSelectCount();
    }

    function selectAll() {
      document.querySelectorAll('tbody .row-check').forEach(cb => { cb.checked = true; cb.closest('tr').classList.add('selected'); });
      const h = document.getElementById('headerCheck'); if (h) h.checked = true;
      updateSelectCount();
    }

    function deselectAll() {
      document.querySelectorAll('tbody .row-check').forEach(cb => { cb.checked = false; cb.closest('tr').classList.remove('selected'); });
      const h = document.getElementById('headerCheck'); if (h) h.checked = false;
      updateSelectCount();
    }

    // --- DM Launcher ---
    let dmQueue = [];  // [{username, full_name, sent: bool, skipped: bool}]

    function openDmLauncher() {
      const selected = getSelectedFromVisible();
      if (!selected.length) {
        appConfirm({ title: 'No profiles selected', body: 'Select at least one profile to DM.', okLabel: 'OK', cancelLabel: '' });
        return;
      }
      // Build queue from selected usernames, preserving order from currentData
      const map = {};
      currentData.forEach(r => { if (r.username) map[r.username] = r; });
      dmQueue = selected.map(u => ({
        username: u,
        full_name: (map[u] && map[u].full_name) || '',
        sent: false,
        skipped: false,
      }));
      renderDmQueue();
      document.getElementById('dmModalBackdrop').classList.add('visible');
      document.getElementById('dmTemplate').addEventListener('input', renderDmQueue);
    }

    function closeDmLauncher() {
      document.getElementById('dmModalBackdrop').classList.remove('visible');
    }

    function personalizeMessage(template, row) {
      const fullName = (row.full_name || '').trim();
      const firstName = fullName ? fullName.split(/\\s+/)[0] : row.username;
      return template
        .replace(/\\{name\\}/g, firstName)
        .replace(/\\{username\\}/g, row.username);
    }

    function renderDmQueue() {
      const tmpl = document.getElementById('dmTemplate').value;
      const list = document.getElementById('dmQueueList');
      const sentN = dmQueue.filter(r => r.sent).length;
      document.getElementById('dmProgress').textContent = `${sentN} of ${dmQueue.length} sent`;
      list.innerHTML = dmQueue.map((row, i) => {
        const msg = personalizeMessage(tmpl, row);
        const stateBadge = row.sent
          ? '<span class="dm-status">✓ Sent</span>'
          : (row.skipped ? '<span class="dm-status skipped">Skipped</span>' : '');
        const rowClass = row.sent || row.skipped ? 'dm-row sent' : 'dm-row';
        const actions = (row.sent || row.skipped)
          ? `<button class="btn btn-muted btn-xs" onclick="dmReset(${i})">Reset</button>`
          : `<button class="btn btn-muted btn-xs" onclick="dmSkip(${i})">Skip</button>
             <button class="btn btn-primary btn-xs" onclick="dmOpenOne(${i})">Open + Copy</button>`;
        return `
          <div class="${rowClass}">
            <div class="dm-num">${i + 1}</div>
            <div class="dm-handle"><a href="https://instagram.com/${row.username}" target="_blank">@${row.username}</a><div class="dim" style="font-size:11px; font-weight:400;">${escapeHtml(row.full_name || '')}</div></div>
            <div class="dm-msg" title="${escapeHtml(msg)}">${escapeHtml(msg)}</div>
            <div>${stateBadge}</div>
            <div class="dm-actions">${actions}</div>
          </div>
        `;
      }).join('');
    }

    async function dmOpenOne(idx) {
      const row = dmQueue[idx];
      if (!row || row.sent) return;
      const tmpl = document.getElementById('dmTemplate').value;
      const msg = personalizeMessage(tmpl, row);

      // Copy to clipboard first, then open the tab. Order matters: clipboard write
      // must happen inside the user-gesture handler before window.open redirects focus.
      try {
        await navigator.clipboard.writeText(msg);
      } catch (err) {
        showToast('Clipboard write failed — message: ' + msg.slice(0, 80), false);
      }
      window.open(`https://www.instagram.com/${row.username}/`, '_blank', 'noopener');
      showToast(`Opened @${row.username} · message copied. Paste with Cmd+V`, true);
      row.sent = true;
      row.skipped = false;
      renderDmQueue();
    }

    function dmSkip(idx) {
      if (!dmQueue[idx]) return;
      dmQueue[idx].skipped = true;
      dmQueue[idx].sent = false;
      renderDmQueue();
    }

    function dmReset(idx) {
      if (!dmQueue[idx]) return;
      dmQueue[idx].sent = false;
      dmQueue[idx].skipped = false;
      renderDmQueue();
    }

    async function dmOpenAll() {
      const remaining = dmQueue.filter(r => !r.sent && !r.skipped).length;
      if (!remaining) return;
      const ok = await appConfirm({
        title: `Open ${remaining} IG tabs?`,
        body: `Tabs will open one at a time with a 600ms delay so your browser doesn't block popups. The clipboard will hold the <b>last opened</b> recipient's message — for batch sends, use <b>Open + Copy</b> per row instead.`,
        okLabel: 'Open all',
      });
      if (!ok) return;
      for (let i = 0; i < dmQueue.length; i++) {
        const row = dmQueue[i];
        if (row.sent || row.skipped) continue;
        const tmpl = document.getElementById('dmTemplate').value;
        const msg = personalizeMessage(tmpl, row);
        try { await navigator.clipboard.writeText(msg); } catch {}
        window.open(`https://www.instagram.com/${row.username}/`, '_blank', 'noopener');
        row.sent = true;
        renderDmQueue();
        await new Promise(r => setTimeout(r, 600));
      }
      showToast('All tabs opened. Switch to each and paste with Cmd+V', true);
    }

    // --- Bulk DM (shared message) ---
    let bulkDmSelected = [];
    let bulkDmMsgCache = '';

    function bulkDmOpen() {
      const selected = getSelectedFromVisible();
      if (!selected.length) { showToast('Select at least one profile first', false); return; }
      bulkDmSelected = selected;

      const backdrop = document.getElementById('bulkDmBackdrop');
      const textarea = document.getElementById('bulkDmMessage');
      const goBtn = document.getElementById('bulkDmGo');
      const cancelBtn = document.getElementById('bulkDmCancel');
      const tryAllBtn = document.getElementById('bulkDmTryAll');
      const list = document.getElementById('bulkDmList');
      const intro = document.getElementById('bulkDmIntro');
      const footNote = document.getElementById('bulkDmFootNote');

      // Reset to "compose" stage
      list.style.display = 'none';
      list.innerHTML = '';
      tryAllBtn.style.display = 'none';
      goBtn.style.display = '';
      goBtn.textContent = 'Prepare links';
      textarea.style.display = '';
      intro.style.display = '';
      footNote.textContent = '';

      document.getElementById('bulkDmCount').textContent = `· ${selected.length} ${selected.length === 1 ? 'profile' : 'profiles'}`;
      textarea.value = localStorage.getItem('bulkDmMessage') || 'Hey! Saw you and wanted to connect.';
      backdrop.classList.add('visible');
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length, textarea.value.length);

      const close = () => {
        backdrop.classList.remove('visible');
        goBtn.removeEventListener('click', goHandler);
        cancelBtn.removeEventListener('click', cancelHandler);
        tryAllBtn.removeEventListener('click', tryAllHandler);
        backdrop.removeEventListener('click', bgHandler);
        document.removeEventListener('keydown', keyHandler);
      };
      const goHandler = () => {
        const msg = textarea.value.trim();
        if (!msg) { textarea.focus(); return; }
        localStorage.setItem('bulkDmMessage', msg);
        bulkDmMsgCache = msg;
        // Copy to clipboard immediately on user gesture.
        navigator.clipboard.writeText(msg).catch(() => {});
        // Switch modal into "click each link" mode
        renderBulkDmList(selected);
        textarea.style.display = 'none';
        intro.style.display = 'none';
        list.style.display = '';
        goBtn.style.display = 'none';
        tryAllBtn.style.display = '';
        footNote.innerHTML = `✓ Message copied to clipboard. Click each handle below — your browser opens 1 tab per click (no popup blocker).`;
      };
      const tryAllHandler = () => {
        // Synchronous loop, single user gesture. Works only if user has allowed popups.
        let opened = 0, blocked = 0;
        for (const u of bulkDmSelected) {
          const w = window.open(`https://www.instagram.com/${u}/`, '_blank', 'noopener');
          if (w) { opened++; markBulkLinkOpened(u); } else blocked++;
        }
        if (blocked > 0) {
          footNote.innerHTML = `<span style="color:#fca5a5;">${blocked} of ${bulkDmSelected.length} blocked.</span> Click the popup-blocked icon in your address bar → "Always allow for localhost:3002" → retry. Or click handles individually below.`;
        } else {
          footNote.innerHTML = `<span style="color:#a7f3d0;">All ${opened} tabs open.</span>`;
        }
      };
      const cancelHandler = () => close();
      const bgHandler = (e) => { if (e.target === backdrop) close(); };
      const keyHandler = (e) => {
        if (e.key === 'Escape') close();
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && goBtn.style.display !== 'none') goHandler();
      };
      goBtn.addEventListener('click', goHandler);
      cancelBtn.addEventListener('click', cancelHandler);
      tryAllBtn.addEventListener('click', tryAllHandler);
      backdrop.addEventListener('click', bgHandler);
      document.addEventListener('keydown', keyHandler);
    }

    function renderBulkDmList(usernames) {
      const list = document.getElementById('bulkDmList');
      const map = {};
      currentData.forEach(r => { if (r.username) map[r.username] = r; });
      list.innerHTML = '<div class="bulk-grid">' + usernames.map(u => {
        const row = map[u] || {};
        const fullName = escapeHtml(row.full_name || '');
        return `<a class="bulk-link" href="https://www.instagram.com/${u}/" target="_blank" rel="noopener" data-username="${u}" onclick="markBulkLinkOpened('${u}')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          <span class="name">@${escapeHtml(u)}</span>
        </a>`;
      }).join('') + '</div>';
    }

    function markBulkLinkOpened(username) {
      const el = document.querySelector(`.bulk-link[data-username="${CSS.escape(username)}"]`);
      if (el) el.classList.add('opened');
      // Re-write clipboard on each click in case the user has copied something else in between.
      if (bulkDmMsgCache) navigator.clipboard.writeText(bulkDmMsgCache).catch(() => {});
    }

    function showToast(msg, success) {
      const toast = document.getElementById('dmToast');
      toast.className = 'dm-toast visible' + (success ? ' success' : '');
      toast.innerHTML = success
        ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> ${escapeHtml(msg)}`
        : escapeHtml(msg);
      clearTimeout(showToast._t);
      showToast._t = setTimeout(() => { toast.classList.remove('visible'); }, 3500);
    }

    async function openSelectedInIG() {
      const selected = getSelectedFromVisible();
      if (!selected.length) return;
      if (selected.length > 15) {
        const ok = await appConfirm({
          title: `Open ${selected.length} Instagram tabs?`,
          body: `This will open <b>${selected.length}</b> new tabs at once. Your browser may block popups — you'll see a popup-blocked icon in the address bar if so.`,
          okLabel: 'Open tabs',
        });
        if (!ok) return;
      }
      selected.forEach(u => window.open('https://instagram.com/' + u, '_blank', 'noopener'));
    }

    // --- Render ---
    function avatarFor(item) {
      if (item.profile_pic_url) {
        const initial = (item.username || '?')[0].toUpperCase();
        return `<a href="https://instagram.com/${item.username}" target="_blank"><img class="avatar" src="${item.profile_pic_url}" alt="" loading="lazy" onerror="this.outerHTML='<div class=avatar-fallback>${initial}</div>';"></a>`;
      }
      const initial = (item.username || '?')[0].toUpperCase();
      return `<div class="avatar-fallback">${initial}</div>`;
    }

    function fmtNum(n) {
      if (n == null) return '—';
      if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
      if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
      return String(n);
    }

    function buildHeader() {
      const cols = [
        { key: 'check', label: '<input type="checkbox" class="row-check" onchange="toggleSelectAll(this)" id="headerCheck">', sort: false, w: '32px' },
        { key: 'avatar', label: '', sort: false, w: '44px' },
        { key: 'username', label: 'Username', sort: true },
        { key: 'full_name', label: 'Full name', sort: true },
        { key: 'is_verified', label: 'Status', sort: true },
      ];
      if (hasDetails) {
        cols.push({ key: 'followers_count', label: 'Followers', sort: true, align: 'right' });
        cols.push({ key: 'posts_count', label: 'Posts', sort: true, align: 'right' });
        cols.push({ key: 'biography', label: 'Bio', sort: false });
      } else {
        cols.push({ key: 'username_scrape', label: 'Source', sort: false });
      }
      if (Object.keys(igEnrichData).length > 0) {
        cols.push({ key: 'email', label: 'Email', sort: false });
        cols.push({ key: 'phone', label: 'Phone', sort: false });
        cols.push({ key: 'match', label: 'Match', sort: false });
      }
      return cols.map(c => {
        const isSorted = sortCol === c.key;
        const arrow = c.sort ? `<span class="sort-arrow">${isSorted ? (sortDir === 'asc' ? '▲' : '▼') : '▲▼'}</span>` : '';
        const cls = (c.sort ? 'sortable ' : '') + (isSorted ? 'sorted' : '');
        const onclick = c.sort ? ` onclick="clickSort('${c.key}')"` : '';
        const style = (c.w ? `width:${c.w};` : '') + (c.align === 'right' ? 'text-align:right;' : '');
        return `<th class="${cls}" style="${style}"${onclick}>${c.label}${arrow}</th>`;
      }).join('');
    }

    function renderTable() {
      const filtered = applySort(applyFilters(currentData));
      document.getElementById('tableHeader').innerHTML = buildHeader();

      const stat = document.getElementById('filterStat');
      if (filtered.length === currentData.length) stat.textContent = `${currentData.length} rows`;
      else stat.textContent = `${filtered.length} of ${currentData.length} rows`;

      const body = document.getElementById('resultsBody');
      body.innerHTML = filtered.map(item => {
        const checkCell = `<td><input type="checkbox" class="row-check" data-username="${item.username}" onclick="onRowCheck(event, this)"></td>`;
        const avatarCell = `<td>${avatarFor(item)}</td>`;
        const usernameCell = `<td><a class="handle" href="https://instagram.com/${item.username}" target="_blank">@${item.username}</a></td>`;
        const nameCell = `<td>${escapeHtml(item.full_name || '')}</td>`;
        const statusCell = `<td>${item.is_verified ? '<span class="badge verified">✓ Verified</span> ' : ''}${item.is_private ? '<span class="badge private">Private</span>' : '<span class="badge public">Public</span>'}</td>`;

        let extra = '';
        if (hasDetails) {
          extra += `<td class="num-cell">${fmtNum(item.followers_count)}</td>`;
          extra += `<td class="num-cell">${fmtNum(item.posts_count)}</td>`;
          extra += `<td class="bio-cell">${escapeHtml(item.biography || '').slice(0, 240) || '<span class="dim">—</span>'}</td>`;
        } else {
          extra += `<td><a class="sub-handle" href="https://instagram.com/${item.username_scrape || ''}" target="_blank">@${item.username_scrape || '—'}</a></td>`;
        }
        if (Object.keys(igEnrichData).length > 0) {
          const key = item.full_name || item.username;
          const enr = igEnrichData[key] || {};
          const email = (enr.emails || [])[0] || '';
          const phone = (enr.phones || [])[0] || '';
          const conf = enr.confidence || 'none';
          const confCls = conf === 'high' ? 'conf-high' : conf === 'medium' ? 'conf-medium' : conf === 'low' ? 'conf-low' : '';
          extra += `<td class="email-cell">${email ? `<a href="mailto:${escapeHtml(email)}" style="color:inherit;text-decoration:none;">${escapeHtml(email)}</a>` : '<span class="dim">—</span>'}</td>`;
          extra += `<td class="phone-cell">${escapeHtml(phone) || '<span class="dim">—</span>'}</td>`;
          extra += `<td>${email ? `<span class="conf-badge ${confCls}">${conf}</span>` : '<span class="dim">—</span>'}</td>`;
        }
        return `<tr>${checkCell}${avatarCell}${usernameCell}${nameCell}${statusCell}${extra}</tr>`;
      }).join('');
      updateSelectCount();
    }

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    function exportCSV() {
      if (!currentData.length) return;
      const hasEnrich = Object.keys(igEnrichData).length > 0;
      const rows = applySort(applyFilters(currentData));
      const baseHeaders = ['username', 'full_name', 'id', 'is_private', 'is_verified', 'username_scrape'];
      if (hasDetails) baseHeaders.push('biography', 'followers_count', 'follows_count', 'posts_count', 'external_url');
      const headers = [...baseHeaders, ...(hasEnrich ? ['email', 'phone', 'confidence'] : [])];
      const out = rows.map(r => {
        const baseVals = baseHeaders.map(h => {
          let val = r[h];
          if (Array.isArray(val)) val = val.join('; ');
          return '"' + String(val ?? '').replace(/"/g, '""') + '"';
        });
        if (hasEnrich) {
          const enr = igEnrichData[r.full_name || r.username] || {};
          baseVals.push('"' + ((enr.emails || [])[0] || '') + '"');
          baseVals.push('"' + ((enr.phones || [])[0] || '') + '"');
          baseVals.push('"' + (enr.confidence || '') + '"');
        }
        return baseVals.join(',');
      });
      download([headers.join(','), ...out].join('\\n'), 'followers.csv', 'text/csv');
    }

    function exportJSON() {
      if (!currentData.length) return;
      const rows = applySort(applyFilters(currentData));
      download(JSON.stringify(rows, null, 2), 'followers.json', 'application/json');
    }

    function download(content, filename, mime) {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([content], { type: mime }));
      a.download = filename;
      a.click();
    }

    // ── Tab switching ────────────────────────────────────────────────────────
    function switchTab(tab) {
      document.getElementById('igTab').style.display  = tab === 'ig' ? '' : 'none';
      document.getElementById('lbTab').style.display  = tab === 'lb' ? '' : 'none';
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
      const subs = { ig: '· Instagram outreach', lb: '· Leaderboard scraper' };
      document.getElementById('brandSub').textContent = subs[tab] || '';
    }

    // ── Leaderboard scraper ──────────────────────────────────────────────────
    let lbData = [];

    document.getElementById('lbForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const url      = document.getElementById('lbUrl').value.trim();
      const max      = parseInt(document.getElementById('lbMax').value) || 50;
      const months   = parseInt(document.getElementById('lbMonths').value);
      const usOnly    = document.getElementById('lbUsOnly').checked;
      const pages     = document.getElementById('lbPages').value;
      const startPage = parseInt(document.getElementById('lbStartPage').value) || 1;
      const profiles  = document.getElementById('lbProfiles').checked;

      const isHendon = url.includes('thehendonmob.com');
      const btn    = document.getElementById('lbBtn');
      const status = document.getElementById('lbStatus');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Scraping';
      status.className = 'status visible';
      const waitMsg = isHendon
        ? ('Scraping The Hendon Mob — a Chrome window will open to clear the Cloudflare check. ~7s per page'
           + (profiles ? ', plus ~3s per player for profile details.' : '.'))
        : 'Scraping leaderboard and player profiles — this may take 30–90 seconds...';
      status.innerHTML = `<span class="spinner"></span><span>${waitMsg}</span>`;
      document.getElementById('lbResultsCard').classList.remove('visible');

      try {
        const res  = await fetch('/api/scrape-leaderboard', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, max_players: max, months_active: months, us_only: usOnly, pages, start_page: startPage, fetch_profiles: profiles }),
        });
        const data = await res.json();
        if (data.error) {
          status.className = 'status visible error';
          status.textContent = data.error;
        } else {
          lbData = data.results;
          document.getElementById('lbChip').textContent = lbData.length;
          status.className = 'status visible success';
          status.innerHTML = `<span>✓ Found <b>${lbData.length}</b> players in ${data.elapsed}s</span>`;
          renderLbTable();
          document.getElementById('lbResultsCard').classList.add('visible');
        }
      } catch (err) {
        status.className = 'status visible error';
        status.textContent = 'Request failed: ' + err.message;
      } finally {
        btn.disabled = false;
        btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg> Scrape`;
      }
    });

    function renderLbTable() {
      const hasEnrich = Object.keys(lbEnrichData).length > 0;
      const search  = document.getElementById('lbSearch').value.toLowerCase();
      const rows    = lbData.filter(p => !search || (p.name || '').toLowerCase().includes(search));
      const stat    = document.getElementById('lbFilterStat');
      stat.textContent = rows.length === lbData.length ? `${lbData.length} players` : `${rows.length} of ${lbData.length} players`;

      const cols = ['Rank', 'Name', 'Metric', 'Country', 'State / City', 'Last Active', 'Links'];
      if (hasEnrich) cols.push('Email', 'Phone', 'Socials', 'Match');
      document.getElementById('lbTableHead').innerHTML = cols.map(c => `<th>${c}</th>`).join('');

      const currentYear = new Date().getFullYear();
      document.getElementById('lbTableBody').innerHTML = rows.map(p => {
        const q      = encodeURIComponent(`"${p.name}" poker player site:linkedin.com`);
        const liLink = `<a class="search-link" href="https://www.google.com/search?q=${q}" target="_blank" rel="noopener">LinkedIn ↗</a>`;
        const profileLinks = Object.entries(p.profiles || {}).map(([net, url]) =>
          `<a class="search-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">${net} ↗</a>`).join(' ');
        const yearCls = p.last_active_year && p.last_active_year < currentYear - 1 ? 'year-cell stale-year' : 'year-cell';
        let enrichCells = '';
        if (hasEnrich) {
          const enr = lbEnrichData[p.name] || {};
          const email = (enr.emails || [])[0] || '';
          const phone = (enr.phones || [])[0] || '';
          const conf = enr.confidence || 'none';
          const confCls = conf === 'high' ? 'conf-high' : conf === 'medium' ? 'conf-medium' : conf === 'low' ? 'conf-low' : '';
          const profiles = enr.profiles || {};
          const socialLinks = Object.entries(profiles).map(([net, url]) =>
            `<a class="search-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">${net} ↗</a>`
          ).join(' ');
          const hasAny = email || phone || socialLinks;
          enrichCells = `
            <td class="email-cell">${email ? `<a href="mailto:${escapeHtml(email)}" style="color:inherit;text-decoration:none;">${escapeHtml(email)}</a>` : '<span class="dim">—</span>'}</td>
            <td class="phone-cell">${escapeHtml(phone) || '<span class="dim">—</span>'}</td>
            <td style="font-size:12px;">${socialLinks || '<span class="dim">—</span>'}</td>
            <td>${hasAny ? `<span class="conf-badge ${confCls}">${conf}</span>` : '<span class="dim">—</span>'}</td>`;
        }
        return `<tr>
          <td class="num-cell">${p.rank ?? '—'}</td>
          <td style="font-weight:500;">${escapeHtml(p.name || '')}</td>
          <td class="earnings-cell">${escapeHtml(p.metric || '—')}</td>
          <td style="font-size:13px;color:var(--text-muted);">${escapeHtml(p.country || '—')}</td>
          <td style="font-size:13px;">${escapeHtml(p.city_state || '—')}</td>
          <td class="${yearCls}">${p.last_active_year ?? '—'}</td>
          <td style="font-size:12px;">${profileLinks ? profileLinks + ' ' : ''}${liLink}</td>
          ${enrichCells}
        </tr>`;
      }).join('');
    }

    function exportLbCSV() {
      if (!lbData.length) return;
      const hasEnrich = Object.keys(lbEnrichData).length > 0;
      const hasSocials = lbData.some(r => r.profiles && Object.keys(r.profiles).length);
      const baseHeaders = ['rank', 'name', 'metric', 'country', 'city_state', 'last_active_year'];
      const headers = [...baseHeaders, ...(hasSocials ? ['socials'] : []), ...(hasEnrich ? ['email', 'phone', 'confidence'] : [])];
      const out = lbData.map(r => {
        const vals = baseHeaders.map(h => '"' + String(r[h] ?? '').replace(/"/g, '""') + '"');
        if (hasSocials) {
          vals.push('"' + Object.values(r.profiles || {}).join(' ').replace(/"/g, '""') + '"');
        }
        if (hasEnrich) {
          const enr = lbEnrichData[r.name] || {};
          vals.push('"' + ((enr.emails || [])[0] || '') + '"');
          vals.push('"' + ((enr.phones || [])[0] || '') + '"');
          vals.push('"' + (enr.confidence || '') + '"');
        }
        return vals.join(',');
      });
      download([headers.join(','), ...out].join('\\n'), 'leaderboard.csv', 'text/csv');
    }

    // ── Contact enrichment ───────────────────────────────────────────────────

    const _enrichIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`;

    async function enrichLbContacts() {
      if (!lbData.length) return;
      const btn    = document.getElementById('lbEnrichBtn');
      const status = document.getElementById('lbStatus');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Enriching...';
      status.className = 'status visible';
      status.innerHTML = `<span class="spinner"></span><span>Enriching via People Data Labs — ~${lbData.length * 0.2}s estimated...</span>`;

      const lbUrl   = document.getElementById('lbUrl').value;
      const profHint = lbUrl.includes('wsop.com') ? 'poker player' : '';

      try {
        const res  = await fetch('/api/enrich-contacts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            players: lbData.map(p => ({ name: p.name, country: p.country })),
            profession_hint: profHint,
          })
        });
        const data = await res.json();
        if (data.error) {
          status.className = 'status visible error';
          status.textContent = data.error;
        } else {
          lbEnrichData = data.results;
          const withEmail   = Object.values(lbEnrichData).filter(r => r.emails && r.emails.length).length;
          const withContact = Object.values(lbEnrichData).filter(r => r.emails?.length || r.phones?.length || Object.keys(r.profiles||{}).length).length;
          status.className = 'status visible success';
          status.innerHTML = `<span>✓ Enriched ${lbData.length} players · <b>${withContact}</b> with any contact · <b>${withEmail}</b> with email · ${data.elapsed}s</span>`;
          renderLbTable();
        }
      } catch (err) {
        status.className = 'status visible error';
        status.textContent = 'Enrichment failed: ' + err.message;
      } finally {
        btn.disabled = false;
        btn.innerHTML = _enrichIcon + ' Enrich Contacts';
      }
    }

    async function enrichIgContacts() {
      if (!currentData.length) return;
      const btn    = document.getElementById('igEnrichBtn');
      const status = document.getElementById('status');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Enriching...';
      status.className = 'status visible';
      status.innerHTML = `<span class="spinner"></span><span>Enriching via People Data Labs — ~${currentData.length * 0.2}s estimated...</span>`;

      try {
        const res  = await fetch('/api/enrich-contacts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            players: currentData.map(p => ({
              name: p.full_name || p.username,
              instagram_url: `https://www.instagram.com/${p.username}/`,
            })),
            profession_hint: '',
          })
        });
        const data = await res.json();
        if (data.error) {
          status.className = 'status visible error';
          status.textContent = data.error;
        } else {
          igEnrichData = data.results;
          const withEmail   = Object.values(igEnrichData).filter(r => r.emails && r.emails.length).length;
          const withContact = Object.values(igEnrichData).filter(r => r.emails?.length || r.phones?.length || Object.keys(r.profiles||{}).length).length;
          status.className = 'status visible success';
          status.innerHTML = `<span>✓ Enriched ${currentData.length} profiles · <b>${withContact}</b> with any contact · <b>${withEmail}</b> with email · ${data.elapsed}s</span>`;
          renderTable();
        }
      } catch (err) {
        status.className = 'status visible error';
        status.textContent = 'Enrichment failed: ' + err.message;
      } finally {
        btn.disabled = false;
        btn.innerHTML = _enrichIcon + ' Enrich Contacts';
      }
    }

  </script>
</body>
</html>
"""


def _parse_usernames(raw: str) -> list[str]:
    usernames = []
    for u in raw.split(","):
        u = u.strip().strip("@")
        parts = [p for p in u.split("/") if p]
        username = parts[-1] if parts else ""
        if username and username not in ("www.instagram.com", "instagram.com"):
            usernames.append(username)
    return usernames


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        return jsonify(error="APIFY_API_TOKEN not configured"), 500

    body = request.json or {}
    usernames = _parse_usernames(body.get("usernames", ""))
    if not usernames:
        return jsonify(error="No usernames provided"), 400

    limit = max(100, min(body.get("limit", 200), 90000))
    data_type = body.get("type", "Followers")
    if data_type not in ("Followers", "Followings"):
        data_type = "Followers"

    client = ApifyClient(token)
    run_input = {
        "Account": usernames,
        "resultsLimit": limit,
        "dataToScrape": data_type,
    }

    start = time.time()
    try:
        run = client.actor(FOLLOWERS_ACTOR).call(run_input=run_input)
    except Exception as e:
        return jsonify(error=str(e)), 500

    elapsed = round(time.time() - start, 1)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return jsonify(results=items, elapsed=elapsed, count=len(items))


@app.route("/api/profile-details", methods=["POST"])
def api_profile_details():
    """Second-pass scrape: bio, follower/post counts, etc. for given usernames."""
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        return jsonify(error="APIFY_API_TOKEN not configured"), 500

    body = request.json or {}
    usernames = [u.strip().lstrip("@") for u in (body.get("usernames") or []) if isinstance(u, str) and u.strip()]
    if not usernames:
        return jsonify(error="No usernames provided"), 400
    if len(usernames) > 1000:
        return jsonify(error="Max 1000 usernames per call"), 400

    client = ApifyClient(token)
    start = time.time()
    try:
        run = client.actor(PROFILE_ACTOR).call(run_input={"usernames": usernames})
    except Exception as e:
        return jsonify(error=str(e)), 500

    elapsed = round(time.time() - start, 1)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return jsonify(results=items, elapsed=elapsed, count=len(items))


@app.route("/api/scrape-leaderboard", methods=["POST"])
def api_scrape_leaderboard():
    # openai_key may be None — WSOP URLs don't need it; scraper raises ValueError for non-WSOP without it
    openai_key = os.getenv("OPENAI_API_KEY")

    body = request.json or {}
    url = body.get("url", "").strip()
    if not url or not url.startswith("http"):
        return jsonify(error="A valid URL is required"), 400

    max_players   = min(int(body.get("max_players", 50)), 200)
    months_active = int(body.get("months_active", 12))
    us_only       = bool(body.get("us_only", True))

    start = time.time()
    try:
        if "thehendonmob.com" in url:
            # Paginated, Cloudflare-protected. This is the bounded interactive
            # path — page count is capped here (use scraper.harvest for the full
            # multi-day run). A page number in the URL itself takes precedence.
            from scraper.hendon_mob import scrape_money_list
            num_pages = max(1, min(int(body.get("pages", 1)), MAX_UI_PAGES))
            start_page = int(body["start_page"]) if body.get("start_page") else None
            fetch_profiles = bool(body.get("fetch_profiles", False))
            players = scrape_money_list(
                url=url, start_page=start_page, num_pages=num_pages,
                fetch_profiles=fetch_profiles,
                country="United States" if us_only else None,
            )
            results = [{
                "rank": p.get("rank"),
                "name": p.get("name", ""),
                "country": p.get("country", ""),
                "metric": p.get("earnings", ""),
                "profile_url": p.get("profile_url"),
                "city_state": p.get("city_state", ""),
                "last_active_year": None,
                "profiles": p.get("profiles", {}),
            } for p in players]
        else:
            from scraper.hendon_mob import scrape_leaderboard
            results = scrape_leaderboard(
                url=url,
                us_only=us_only,
                months_active=months_active,
                max_players=max_players,
                openai_api_key=openai_key,
            )
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=str(e)), 500

    elapsed = round(time.time() - start, 1)
    return jsonify(results=results, elapsed=elapsed, count=len(results))


@app.route("/api/enrich-contacts", methods=["POST"])
def api_enrich_contacts():
    openai_key   = os.getenv("OPENAI_API_KEY")
    apify_key    = os.getenv("APIFY_API_TOKEN")
    twitter_key  = os.getenv("TWITTER_BEARER_TOKEN")

    if not openai_key and not apify_key:
        return jsonify(error="OPENAI_API_KEY (web-search) or APIFY_API_TOKEN (social scrape) is required"), 500

    body    = request.json or {}
    players = body.get("players") or []
    if not players:
        return jsonify(error="No players provided"), 400
    if len(players) > 200:
        return jsonify(error="Max 200 players per enrichment batch"), 400

    profession_hint = body.get("profession_hint", "")

    start = time.time()
    try:
        from enrichment.pipeline import enrich_batch
        results = enrich_batch(
            players,
            profession_hint=profession_hint,
            openai_api_key=openai_key,
            apify_token=apify_key,
            twitter_bearer=twitter_key,
        )
    except Exception as e:
        return jsonify(error=str(e)), 500

    elapsed = round(time.time() - start, 1)
    return jsonify(results=results, elapsed=elapsed, count=len(results))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3002, debug=True, use_reloader=False, threaded=True)
