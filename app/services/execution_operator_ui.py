from __future__ import annotations

from html import escape


def build_execution_operator_ui(*, symbol: str | None, universe: str, days: int) -> str:
    default_symbol = escape(symbol or "")
    default_universe = escape(universe)
    default_days = max(int(days), 1)
    template = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>실행 운영 화면</title>
  <style>
    :root {
      --bg: #091018;
      --panel: rgba(18, 25, 35, 0.88);
      --panel-2: rgba(24, 33, 44, 0.92);
      --border: #253244;
      --text: #e7edf5;
      --muted: #9fb0c3;
      --good: #1f9d55;
      --warn: #d98e04;
      --bad: #c33f38;
      --info: #2d7ff9;
      --accent: #e9d8a6;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      --sans: "Pretendard", "Noto Sans KR", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(45,127,249,0.18), transparent 32%),
        radial-gradient(circle at top right, rgba(217,142,4,0.15), transparent 28%),
        linear-gradient(180deg, #091018 0%, #101722 100%);
      color: var(--text);
      font-family: var(--sans);
    }
    header {
      padding: 20px 24px 12px;
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      background: rgba(9,16,24,0.94);
      backdrop-filter: blur(12px);
      z-index: 5;
    }
    h1 { margin: 0 0 6px; font-size: 22px; }
    .sub { color: var(--muted); font-size: 13px; line-height: 1.5; }
    .controls {
      display: grid;
      grid-template-columns: 160px 220px 120px 160px 1fr;
      gap: 10px;
      padding: 16px 24px;
      align-items: end;
      border-bottom: 1px solid var(--border);
    }
    label {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, button {
      width: 100%;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: rgba(18,25,35,0.94);
      color: var(--text);
    }
    button {
      cursor: pointer;
      background: linear-gradient(180deg, #223246 0%, #1a2635 100%);
      font-weight: 700;
    }
    html { scroll-behavior: smooth; }
    body { overflow-x: hidden; }
    main { padding: 18px 24px 36px; }
    .app-shell {
      display: grid;
      grid-template-columns: 190px minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }
    .nav-rail {
      position: sticky;
      top: 108px;
      display: grid;
      gap: 12px;
    }
    .nav-card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 14px;
      box-shadow: 0 6px 24px rgba(0,0,0,0.22);
    }
    .nav-title {
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 10px;
      font-weight: 700;
    }
    .nav-links {
      display: grid;
      gap: 8px;
    }
    .nav-link {
      width: 100%;
      text-align: left;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(8,12,17,0.55);
      color: var(--text);
      font-weight: 700;
      cursor: pointer;
    }
    .nav-link:hover {
      border-color: #35506f;
      background: rgba(19,28,40,0.88);
    }
    .nav-link.active {
      border-color: #4f79a7;
      background: linear-gradient(180deg, rgba(39,58,82,0.94) 0%, rgba(24,36,52,0.96) 100%);
      box-shadow: inset 0 0 0 1px rgba(140,184,255,0.12);
    }
    .content-column {
      min-width: 0;
      display: grid;
      gap: 16px;
    }
    .detail-section {
      scroll-margin-top: 118px;
    }
    .grid { display: grid; gap: 14px; }
    .cards {
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      margin-bottom: 14px;
    }
    .two {
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      margin-bottom: 14px;
    }
    .three {
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      margin-bottom: 14px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 16px;
      box-shadow: 0 6px 24px rgba(0,0,0,0.22);
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: 15px;
      letter-spacing: -0.01em;
    }
    .metric {
      font-size: 28px;
      font-weight: 800;
      margin: 4px 0 6px;
      letter-spacing: -0.03em;
    }
    .meta {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.55;
    }
    .strong-line {
      font-size: 15px;
      font-weight: 700;
      margin-bottom: 8px;
      color: var(--accent);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 700;
      margin-right: 6px;
      margin-bottom: 6px;
    }
    .good { background: rgba(31,157,85,0.14); color: #7be0a7; }
    .warn { background: rgba(217,142,4,0.14); color: #f1bc58; }
    .bad { background: rgba(195,63,56,0.14); color: #ff8880; }
    .info { background: rgba(45,127,249,0.14); color: #8cb8ff; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      min-width: 640px;
    }
    th, td {
      padding: 10px 8px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
    }
    th { color: var(--muted); font-weight: 600; }
    code, pre { font-family: var(--mono); }
    pre {
      background: rgba(8,12,17,0.72);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      overflow: auto;
      font-size: 12px;
    }
    .stack > * + * { margin-top: 10px; }
    .empty { color: var(--muted); font-size: 13px; }
    .status-line {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 12px;
    }
    .kv {
      display: grid;
      grid-template-columns: 110px 1fr;
      gap: 8px;
      font-size: 13px;
      line-height: 1.55;
      margin-bottom: 8px;
    }
    .kv .k { color: var(--muted); }
    .kv .v { color: var(--text); }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 10px;
    }
    .summary-box {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      background: rgba(10,16,24,0.55);
    }
    .summary-box .label {
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 6px;
    }
    .summary-box .value {
      font-size: 16px;
      font-weight: 700;
      line-height: 1.4;
    }
    .desk-strip {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }
    .hero-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 10px;
      margin: 12px 0;
    }
    .hero-stat {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      background: linear-gradient(180deg, rgba(15,23,33,0.92) 0%, rgba(10,16,24,0.72) 100%);
    }
    .hero-stat .label {
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .hero-stat .value {
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.03em;
      line-height: 1.1;
    }
    .hero-stat .subvalue {
      margin-top: 4px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.45;
    }
    .prob-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin: 12px 0;
    }
    .prob-box {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      background: rgba(8,12,17,0.66);
    }
    .prob-box .label {
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .prob-box .value {
      font-size: 22px;
      font-weight: 800;
      line-height: 1.1;
    }
    .hint-card {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      background: rgba(8,12,17,0.5);
      margin-top: 10px;
    }
    .hint-card .title {
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .hint-card .body {
      font-size: 13px;
      line-height: 1.55;
    }
    .hint-card .body a {
      color: #8cb8ff;
      text-decoration: none;
    }
    .hint-card .body a:hover {
      text-decoration: underline;
    }
    .price-line {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 10px;
      margin-bottom: 4px;
    }
    .price-chip {
      min-width: 96px;
      border-radius: 999px;
      padding: 7px 12px;
      border: 1px solid var(--border);
      background: rgba(8,12,17,0.55);
      font-size: 12px;
      color: var(--text);
    }
    .price-chip strong {
      display: block;
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 3px;
      font-weight: 600;
    }
    .list-stack {
      display: grid;
      gap: 10px;
    }
    .list-card {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      background: rgba(8,12,17,0.58);
    }
    .list-card .title {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 6px;
    }
    .list-card .desc {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    .list-card .meta-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    .section-note {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
      margin-top: -4px;
      margin-bottom: 4px;
    }
    .table-wrap {
      overflow-x: auto;
      border-radius: 12px;
      border: 1px solid rgba(37, 50, 68, 0.55);
    }
    .section-header {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: end;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }
    .section-header h2 {
      margin: 0;
    }
    .section-header .meta {
      max-width: 720px;
    }
    .raw-panels details {
      border: 1px solid var(--border);
      border-radius: 12px;
      background: rgba(12,18,26,0.74);
      padding: 10px 12px;
    }
    .raw-panels summary {
      cursor: pointer;
      font-weight: 700;
      color: var(--muted);
    }
    @media (max-width: 920px) {
      .app-shell {
        grid-template-columns: 1fr;
      }
      .nav-rail { position: static; }
      .nav-links {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .controls {
        grid-template-columns: 1fr 1fr;
      }
      .prob-grid {
        grid-template-columns: 1fr;
      }
      table {
        min-width: 560px;
      }
    }
    @media (max-width: 640px) {
      .controls {
        grid-template-columns: 1fr;
      }
      .nav-links {
        grid-template-columns: 1fr 1fr;
      }
      .hero-grid,
      .summary-grid,
      .cards,
      .two,
      .three {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>실행 운영 화면</h1>
    <div class="sub">
      차트나 미러 지표가 아니라 서버 런타임 상태를 읽는 운영 화면입니다.
      최종 승인 기준은 여전히 <code>POST /validation/report</code> 와 <code>POST /operations/checklist</code> 입니다.
    </div>
  </header>
  <section class="controls">
    <div>
      <label for="symbol">심볼</label>
      <input id="symbol" value="__DEFAULT_SYMBOL__" placeholder="BTCUSDC" />
    </div>
    <div>
      <label for="universe">유니버스</label>
      <input id="universe" value="__DEFAULT_UNIVERSE__" />
    </div>
    <div>
      <label for="days">리포트 기준 최근 일수</label>
      <input id="days" type="number" min="1" max="365" value="__DEFAULT_DAYS__" />
    </div>
    <div>
      <label for="autorefresh">30초 자동 새로고침</label>
      <input id="autorefresh" type="checkbox" />
    </div>
    <div>
      <button id="refresh">새로고침</button>
    </div>
  </section>
  <main>
    <div class="status-line">
      <div id="status">대기 중</div>
      <div id="updated"></div>
    </div>
    <section class="app-shell">
      <aside class="nav-rail">
        <section class="nav-card">
          <div class="nav-title">빠른 이동</div>
          <div class="nav-links">
            <button class="nav-link" data-target="home-section">홈</button>
            <button class="nav-link" data-target="candidates-section">후보</button>
            <button class="nav-link" data-target="funnel-section">퍼널</button>
            <button class="nav-link" data-target="approval-section">승인</button>
            <button class="nav-link" data-target="orders-section">주문/포지션</button>
            <button class="nav-link" data-target="reconcile-section">리컨실리</button>
            <button class="nav-link" data-target="intents-section">Intent</button>
            <button class="nav-link" data-target="locks-section">락/정책</button>
            <button class="nav-link" data-target="raw-section">원본</button>
          </div>
        </section>
        <section class="nav-card">
          <div class="nav-title">화면 읽는 법</div>
          <div class="meta">
            상단 operator surface는 Decision Summary 안의 Top Operator Action을 먼저 확인하고, 이어서 Top Opportunity / Top Blocker, Current Operating State 순서로 읽은 뒤 대표 플랜과 상세 운영 섹션으로 내려가면 됩니다.
          </div>
        </section>
        <section class="nav-card">
          <div class="nav-title">기간 필터 안내</div>
          <div class="meta">
            `최근 일수`는 알림/체결 품질 같은 최근 리포트 기준입니다. 열린 주문, 열린 포지션, 활성 락은 운영상 항상 표시됩니다.
          </div>
        </section>
      </aside>

      <div class="content-column">
        <section id="home-section" class="panel detail-section">
          <div class="section-header">
            <div>
              <h2>홈</h2>
              <div class="meta">Decision Summary 안의 Top Operator Action을 먼저 확인하고, 이어서 Top Opportunity / Top Blocker, Current Operating State 순서로 읽은 뒤 대표 플랜과 현재 진입 가이드를 봅니다.</div>
            </div>
          </div>
          <div id="decision-summary" class="stack"></div>
          <div id="approval-divergence-banner" class="stack"></div>
          <section class="grid two">
            <div class="panel">
              <h2>Top Opportunity</h2>
              <div id="top-opportunity" class="stack"></div>
            </div>
            <div class="panel">
              <h2>Top Blocker</h2>
              <div id="top-blocker" class="stack"></div>
            </div>
          </section>
          <div id="current-operating-state" class="stack"></div>
          <div id="strategy-ab-posture" class="stack"></div>
          <div id="promotion-operating-stack" class="stack"></div>
          <div id="promotion-case-inspector" class="stack"></div>
          <div id="validation-checklist-review-stack" class="stack"></div>
          <div id="validation-case-inspector" class="stack"></div>
          <div id="runtime-quality-inspector" class="stack"></div>
          <div id="signal-funnel-inspector" class="stack"></div>
          <div id="alpha-research-inspector" class="stack"></div>
          <div id="kill-condition-inspector" class="stack"></div>
          <div id="policy-lock-inspector" class="stack"></div>
          <div id="intent-exposure-inspector" class="stack"></div>
          <div id="mode-deployment-inspector" class="stack"></div>
          <div id="approval-alignment-inspector" class="stack"></div>
          <div id="data-freshness-source-inspector" class="stack"></div>
          <div id="portfolio-candidate-drilldown" class="stack"></div>
          <div id="portfolio-candidate-inspector" class="stack"></div>
          <div id="checklist-evidence-drilldown" class="stack"></div>
          <div id="report-navigation" class="stack"></div>
          <div id="overview" class="stack"></div>
          <section class="grid cards" id="cards"></section>
          <section class="grid three">
            <div class="panel">
              <h2>대표 플랜</h2>
              <div id="top-plan" class="stack"></div>
            </div>
            <div class="panel">
              <h2>대표 후보</h2>
              <div id="top-candidate" class="stack"></div>
            </div>
            <div class="panel">
              <h2>현재 진입 가이드</h2>
              <div id="entry-guide" class="stack"></div>
            </div>
          </section>
        </section>

        <section id="candidates-section" class="detail-section grid two">
          <div class="panel">
            <div class="section-header">
              <div>
                <h2>실행 후보 목록</h2>
                <div class="meta">지금 실행 가능한 후보를 우선순위 순서대로 봅니다.</div>
              </div>
            </div>
            <div id="candidate-list" class="list-stack"></div>
          </div>
          <div class="panel">
            <div class="section-header">
              <div>
                <h2>활성 플랜 목록</h2>
                <div class="meta">현재 심볼의 살아 있는 계획만 묶어 보여줍니다.</div>
              </div>
            </div>
            <div id="plan-list" class="list-stack"></div>
          </div>
        </section>

        <section id="funnel-section" class="detail-section panel">
          <div class="section-header">
            <div>
              <h2>신호 퍼널</h2>
              <div class="meta">후보가 어디서 줄어드는지, 그리고 어떤 family / regime / session에서 통과율이 높은지 runtime 기준으로 봅니다.</div>
            </div>
          </div>
          <div id="signal-funnel" class="stack"></div>
        </section>

        <section id="approval-section" class="detail-section grid two">
          <div class="panel">
            <div class="section-header">
              <div>
                <h2>승인 / 체크리스트</h2>
                <div class="meta">validation과 checklist 기준의 배포 판단을 함께 봅니다.</div>
              </div>
            </div>
            <div id="approval-summary" class="stack"></div>
          </div>
          <div class="panel">
            <div class="section-header">
              <div>
                <h2>포트폴리오 / 알림 / 체결 품질</h2>
                <div class="meta">런타임 운영 품질과 최근 알림, 포트폴리오 상태를 묶어서 봅니다.</div>
              </div>
            </div>
            <div id="runtime-summary" class="stack"></div>
          </div>
        </section>

        <section id="orders-section" class="detail-section panel">
          <div class="section-header">
            <div>
              <h2>열린 주문 / 포지션</h2>
              <div class="meta">활성 상태는 기간과 무관하게 항상 표시됩니다.</div>
            </div>
          </div>
          <div id="orders-positions" class="stack"></div>
        </section>

        <section id="reconcile-section" class="detail-section panel">
          <div class="section-header">
            <div>
              <h2>리컨실리에이션</h2>
              <div class="meta">최근 점검 이벤트는 `최근 일수` 기준이 아니라 최신 이벤트 순으로 표시됩니다.</div>
            </div>
          </div>
          <div id="reconcile" class="stack"></div>
        </section>

        <section id="intents-section" class="detail-section panel">
          <div class="section-header">
            <div>
              <h2>최근 Intent</h2>
              <div class="meta">최근 의사결정과 제출 직전 상태를 추적합니다.</div>
            </div>
          </div>
          <div id="intents"></div>
        </section>

        <section id="locks-section" class="detail-section panel">
          <div class="section-header">
            <div>
              <h2>락 / 롤아웃 정책</h2>
              <div class="meta">현재 시스템이 무엇을 막고 있는지와 family별 live 허용 범위를 봅니다.</div>
            </div>
          </div>
          <div id="locks" class="stack"></div>
        </section>

        <section id="raw-section" class="detail-section grid two raw-panels">
          <details>
            <summary>원본 Dashboard Payload</summary>
            <pre id="raw-dashboard">{}</pre>
          </details>
          <details>
            <summary>원본 Checklist Payload</summary>
            <pre id="raw-checklist">{}</pre>
          </details>
        </section>
      </div>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    let timer = null;

    function badgeClass(value) {
      const v = String(value || '').toUpperCase();
      if ((v.includes('GO') && !v.includes('NO_GO')) || v === 'ALLOWED' || v === 'READY') return 'good';
      if (v.includes('MANUAL') || v.includes('WARN') || v.includes('REVIEW') || v.includes('PAPER') || v.includes('SHADOW')) return 'warn';
      if (v.includes('NO_GO') || v.includes('BLOCK') || v.includes('FAIL') || v.includes('CRITICAL') || v.includes('NOT_READY')) return 'bad';
      return 'info';
    }

    function badge(label, value) {
      const v = value == null || value === '' ? 'n/a' : String(value);
      return `<span class="badge ${badgeClass(v)}">${label}: ${v}</span>`;
    }

    function esc(value) {
      return String(value == null ? '' : value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;');
    }

    function asJson(el, value) {
      $(el).textContent = JSON.stringify(value ?? {}, null, 2);
    }

    function fmtPrice(value) {
      if (value == null || Number.isNaN(Number(value))) return 'n/a';
      return Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 });
    }

    function fmtPercent(value) {
      if (value == null || Number.isNaN(Number(value))) return 'n/a';
      return `${(Number(value) * 100).toFixed(1)}%`;
    }

    function fmtR(value) {
      if (value == null || Number.isNaN(Number(value))) return 'n/a';
      const n = Number(value);
      return `${n >= 0 ? '+' : ''}${n.toFixed(2)}R`;
    }

    function fmtMaybe(value) {
      return value == null || value === '' ? 'n/a' : String(value);
    }

    function boolLabel(value) {
      return value ? '예' : '아니오';
    }

    function firstPlan(plans) {
      return Array.isArray(plans) && plans.length ? plans[0] : null;
    }

    function pickCandidate(scannerRows, symbol) {
      if (!Array.isArray(scannerRows) || scannerRows.length === 0) return null;
      return scannerRows.find((row) => row.symbol === symbol) || scannerRows[0];
    }

    function deriveTradeStatus(dashboard, candidate, plan) {
      if (dashboard?.new_entries_allowed === false) return '차단';
      if (candidate?.deployment_go_no_go === 'GO') return '지금 후보 있음';
      if (candidate?.deployment_go_no_go === 'MANUAL_REVIEW') return '수동 검토';
      if (plan) return '플랜 있음';
      return '후보 없음';
    }

    function deriveTradeReason(dashboard, candidate, plan) {
      if (candidate?.block_reason_message) return candidate.block_reason_message;
      if (dashboard?.blocking_reason_message) return dashboard.blocking_reason_message;
      if (candidate?.deployment_message) return candidate.deployment_message;
      if (plan?.expected_summary) return plan.expected_summary;
      return '이 심볼에 대해 지금 바로 실행 가능한 후보가 없습니다.';
    }

    function renderSummaryBox(label, value, extra = '') {
      return `
        <div class="summary-box">
          <div class="label">${esc(label)}</div>
          <div class="value">${esc(value)}</div>
          ${extra ? `<div class="meta">${esc(extra)}</div>` : ''}
        </div>
      `;
    }

    function deriveOperatorActionPriority(dashboard, checklist, validation) {
      const funnel = dashboard?.signal_funnel || {};
      const sharedPriority = funnel.operator_action_priority || {};
      if (sharedPriority && (sharedPriority.available !== false) && (sharedPriority.top_action || (sharedPriority.next_actions || []).length > 0)) {
        return {
          available: true,
          top_action: sharedPriority.top_action || 'continue_runtime_monitoring',
          top_reason: sharedPriority.top_reason || '',
          priority_level: sharedPriority.priority_level || 'monitor',
          supporting_signals: Array.isArray(sharedPriority.supporting_signals) ? sharedPriority.supporting_signals : [],
          blocking_signals: Array.isArray(sharedPriority.blocking_signals) ? sharedPriority.blocking_signals : [],
          next_actions: Array.isArray(sharedPriority.next_actions) ? sharedPriority.next_actions.slice(0, 3) : [],
          advisory_only: sharedPriority.advisory_only !== false,
        };
      }

      const degradation = funnel.execution_degradation_advisory || {};
      const familyExecution = funnel.family_execution_degradation_advisory || {};
      const modeAdvisory = funnel.mode_advisory || {};
      const researchAction = funnel.alpha_research_recommended_action || {};
      const softeningReview = funnel.alpha_research_softening_review || {};
      const promotionWatchlist = funnel.alpha_research_promotion_watchlist || {};

      const playbookAction = dashboard?.playbook_action
        || checklist?.playbook_action
        || validation?.playbook_action
        || '';
      const playbookReason = dashboard?.playbook_message
        || checklist?.playbook_message
        || validation?.playbook_message
        || validation?.deployment_message
        || '';

      const topFamilyExecution = familyExecution?.top_family || {};
      const modeFamilyTop = modeAdvisory?.family_top || {};
      const modeRegimeTop = modeAdvisory?.regime_top || {};
      const modeSessionTop = modeAdvisory?.session_top || {};
      const modeTop = [modeFamilyTop, modeRegimeTop, modeSessionTop].find((row) => row && row.bucket) || {};

      const nextActions = [];
      function pushAction(action, reason, priorityLevel, source) {
        if (!action) return;
        nextActions.push({
          action,
          reason: reason || '',
          priority_level: priorityLevel,
          source,
          advisory_only: true,
        });
      }

      if (playbookAction) {
        pushAction(playbookAction, playbookReason, 'urgent', 'playbook');
      }

      if (degradation?.status === 'manual_review') {
        pushAction(
          degradation?.recommended_action || 'review_execution_drag_before_expansion',
          degradation?.summary || 'global execution degradation requires manual review',
          'urgent',
          'execution_degradation'
        );
      } else if (degradation?.status === 'watch') {
        pushAction(
          degradation?.recommended_action || 'review_execution_drag_and_hold_size',
          degradation?.summary || 'global execution quality is drifting',
          'watch',
          'execution_degradation'
        );
      }

      if (topFamilyExecution?.family) {
        const familyAction = topFamilyExecution?.recommended_action
          || `review_family_${topFamilyExecution.family}_execution_drag`;
        const familyReason = topFamilyExecution?.summary
          || `family=${topFamilyExecution.family} status=${topFamilyExecution.status || 'n/a'}`;
        const familyPriority = topFamilyExecution?.status === 'manual_review'
          ? 'watch'
          : (topFamilyExecution?.status === 'watch' ? 'watch' : 'monitor');
        pushAction(familyAction, familyReason, familyPriority, 'family_execution_degradation');
      }

      if (modeTop?.advisory_state === 'research_only') {
        pushAction(
          'keep_bucket_in_research_only_review',
          modeTop?.why || `${modeTop.axis || 'bucket'}=${modeTop.bucket || 'unknown'} remains research-only`,
          'research',
          'mode_advisory'
        );
      } else if (modeTop?.advisory_state === 'promotion_watch') {
        pushAction(
          'keep_bucket_under_promotion_watch',
          modeTop?.why || `${modeTop.axis || 'bucket'}=${modeTop.bucket || 'unknown'} stays on promotion watch`,
          'watch',
          'mode_advisory'
        );
      } else if (modeTop?.advisory_state === 'watch') {
        pushAction(
          'watch_bucket_execution_and_outcome',
          modeTop?.why || `${modeTop.axis || 'bucket'}=${modeTop.bucket || 'unknown'} should be watched`,
          'watch',
          'mode_advisory'
        );
      }

      if (researchAction?.recommended_action) {
        pushAction(
          researchAction.recommended_action,
          researchAction?.recommended_reason || 'alpha-research next step',
          'research',
          'alpha_research'
        );
      } else if (softeningReview?.top_candidate?.bucket) {
        pushAction(
          'softening_review',
          `${softeningReview.top_candidate.axis || 'bucket'}=${softeningReview.top_candidate.bucket}`,
          'research',
          'alpha_research_softening'
        );
      } else if (promotionWatchlist?.top_watch?.bucket) {
        pushAction(
          'promotion_watch',
          `${promotionWatchlist.top_watch.focus || 'bucket'}=${promotionWatchlist.top_watch.bucket}`,
          'research',
          'alpha_research_promotion_watch'
        );
      }

      const priorityRank = { urgent: 3, watch: 2, research: 1, monitor: 0 };
      nextActions.sort((a, b) => {
        const rankDelta = (priorityRank[b.priority_level] || 0) - (priorityRank[a.priority_level] || 0);
        if (rankDelta !== 0) return rankDelta;
        return String(a.action || '').localeCompare(String(b.action || ''));
      });

      const top = nextActions[0];
      if (!top) {
        return {
          available: true,
          top_action: 'continue_runtime_monitoring',
          top_reason: 'no stronger operator action is currently implied by playbook, execution, family, mode, or research signals',
          priority_level: 'monitor',
          supporting_signals: [],
          blocking_signals: [],
          next_actions: [],
          advisory_only: true,
        };
      }

      const supportingSignals = [];
      const blockingSignals = [];
      if (playbookAction) supportingSignals.push(`playbook:${playbookAction}`);
      if (degradation?.status) supportingSignals.push(`execution:${degradation.status}`);
      if (topFamilyExecution?.family) supportingSignals.push(`family:${topFamilyExecution.family}:${topFamilyExecution.status || 'n/a'}`);
      if (modeTop?.bucket) supportingSignals.push(`mode:${modeTop.axis || 'bucket'}=${modeTop.bucket}:${modeTop.advisory_state || 'n/a'}`);
      if (researchAction?.recommended_action) supportingSignals.push(`research:${researchAction.recommended_action}`);
      if (dashboard?.new_entries_allowed === false) blockingSignals.push(`entry_gate:${dashboard?.blocking_reason_code || 'blocked'}`);
      if (topFamilyExecution?.status === 'manual_review') blockingSignals.push(`family_manual_review:${topFamilyExecution.family}`);
      if (modeTop?.advisory_state === 'research_only') blockingSignals.push(`research_only:${modeTop.axis || 'bucket'}=${modeTop.bucket || 'unknown'}`);

      return {
        available: true,
        top_action: top.action,
        top_reason: top.reason,
        priority_level: top.priority_level,
        supporting_signals: supportingSignals,
        blocking_signals: blockingSignals,
        next_actions: nextActions.slice(1, 4),
        advisory_only: true,
      };
    }

    function renderDecisionSummary(dashboard, checklist, validation) {
      const signalFunnel = dashboard?.signal_funnel || {};
      const degradation = signalFunnel.execution_degradation_advisory || {};
      const modeAdvisory = signalFunnel.mode_advisory || {};
      const familyTop = modeAdvisory.family_top || {};
      const operatorActionPriority = deriveOperatorActionPriority(dashboard, checklist, validation);
      const entriesAllowed = dashboard?.new_entries_allowed !== false;
      const entryState = entriesAllowed ? '가능' : '불가';
      const primaryReason = dashboard?.blocking_reason_message
        || checklist?.playbook_message
        || dashboard?.playbook_message
        || validation?.deployment_message
        || '현재 운영 판단 근거가 없습니다.';
      const operatingHint = dashboard?.playbook_action
        || checklist?.playbook_action
        || validation?.playbook_action
        || 'playbook action unavailable';
      const decisionBadges = [
        badge('신규 진입', entryState),
        badge('서버 승인', dashboard?.deployment_go_no_go || 'n/a'),
        badge('체크리스트', checklist?.deployment_go_no_go || 'n/a'),
        badge('검증', validation?.deployment_go_no_go || 'n/a'),
      ].join('');

      $('decision-summary').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Decision Summary</h2>
              <div class="meta">지금 신규 진입 가능 여부와 Decision Summary 안의 server-side Top Operator Action을 먼저 보여줍니다. policy mutation이 아니라 reading priority입니다.</div>
            </div>
          </div>
          <div class="desk-strip">${decisionBadges}</div>
          <div class="strong-line">${esc(entriesAllowed ? '현재 신규 진입은 열려 있습니다.' : '현재 신규 진입은 차단되어 있습니다.')}</div>
          <div class="meta">${esc(primaryReason)}</div>
          <div class="summary-grid" style="margin-top:12px;">
            ${renderSummaryBox('핵심 이유', entriesAllowed ? '진입 가능' : '진입 차단', dashboard?.blocking_reason_code || 'runtime safety / checklist / validation 기준')}
            ${renderSummaryBox('Top Operator Action', operatorActionPriority?.top_action || 'continue_runtime_monitoring', operatorActionPriority?.top_reason || 'server-side operator action priority unavailable; advisory only')}
            ${renderSummaryBox('현재 운영 해석', operatingHint, dashboard?.playbook_message || checklist?.playbook_message || '')}
            ${renderSummaryBox('Execution 상태', degradation?.status || 'n/a', degradation?.summary || 'execution advisory unavailable')}
            ${renderSummaryBox('대표 Mode Advisory', familyTop?.advisory_state || 'n/a', familyTop?.bucket ? `family=${familyTop.bucket}` : (modeAdvisory?.coverage_note || 'mode advisory unavailable'))}
          </div>
        </div>
      `;
    }

    function renderApprovalDivergenceBanner(dashboard, checklist, validation, candidate) {
      const deploymentStatuses = [
        dashboard?.deployment_go_no_go,
        checklist?.deployment_go_no_go,
        validation?.deployment_go_no_go,
        candidate?.deployment_go_no_go || candidate?.operator_status,
      ].filter((value) => value);
      const playbookActions = [
        dashboard?.playbook_action,
        checklist?.playbook_action,
        validation?.playbook_action,
      ].filter((value) => value);
      const deploymentAligned = new Set(deploymentStatuses).size <= 1;
      const playbookAligned = new Set(playbookActions).size <= 1;
      const state = deploymentAligned && playbookAligned ? 'aligned' : 'diverged';
      const message = state === 'aligned'
        ? 'dashboard / checklist / validation / candidate surface가 같은 방향을 가리키고 있습니다.'
        : 'dashboard / checklist / validation / candidate surface가 서로 다른 방향을 가리키고 있습니다.';
      const detail = [
        `dashboard=${dashboard?.deployment_go_no_go || 'n/a'}`,
        `checklist=${checklist?.deployment_go_no_go || 'n/a'}`,
        `validation=${validation?.deployment_go_no_go || 'n/a'}`,
        `candidate=${candidate?.deployment_go_no_go || candidate?.operator_status || 'n/a'}`,
      ].join(' | ');
      const nextMove = dashboard?.playbook_action
        || validation?.playbook_action
        || checklist?.playbook_action
        || 'approval divergence next move unavailable';

      $('approval-divergence-banner').innerHTML = `
        <div class="panel">
          <div class="desk-strip">
            ${badge('Approval Divergence', state)}
            ${badge('Dashboard', dashboard?.deployment_go_no_go || 'n/a')}
            ${badge('Checklist', checklist?.deployment_go_no_go || 'n/a')}
            ${badge('Validation', validation?.deployment_go_no_go || 'n/a')}
          </div>
          <div class="strong-line">${esc(message)}</div>
          <div class="meta">${esc(detail)}</div>
          <div class="meta">${esc(`next_move=${nextMove}`)}</div>
        </div>
      `;
    }

    function renderTopOpportunity(candidate, symbol) {
      if (!candidate) {
        $('top-opportunity').innerHTML = `<div class="empty">${esc(symbol)} 기준으로 바로 볼 accepted 후보가 없습니다.</div>`;
        return;
      }
      const candidateCluster = candidate?.strategy_cluster || candidate?.multi_strategy_overlay?.cluster || 'n/a';
      const candidateClusterStatus = candidate?.strategy_cluster_status
        || candidate?.multi_strategy_overlay?.strategy_cluster_status
        || 'n/a';
      const candidateABSummary = candidate?.strategy_cluster_balance?.summary
        || candidate?.b_continuation_activation?.summary
        || candidate?.multi_strategy_overlay?.summary
        || '현재 row-level A/B posture summary가 없습니다.';
      const source = candidate.symbol === symbol
        ? '현재 심볼 기준 상위 후보'
        : `현재 심볼 후보 없음, 전체 상위 후보=${candidate.symbol}`;
      $('top-opportunity').innerHTML = `
        <div>${badge('심볼', candidate.symbol)} ${badge('상태', candidate.deployment_go_no_go || candidate.operator_status || 'n/a')} ${badge('Family', candidate.strategy_family || 'n/a')} ${badge('Cluster', candidateCluster)}</div>
        <div class="kv"><div class="k">방향 / 모델</div><div class="v">${esc(`${fmtMaybe(candidate.direction)} / ${fmtMaybe(candidate.entry_model)}`)}</div></div>
        <div class="kv"><div class="k">추정 승률 / EV</div><div class="v">${esc(`${fmtPercent(candidate.expected_win_prob)} / ${fmtR(candidate.expected_ev_r)}`)}</div></div>
        <div class="kv"><div class="k">권장 리스크</div><div class="v">${esc(fmtR(candidate.recommended_risk_r))}</div></div>
        <div class="kv"><div class="k">A/B posture</div><div class="v">${esc(`${candidateClusterStatus} / ${candidateABSummary}`)}</div></div>
        <div class="kv"><div class="k">왜 지금</div><div class="v">${esc(fmtMaybe(candidate.why_now || candidate.expected_summary))}</div></div>
        <div class="meta">${esc(source)}</div>
      `;
    }

    function renderTopBlocker(dashboard) {
      const funnel = dashboard?.signal_funnel || {};
      const hard = funnel.hard_block_summary || {};
      const soft = funnel.softening_candidate_summary || {};
      const rollout = funnel.rollout_block_summary || {};
      let title = '현재 대표 차단 축이 없습니다.';
      let desc = '신규 진입을 막는 runtime gate summary가 없습니다.';
      let badgeValue = 'n/a';

      if ((dashboard?.current_entry_gate_group || '') === 'safety' || (hard?.blocked ?? 0) > 0) {
        title = hard?.top_reason || dashboard?.blocking_reason_code || 'safety';
        desc = dashboard?.blocking_reason_message || '현재 hard gate가 신규 진입을 막고 있습니다.';
        badgeValue = 'hard gate';
      } else if ((soft?.blocked ?? 0) > 0) {
        title = soft?.top_reason || 'quality';
        desc = '현재 quality near-miss가 research-only softening 검토 대상으로 남아 있습니다.';
        badgeValue = 'research-only';
      } else if ((rollout?.blocked ?? 0) > 0) {
        title = rollout?.top_reason || 'rollout';
        desc = '현재 운영 정책 제한 때문에 후보가 막히고 있습니다.';
        badgeValue = 'rollout';
      }

      $('top-blocker').innerHTML = `
        <div>${badge('대표 차단', badgeValue)} ${badge('게이트', dashboard?.signal_funnel?.current_entry_gate_group || 'n/a')}</div>
        <div class="strong-line">${esc(title)}</div>
        <div class="meta">${esc(desc)}</div>
        <div class="summary-grid" style="margin-top:12px;">
          ${renderSummaryBox('Hard gate 차단 수', String(hard?.blocked ?? 0), hard?.top_reason || '없음')}
          ${renderSummaryBox('Softening 후보 수', String(soft?.blocked ?? 0), soft?.top_reason ? `${soft.top_reason} / research-only` : '없음')}
          ${renderSummaryBox('Rollout 차단 수', String(rollout?.blocked ?? 0), rollout?.top_reason || '없음')}
        </div>
      `;
    }

    function renderCurrentOperatingState(dashboard, checklist, validation) {
      const funnel = dashboard?.signal_funnel || {};
      const portfolio = dashboard?.portfolio_summary || {};
      const degradation = funnel.execution_degradation_advisory || {};
      const familyExecutionAdvisory = funnel.family_execution_degradation_advisory || {};
      const modeAdvisory = funnel.mode_advisory || {};
      const researchAction = funnel.alpha_research_recommended_action || {};
      const softeningReview = funnel.alpha_research_softening_review || {};
      const promotionWatchlist = funnel.alpha_research_promotion_watchlist || {};
      const operatorActionPriority = deriveOperatorActionPriority(dashboard, checklist, validation);

      const playbookHint = dashboard?.playbook_action
        || checklist?.playbook_action
        || validation?.playbook_action
        || 'playbook action unavailable';
      const playbookReason = dashboard?.playbook_message
        || checklist?.playbook_message
        || validation?.playbook_message
        || validation?.deployment_message
        || '현재 운영 액션 요약이 없습니다.';

      const headroomByRegime = portfolio?.headroom_by_regime || {};
      const topHeadroom = Object.entries(headroomByRegime)
        .sort((a, b) => Number(a[1] || 0) - Number(b[1] || 0))[0];
      const headroomValue = topHeadroom
        ? `${topHeadroom[0]}=${fmtMaybe(topHeadroom[1])}`
        : `${portfolio.accepted_candidate_count ?? 0} accepted / ${portfolio.blocked_candidate_count ?? 0} blocked`;
      const headroomReason = portfolio?.playbook_action
        || portfolio?.risk_reason
        || 'portfolio headroom detail unavailable';

      const familyTop = modeAdvisory?.family_top || {};
      const regimeTop = modeAdvisory?.regime_top || {};
      const sessionTop = modeAdvisory?.session_top || {};
      const modeTop = [familyTop, regimeTop, sessionTop].find((row) => row && row.bucket) || familyTop;
      const modeValue = modeTop?.advisory_state || 'n/a';
      const modeReason = modeTop?.bucket
        ? `${modeTop.axis || 'bucket'}=${modeTop.bucket}`
        : (modeAdvisory?.coverage_note || 'mode advisory unavailable');

      const familyTopExecution = familyExecutionAdvisory?.top_family || {};
      const familyExecutionValue = familyTopExecution?.family
        ? `${familyTopExecution.family} / ${familyTopExecution.status || 'n/a'}`
        : 'n/a';
      const familyExecutionReason = familyTopExecution?.family
        ? `post_cost_alignment=${familyTopExecution.post_cost_alignment || 'n/a'}`
        : (familyExecutionAdvisory?.coverage_note || 'family execution advisory unavailable');
      const familyCoverageValue = String(familyExecutionAdvisory?.family_count ?? 0);
      const familyCoverageReason = familyExecutionAdvisory?.coverage_note || 'family execution advisory unavailable';

      let researchNextStep = researchAction?.recommended_action || 'research action unavailable';
      let researchReason = researchAction?.recommended_reason || '';
      if (!researchAction?.recommended_action && softeningReview?.top_candidate?.bucket) {
        researchNextStep = 'softening_review';
        researchReason = `${softeningReview.top_candidate.axis || 'bucket'}=${softeningReview.top_candidate.bucket}`;
      } else if (!researchAction?.recommended_action && promotionWatchlist?.top_watch?.bucket) {
        researchNextStep = 'promotion_watch';
        researchReason = `${promotionWatchlist.top_watch.focus || 'bucket'}=${promotionWatchlist.top_watch.bucket}`;
      }
      const nextActions = Array.isArray(operatorActionPriority?.next_actions) ? operatorActionPriority.next_actions : [];
      const nextActionText = nextActions.length
        ? nextActions.map((item) => `${item.action} [${item.priority_level}]`).join(' | ')
        : '추가 operator action priority가 없습니다.';
      const nextActionReason = nextActions.length
        ? nextActions.map((item) => item.reason).filter(Boolean).join(' | ')
        : '현재 top operator action만 확인하면 됩니다.';

      $('current-operating-state').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Current Operating State</h2>
              <div class="meta">Top Operator Action과 Top Opportunity / Top Blocker 다음 순서에서, 포트폴리오, execution, family advisory, mode, research 기준의 server-side 현재 운영 해석과 next actions를 요약합니다.</div>
            </div>
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Playbook / Deployment Hint', playbookHint, playbookReason)}
            ${renderSummaryBox('Portfolio Headroom', headroomValue, headroomReason)}
            ${renderSummaryBox('Execution Degradation', degradation?.status || 'n/a', degradation?.summary || degradation?.recommended_action || 'execution advisory unavailable')}
            ${renderSummaryBox('Family Execution Advisory', familyExecutionValue, familyExecutionReason)}
            ${renderSummaryBox('Family Advisory Coverage', familyCoverageValue, familyCoverageReason)}
            ${renderSummaryBox('Mode Advisory', modeValue, modeReason)}
            ${renderSummaryBox('Alpha-Research Next Step', researchNextStep, researchReason || 'research-only next step')}
            ${renderSummaryBox('Next Actions', nextActionText, nextActionReason || 'server-side operator reading priority only; not a live submit instruction')}
          </div>
        </div>
      `;
    }

    function renderStrategyABPosture(dashboard, candidate) {
      const funnel = dashboard?.signal_funnel || {};
      const portfolio = dashboard?.portfolio_summary || {};
      const multiStrategy = funnel.multi_strategy_ab_expansion || portfolio?.multi_strategy_ab_summary || {};
      const bActivation = funnel.b_continuation_activation || {};
      const clusterBalance = funnel.strategy_cluster_balance || portfolio?.strategy_cluster_balance_summary || {};
      const candidateOverlay = candidate?.multi_strategy_overlay || {};
      const candidateBActivation = candidate?.b_continuation_activation || {};
      const candidateBalance = candidate?.strategy_cluster_balance || {};
      const aCluster = multiStrategy?.a_cluster || {};
      const bCluster = multiStrategy?.b_cluster || {};
      const familyMix = Array.isArray(clusterBalance?.family_mix) && clusterBalance.family_mix.length
        ? clusterBalance.family_mix
        : (Array.isArray(multiStrategy?.family_mix) ? multiStrategy.family_mix : []);
      const candidateCluster = candidate?.strategy_cluster || candidateOverlay?.cluster || 'n/a';
      const candidateClusterStatus = candidate?.strategy_cluster_status
        || candidateOverlay?.strategy_cluster_status
        || 'n/a';
      const candidatePostureState = candidateBalance?.balance_state
        || candidateBActivation?.activation_state
        || candidateClusterStatus;
      const candidatePostureSummary = candidateBalance?.summary
        || candidateBActivation?.summary
        || candidateOverlay?.summary
        || candidate?.expected_summary
        || '현재 대표 후보의 A/B posture detail이 없습니다.';

      $('strategy-ab-posture').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>A/B Strategy Posture</h2>
              <div class="meta">A remains anchor인지, B continuation이 research-only인지 guarded activation인지, 현재 mix가 여전히 A 집중인지까지 한 번에 읽습니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Mode', multiStrategy?.mode || clusterBalance?.mode || 'n/a')}
            ${badge('A Anchor', multiStrategy?.raw_family_anchor || 'n/a')}
            ${badge('B 상태', bActivation?.activation_state || 'n/a')}
            ${badge('Mix', clusterBalance?.balance_state || 'n/a')}
            ${badge('대표 후보 Cluster', candidateCluster)}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('A Cluster', aCluster?.cluster || 'n/a', aCluster?.strategy_cluster_status || 'A cluster summary unavailable')}
            ${renderSummaryBox('B Cluster', bCluster?.cluster || 'n/a', bCluster?.strategy_cluster_status || 'B cluster summary unavailable')}
            ${renderSummaryBox('B Activation', bActivation?.activation_state || 'n/a', bActivation?.summary || 'B continuation activation summary unavailable')}
            ${renderSummaryBox('Cluster Balance', clusterBalance?.balance_state || 'n/a', clusterBalance?.summary || 'strategy cluster balance summary unavailable')}
            ${renderSummaryBox('Target Mix', clusterBalance?.target_mix || 'n/a', clusterBalance?.balance_bias || 'balance bias unavailable')}
            ${renderSummaryBox('대표 후보 A/B 해석', candidatePostureState || 'n/a', candidatePostureSummary)}
          </div>
          <div class="hint-card">
            <div class="title">현재 A/B mix</div>
            <div class="body">${esc(clusterBalance?.summary || multiStrategy?.summary || '현재 A/B runtime mix summary가 없습니다.')}</div>
          </div>
          ${renderTable(
            familyMix,
            [
              { label: 'Cluster', key: 'cluster' },
              { label: 'Raw Family', key: 'raw_family' },
              { label: '전체 후보', render: (row) => String(row.total_candidates ?? 0) },
              { label: 'Accepted', render: (row) => String(row.accepted_candidates ?? 0) },
              { label: 'Blocked', render: (row) => String(row.blocked_candidates ?? 0) },
              { label: 'Alpha Research', render: (row) => String(row.alpha_research_candidates ?? 0) },
            ],
            '현재 family mix 집계가 없습니다.'
          )}
        </div>
      `;
    }

    function renderPromotionOperatingStack(dashboard) {
      const funnel = dashboard?.signal_funnel || {};
      const governance = funnel.promotion_governance || {};
      const reviewQueue = funnel.promotion_review_queue || {};
      const remediationQueue = funnel.promotion_remediation_queue || {};
      const clearance = funnel.promotion_clearance_tracker || {};
      const reopenQueue = funnel.promotion_reopen_queue || {};
      const decisionBrief = funnel.promotion_decision_brief || {};
      const autoExecution = funnel.auto_promotion_rollout_execution || {};
      const history = funnel.promotion_lifecycle_history || {};
      const researchLoop = funnel.research_promotion_operating_loop || {};
      const family = governance?.family
        || clearance?.family
        || decisionBrief?.family
        || researchLoop?.family
        || reviewQueue?.headline_family
        || reopenQueue?.headline_family
        || 'n/a';
      const remainingDomains = Array.isArray(clearance?.remaining_guardrail_domains)
        ? clearance.remaining_guardrail_domains
        : [];
      const clearedDomains = Array.isArray(clearance?.cleared_guardrail_domains)
        ? clearance.cleared_guardrail_domains
        : [];
      const recentTransitions = Array.isArray(history?.recent_transitions)
        ? history.recent_transitions
        : [];

      $('promotion-operating-stack').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Promotion Operating Stack</h2>
              <div class="meta">승격 review, remediation, clearance, reopen, semi-auto execution, history, research followthrough를 한 번에 읽습니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Family', family)}
            ${badge('Governance', governance?.state || 'n/a')}
            ${badge('Review Queue', reviewQueue?.top_review_action || 'n/a')}
            ${badge('Remediation', remediationQueue?.top_remediation_action || 'n/a')}
            ${badge('Clearance', clearance?.clearance_state || 'n/a')}
            ${badge('Auto Exec', autoExecution?.execution_stage || 'n/a')}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Promotion Governance', governance?.state || 'n/a', governance?.summary || governance?.promotion_bias || 'promotion governance unavailable')}
            ${renderSummaryBox('Promotion Review Queue', reviewQueue?.queue_state || 'n/a', reviewQueue?.top_review_action || 'review queue unavailable')}
            ${renderSummaryBox('Promotion Remediation Queue', remediationQueue?.queue_state || 'n/a', remediationQueue?.top_remediation_action || 'remediation queue unavailable')}
            ${renderSummaryBox('Promotion Clearance Tracker', clearance?.clearance_state || 'n/a', clearance?.clearance_bias || clearance?.summary || 'clearance tracker unavailable')}
            ${renderSummaryBox('Promotion Reopen Queue', reopenQueue?.queue_state || 'n/a', reopenQueue?.top_reopen_action || 'reopen queue unavailable')}
            ${renderSummaryBox('Promotion Decision Brief', decisionBrief?.brief_state || 'n/a', decisionBrief?.decision_bias || decisionBrief?.summary || 'decision brief unavailable')}
            ${renderSummaryBox('Auto Promotion Execution', autoExecution?.execution_stage || 'n/a', autoExecution?.execution_bias || autoExecution?.summary || 'auto execution summary unavailable')}
            ${renderSummaryBox('Research Promotion Loop', researchLoop?.loop_state || 'n/a', researchLoop?.recommended_action || researchLoop?.summary || 'research loop unavailable')}
            ${renderSummaryBox('Promotion Lifecycle History', history?.history_state || 'n/a', history?.latest_event_type || history?.summary || 'lifecycle history unavailable')}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">남은 Guardrail Domain</div>
              <div class="body">${esc(remainingDomains.length ? remainingDomains.join(', ') : '현재 남은 guardrail domain이 없습니다.')}</div>
            </div>
            <div class="hint-card">
              <div class="title">최근 Promotion Transition</div>
              <div class="body">${esc(recentTransitions.length ? recentTransitions.slice(0, 3).join(' | ') : '최근 promotion lifecycle transition 기록이 없습니다.')}</div>
            </div>
          </div>
          <div class="hint-card">
            <div class="title">Cleared Domain</div>
            <div class="body">${esc(clearedDomains.length ? clearedDomains.join(', ') : '아직 cleared guardrail domain이 없습니다.')}</div>
          </div>
        </div>
      `;
    }

    function renderPromotionCaseInspector(dashboard) {
      const funnel = dashboard?.signal_funnel || {};
      const governance = funnel.promotion_governance || {};
      const reviewQueue = funnel.promotion_review_queue || {};
      const remediationQueue = funnel.promotion_remediation_queue || {};
      const clearance = funnel.promotion_clearance_tracker || {};
      const reopenQueue = funnel.promotion_reopen_queue || {};
      const decisionBrief = funnel.promotion_decision_brief || {};
      const autoExecution = funnel.auto_promotion_rollout_execution || {};
      const history = funnel.promotion_lifecycle_history || {};
      const researchLoop = funnel.research_promotion_operating_loop || {};
      const family = decisionBrief?.family
        || governance?.family
        || clearance?.family
        || autoExecution?.target_family
        || researchLoop?.family
        || reviewQueue?.headline_family
        || 'n/a';
      const remainingDomains = Array.isArray(clearance?.remaining_guardrail_domains)
        ? clearance.remaining_guardrail_domains
        : [];
      const clearedDomains = Array.isArray(clearance?.cleared_guardrail_domains)
        ? clearance.cleared_guardrail_domains
        : [];
      const recentTransitions = Array.isArray(history?.recent_transitions)
        ? history.recent_transitions
        : [];
      const nextMove = autoExecution?.summary
        || decisionBrief?.summary
        || researchLoop?.summary
        || governance?.summary
        || 'current promotion case summary unavailable';

      $('promotion-case-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Promotion Case Inspector</h2>
              <div class="meta">현재 headline family의 승격 case를 single-family inspector로 다시 압축해, target posture, write scope, remaining guardrails, next move를 바로 읽습니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Family', family)}
            ${badge('Target Posture', decisionBrief?.target_posture || autoExecution?.target_posture || governance?.target_posture || 'n/a')}
            ${badge('Brief', decisionBrief?.brief_state || 'n/a')}
            ${badge('Execution Stage', autoExecution?.execution_stage || 'n/a')}
            ${badge('Write Scope', autoExecution?.write_scope || 'n/a')}
            ${badge('History', history?.history_state || 'n/a')}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Promotion Governance', governance?.state || 'n/a', governance?.promotion_bias || governance?.summary || 'promotion governance unavailable')}
            ${renderSummaryBox('Decision Brief', decisionBrief?.brief_state || 'n/a', decisionBrief?.decision_bias || decisionBrief?.summary || 'decision brief unavailable')}
            ${renderSummaryBox('Review / Reopen', reviewQueue?.top_review_action || 'n/a', reopenQueue?.top_reopen_action || 'reopen queue unavailable')}
            ${renderSummaryBox('Remediation / Clearance', remediationQueue?.top_remediation_action || 'n/a', clearance?.clearance_state || clearance?.clearance_bias || 'clearance unavailable')}
            ${renderSummaryBox('Auto Execution', autoExecution?.execution_stage || 'n/a', autoExecution?.execution_bias || autoExecution?.action_domain || 'auto execution unavailable')}
            ${renderSummaryBox('Research Loop', researchLoop?.loop_state || 'n/a', researchLoop?.recommended_action || researchLoop?.target_stage || 'research loop unavailable')}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Next Move</div>
              <div class="body">${esc(nextMove)}</div>
            </div>
            <div class="hint-card">
              <div class="title">Recent Transition</div>
              <div class="body">${esc(recentTransitions.length ? recentTransitions.slice(0, 3).join(' | ') : '최근 transition 기록이 없습니다.')}</div>
            </div>
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Remaining Guardrails</div>
              <div class="body">${esc(remainingDomains.length ? remainingDomains.join(', ') : '현재 남은 guardrail domain이 없습니다.')}</div>
            </div>
            <div class="hint-card">
              <div class="title">Cleared Guardrails</div>
              <div class="body">${esc(clearedDomains.length ? clearedDomains.join(', ') : '아직 cleared guardrail domain이 없습니다.')}</div>
            </div>
          </div>
        </div>
      `;
    }

    function checklistStatusMap(checklist) {
      const rows = Array.isArray(checklist?.checks) ? checklist.checks : [];
      const out = {};
      rows.forEach((row) => {
        const itemId = String(row?.item_id || '').trim();
        if (!itemId) return;
        out[itemId] = row;
      });
      return out;
    }

    function nestedValue(payload, path) {
      if (!payload || !path) return '';
      const parts = String(path).split('.');
      let current = payload;
      for (const part of parts) {
        if (current == null) return '';
        current = current[part];
      }
      return current == null ? '' : current;
    }

    function renderValidationChecklistReviewStack(validation, checklist) {
      const checklistMap = checklistStatusMap(checklist);
      const rows = [
        ['outcome_control_trace', 'Outcome Control', validation?.outcome_control_trace_summary || {}, 'approval_penalty_status', 'portfolio_bias_tier'],
        ['rollout_recommendation', 'Rollout Recommendation', validation?.rollout_recommendation_summary || {}, 'recommendation', 'confidence'],
        ['multi_strategy_ab_expansion', 'Multi Strategy AB', validation?.multi_strategy_ab_summary || {}, 'mode', 'b_cluster.strategy_cluster_status'],
        ['b_continuation_activation', 'B Continuation Activation', validation?.b_continuation_activation_summary || {}, 'activation_state', 'activation_bias'],
        ['strategy_cluster_balance', 'Strategy Cluster Balance', validation?.strategy_cluster_balance_summary || {}, 'balance_state', 'balance_bias'],
        ['promotion_governance', 'Promotion Governance', validation?.promotion_governance_summary || {}, 'state', 'promotion_bias'],
        ['promotion_review_queue', 'Promotion Review Queue', validation?.promotion_review_queue_summary || {}, 'queue_state', 'top_review_action'],
        ['promotion_remediation_queue', 'Promotion Remediation Queue', validation?.promotion_remediation_queue_summary || {}, 'queue_state', 'top_remediation_action'],
        ['promotion_clearance_tracker', 'Promotion Clearance Tracker', validation?.promotion_clearance_tracker_summary || {}, 'clearance_state', 'clearance_bias'],
        ['promotion_reopen_queue', 'Promotion Reopen Queue', validation?.promotion_reopen_queue_summary || {}, 'queue_state', 'top_reopen_action'],
        ['promotion_decision_brief', 'Promotion Decision Brief', validation?.promotion_decision_brief_summary || {}, 'brief_state', 'decision_bias'],
        ['auto_promotion_rollout_execution', 'Auto Promotion Execution', validation?.auto_promotion_rollout_execution_summary || {}, 'execution_stage', 'execution_bias'],
        ['promotion_lifecycle_history', 'Promotion Lifecycle History', validation?.promotion_lifecycle_history_summary || {}, 'history_state', 'latest_event_type'],
        ['research_promotion_operating_loop', 'Research Promotion Loop', validation?.research_promotion_operating_loop_summary || {}, 'loop_state', 'target_stage'],
        ['positive_evidence_expansion', 'Positive Evidence Expansion', validation?.positive_evidence_expansion_summary || {}, 'state', 'expansion_bias'],
        ['outcome_bucket_granularity', 'Outcome Bucket Granularity', validation?.outcome_bucket_granularity_summary || {}, 'top_condition_axis', 'top_condition_bucket.key'],
        ['opportunity_capture', 'Opportunity Capture', validation?.opportunity_capture_summary || {}, 'dominant_bottleneck.reason', 'family_focus.key'],
        ['capital_allocator', 'Capital Allocator', validation?.capital_allocator_summary || {}, 'allocator_state', 'capital_pressure'],
      ].map(([itemId, label, payload, primaryPath, secondaryPath]) => {
        const checklistItem = checklistMap[itemId] || {};
        return {
          label,
          checklist_status: checklistItem?.status || 'n/a',
          validation_state: nestedValue(payload, primaryPath) || 'n/a',
          secondary: nestedValue(payload, secondaryPath) || 'n/a',
          summary: payload?.summary || checklistItem?.summary || 'summary unavailable',
        };
      });

      $('validation-checklist-review-stack').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Validation / Checklist Review Stack</h2>
              <div class="meta">validation top-level summary와 checklist item status를 같은 표로 압축해서, raw JSON 없이 operator review stack을 읽습니다.</div>
            </div>
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Validation GO/NO_GO', validation?.deployment_go_no_go || 'n/a', validation?.deployment_message || 'validation deployment language unavailable')}
            ${renderSummaryBox('Checklist GO/NO_GO', checklist?.deployment_go_no_go || 'n/a', checklist?.deployment_message || 'checklist deployment language unavailable')}
            ${renderSummaryBox('Validation Playbook', validation?.playbook_action || 'n/a', validation?.playbook_message || 'validation playbook unavailable')}
            ${renderSummaryBox('Checklist Playbook', checklist?.playbook_action || 'n/a', checklist?.playbook_message || 'checklist playbook unavailable')}
          </div>
          ${renderTable(
            rows,
            [
              { label: 'Review Layer', key: 'label' },
              { label: 'Checklist', key: 'checklist_status' },
              { label: 'Validation State', key: 'validation_state' },
              { label: 'Secondary', key: 'secondary' },
              { label: 'Summary', key: 'summary' },
            ],
            '현재 validation/checklist review stack이 없습니다.'
          )}
        </div>
      `;
    }

    function renderValidationCaseInspector(validation) {
      const outcomeControl = validation?.outcome_control_trace_summary || {};
      const rollout = validation?.rollout_recommendation_summary || {};
      const lifecycle = validation?.strategy_lifecycle_summary || {};
      const multiStrategy = validation?.multi_strategy_ab_summary || {};
      const bActivation = validation?.b_continuation_activation_summary || {};
      const clusterBalance = validation?.strategy_cluster_balance_summary || {};
      const expansion = validation?.positive_evidence_expansion_summary || {};
      const bucket = validation?.outcome_bucket_granularity_summary || {};
      const capture = validation?.opportunity_capture_summary || {};
      const allocator = validation?.capital_allocator_summary || {};
      const family = lifecycle?.family
        || rollout?.family
        || expansion?.family
        || allocator?.family_focus
        || bucket?.family_focus?.key
        || capture?.family_focus?.key
        || 'n/a';
      const topCondition = `${bucket?.top_condition_axis || 'n/a'} / ${bucket?.top_condition_bucket?.key || 'n/a'}`;
      const captureBottleneck = capture?.dominant_bottleneck?.reason || 'n/a';
      const nextMove = validation?.playbook_message
        || rollout?.summary
        || capture?.summary
        || allocator?.summary
        || outcomeControl?.summary
        || 'current validation case summary unavailable';

      $('validation-case-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Validation Case Inspector</h2>
              <div class="meta">현재 symbol validation case를 outcome control, rollout, lifecycle, A/B posture, condition split, capture, allocator 기준으로 다시 압축해 operator가 한 카드로 읽습니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Family', family)}
            ${badge('Deployment', validation?.deployment_go_no_go || 'n/a')}
            ${badge('Playbook', validation?.playbook_action || 'n/a')}
            ${badge('Rollout', rollout?.recommendation || 'n/a')}
            ${badge('Lifecycle', lifecycle?.state || 'n/a')}
            ${badge('Capture', captureBottleneck)}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Outcome Control', outcomeControl?.approval_penalty_status || 'n/a', outcomeControl?.summary || outcomeControl?.portfolio_bias_tier || 'outcome control unavailable')}
            ${renderSummaryBox('Rollout Recommendation', rollout?.recommendation || 'n/a', rollout?.summary || rollout?.confidence || 'rollout recommendation unavailable')}
            ${renderSummaryBox('Strategy Lifecycle', lifecycle?.state || 'n/a', lifecycle?.transition_bias || lifecycle?.summary || 'strategy lifecycle unavailable')}
            ${renderSummaryBox('Multi Strategy AB', multiStrategy?.mode || 'n/a', multiStrategy?.summary || multiStrategy?.b_cluster?.strategy_cluster_status || 'multi strategy summary unavailable')}
            ${renderSummaryBox('B Continuation Activation', bActivation?.activation_state || 'n/a', bActivation?.activation_bias || bActivation?.summary || 'b activation unavailable')}
            ${renderSummaryBox('Strategy Cluster Balance', clusterBalance?.balance_state || 'n/a', clusterBalance?.balance_bias || clusterBalance?.summary || 'cluster balance unavailable')}
            ${renderSummaryBox('Positive Evidence Expansion', expansion?.state || 'n/a', expansion?.expansion_bias || expansion?.summary || 'positive evidence expansion unavailable')}
            ${renderSummaryBox('Capital Allocator', allocator?.allocator_state || 'n/a', allocator?.capital_pressure || allocator?.summary || 'capital allocator unavailable')}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Top Condition Split</div>
              <div class="body">${esc(`${topCondition} | ${bucket?.summary || 'condition split summary unavailable'}`)}</div>
            </div>
            <div class="hint-card">
              <div class="title">Opportunity Capture</div>
              <div class="body">${esc(`${captureBottleneck} | ${capture?.summary || 'opportunity capture summary unavailable'}`)}</div>
            </div>
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Next Validation Move</div>
              <div class="body">${esc(nextMove)}</div>
            </div>
            <div class="hint-card">
              <div class="title">Operator Reading Order</div>
              <div class="body">${esc('outcome control -> rollout -> lifecycle -> A/B posture -> capture -> allocator 순서로 읽으면 현재 validation case를 빠르게 정리할 수 있습니다.')}</div>
            </div>
          </div>
        </div>
      `;
    }

    function renderRuntimeQualityInspector(dashboard) {
      const alerts = dashboard?.alert_summary || {};
      const overall = alerts?.overall || {};
      const retryQueue = alerts?.retry_queue || {};
      const latestAlert = alerts?.latest_validation_alert || {};
      const quality = dashboard?.execution_quality_summary || {};
      const reconcile = dashboard?.recent_reconciliation_summary || {};
      const queuedCount = retryQueue?.counts?.queued ?? 'n/a';
      const deadLetterCount = retryQueue?.counts?.dead_letter ?? 'n/a';
      const backlogAge = retryQueue?.backlog_age_seconds ?? 'n/a';
      const slippageP95 = quality?.slippage_bps?.p95;
      const qualityFocus = [
        `fill_rate=${quality?.fill_rate == null ? 'n/a' : Number(quality.fill_rate).toFixed(2)}`,
        `slippage_p95=${slippageP95 == null ? 'n/a' : Number(slippageP95).toFixed(2)}`,
        `forced_exit=${quality?.forced_exit_ratio == null ? 'n/a' : Number(quality.forced_exit_ratio).toFixed(2)}`,
      ].join(' | ');
      const retryFocus = `queued=${queuedCount} / dead_letter=${deadLetterCount} / backlog_age_seconds=${backlogAge}`;
      const nextMove = latestAlert?.approval_playbook_action
        || latestAlert?.approval_playbook_message
        || latestAlert?.deployment_message
        || dashboard?.playbook_message
        || 'runtime quality escalation summary unavailable';

      $('runtime-quality-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Runtime Quality Inspector</h2>
              <div class="meta">최근 validation alert, retry queue, execution quality, reconciliation health를 한 카드로 압축해 runtime 운영 품질을 빠르게 읽습니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Alert Overall', overall?.status || overall?.state || 'n/a')}
            ${badge('Latest Alert', latestAlert?.deployment_go_no_go || 'n/a')}
            ${badge('Retry Queue', queuedCount)}
            ${badge('Reconcile', reconcile?.highest_severity || 'n/a')}
            ${badge('Fill Rate', quality?.fill_rate == null ? 'n/a' : Number(quality.fill_rate).toFixed(2))}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Alert Overall', overall?.status || overall?.state || 'n/a', overall?.summary || `alerts_total=${fmtMaybe(overall?.alerts_total)}`)}
            ${renderSummaryBox('Latest Validation Alert', latestAlert?.deployment_go_no_go || 'n/a', latestAlert?.approval_playbook_action || latestAlert?.deployment_message || 'latest validation alert unavailable')}
            ${renderSummaryBox('Retry Queue', String(queuedCount), retryFocus)}
            ${renderSummaryBox('Execution Quality', quality?.fill_rate == null ? 'n/a' : Number(quality.fill_rate).toFixed(2), qualityFocus)}
            ${renderSummaryBox('Failure Mix', quality?.information_failure_ratio == null ? 'n/a' : Number(quality.information_failure_ratio).toFixed(2), `time=${fmtMaybe(quality?.time_failure_ratio)} | target_exit=${fmtMaybe(quality?.target_exit_ratio)}`)}
            ${renderSummaryBox('Reconciliation Health', reconcile?.highest_severity || 'n/a', `critical=${fmtMaybe(reconcile?.critical_count)} | lock_required=${fmtMaybe(reconcile?.lock_required_count)}`)}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Runtime Next Move</div>
              <div class="body">${esc(nextMove)}</div>
            </div>
            <div class="hint-card">
              <div class="title">Quality Drift Focus</div>
              <div class="body">${esc(`${qualityFocus} | retry=${retryFocus}`)}</div>
            </div>
          </div>
        </div>
      `;
    }

    function renderSignalFunnelInspector(dashboard) {
      const funnel = dashboard?.signal_funnel || {};
      const hard = funnel?.hard_block_summary || {};
      const soft = funnel?.softening_candidate_summary || {};
      const rollout = funnel?.rollout_block_summary || {};
      const priorities = Array.isArray(funnel?.quality_softening_priorities) ? funnel.quality_softening_priorities.slice(0, 5) : [];
      const family = Array.isArray(funnel?.family_bottlenecks) ? funnel.family_bottlenecks[0] : null;
      const regime = Array.isArray(funnel?.regime_bottlenecks) ? funnel.regime_bottlenecks[0] : null;
      const session = Array.isArray(funnel?.session_bottlenecks) ? funnel.session_bottlenecks[0] : null;
      const currentGate = funnel?.current_entry_gate_group || 'unknown';
      const currentGateReason = funnel?.current_entry_gate_reason || '현재 신규 진입 차단 사유가 없습니다.';

      $('signal-funnel-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Signal Funnel Inspector</h2>
              <div class="meta">현재 hard gate, softening 후보, rollout block, family/regime/session bottleneck을 홈 섹션에서 한 번에 읽도록 압축합니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Current Entry Gate', currentGate)}
            ${badge('Hard Block', String(hard?.blocked ?? 0))}
            ${badge('Softening', String(soft?.blocked ?? 0))}
            ${badge('Rollout Block', String(rollout?.blocked ?? 0))}
            ${badge('Runtime/Accepted', `${fmtMaybe(funnel?.runtime_candidates ?? 0)} / ${fmtMaybe(funnel?.accepted_candidates ?? 0)}`)}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Hard Gate Summary', String(hard?.blocked ?? 0), hard?.top_reason || currentGateReason)}
            ${renderSummaryBox('Softening Candidate Summary', String(soft?.blocked ?? 0), soft?.top_reason || 'quality softening candidate unavailable')}
            ${renderSummaryBox('Rollout Block Summary', String(rollout?.blocked ?? 0), rollout?.top_reason || 'rollout block unavailable')}
            ${renderSummaryBox('Top Family Bottleneck', family?.key || 'n/a', family ? `${fmtPercent(family.pass_rate)} | ${fmtR(family.avg_expected_ev_r)}` : 'family bottleneck unavailable')}
            ${renderSummaryBox('Top Regime Bottleneck', regime?.key || 'n/a', regime ? `${fmtPercent(regime.pass_rate)} | ${fmtR(regime.avg_expected_ev_r)}` : 'regime bottleneck unavailable')}
            ${renderSummaryBox('Top Session Bottleneck', session?.key || 'n/a', session ? `${fmtPercent(session.pass_rate)} | ${fmtR(session.avg_expected_ev_r)}` : 'session bottleneck unavailable')}
          </div>
          ${renderTable(
            priorities.map((row) => ({
              reason: row?.reason || 'n/a',
              blocked: row?.blocked ?? 0,
              top_family: row?.top_family || 'n/a',
              top_regime: row?.top_regime || 'n/a',
              top_session: row?.top_session || 'n/a',
              avg_expected_ev_r: row?.avg_expected_ev_r,
              avg_expected_win_prob: row?.avg_expected_win_prob,
            })),
            [
              { label: 'Reason', key: 'reason' },
              { label: 'Blocked', render: (row) => String(row.blocked ?? 0) },
              { label: 'Top Family', key: 'top_family' },
              { label: 'Top Regime', key: 'top_regime' },
              { label: 'Top Session', key: 'top_session' },
              { label: 'Avg EV', render: (row) => fmtR(row.avg_expected_ev_r) },
              { label: 'Avg Win', render: (row) => fmtPercent(row.avg_expected_win_prob) },
            ],
            '현재 quality softening priority queue가 없습니다.'
          )}
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Current Gate Reason</div>
              <div class="body">${esc(currentGateReason)}</div>
            </div>
            <div class="hint-card">
              <div class="title">Softening Priority Queue</div>
              <div class="body">${esc(priorities.length ? priorities.map((row) => row.reason || 'n/a').join(' | ') : '현재 완화 검토 우선순위가 없습니다.')}</div>
            </div>
          </div>
        </div>
      `;
    }

    function renderAlphaResearchInspector(dashboard) {
      const funnel = dashboard?.signal_funnel || {};
      const summary = funnel?.alpha_research_summary || {};
      const focus = funnel?.alpha_research_focus_alignment || {};
      const action = funnel?.alpha_research_recommended_action || {};
      const experiment = funnel?.alpha_research_top_shadow_experiment || {};
      const softening = funnel?.alpha_research_softening_review || {};
      const watchlist = funnel?.alpha_research_promotion_watchlist || {};
      const topReview = softening?.top_candidate || {};
      const topWatch = watchlist?.top_watch || {};
      const nextMove = action?.recommended_action
        || experiment?.recommended_action
        || topReview?.recommended_action
        || 'alpha research next move unavailable';

      $('alpha-research-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Alpha Research Inspector</h2>
              <div class="meta">research backlog, 추천 연구 액션, top shadow experiment, softening review, promotion watchlist를 홈 섹션에서 한 번에 읽도록 압축합니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Research Candidates', String(summary?.candidates ?? 0))}
            ${badge('Top Focus', focus?.top_focus || 'n/a')}
            ${badge('Recommended Action', action?.recommended_action || 'n/a')}
            ${badge('Shadow Experiment', experiment?.experiment_id || 'n/a')}
            ${badge('Watchlist', String(watchlist?.watchlist_count ?? 0))}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Alpha Research Summary', String(summary?.candidates ?? 0), summary?.top_reason ? `${summary.top_reason} (${summary.top_reason_count ?? 0})` : 'alpha research candidate unavailable')}
            ${renderSummaryBox('Research Focus Alignment', focus?.top_focus || 'n/a', focus?.top_bucket || `aligned=${fmtMaybe(focus?.aligned_candidate_count)}`)}
            ${renderSummaryBox('Recommended Research Action', action?.recommended_action || 'n/a', action?.recommended_reason || action?.recommended_scope || 'recommended research action unavailable')}
            ${renderSummaryBox('Top Shadow Experiment', experiment?.experiment_id || 'n/a', experiment?.target || experiment?.focus || 'shadow experiment unavailable')}
            ${renderSummaryBox('Softening Review', topReview?.bucket || 'n/a', topReview?.reason || `items=${fmtMaybe((softening?.review_items || []).length)}`)}
            ${renderSummaryBox('Promotion Watchlist', topWatch?.bucket || 'n/a', topWatch?.focus || `watchlist=${fmtMaybe(watchlist?.watchlist_count)}`)}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Research Next Move</div>
              <div class="body">${esc(nextMove)}</div>
            </div>
            <div class="hint-card">
              <div class="title">Top Shadow Metrics</div>
              <div class="body">${esc((experiment?.observe_metrics || []).length ? experiment.observe_metrics.join(', ') : '현재 관찰할 shadow metrics가 없습니다.')}</div>
            </div>
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Softening Review Queue</div>
              <div class="body">${esc((softening?.review_items || []).length ? softening.review_items.map((row) => row.bucket || row.focus || 'n/a').join(' | ') : '현재 softening review queue가 없습니다.')}</div>
            </div>
            <div class="hint-card">
              <div class="title">Promotion Watchlist Queue</div>
              <div class="body">${esc((watchlist?.watch_items || []).length ? watchlist.watch_items.map((row) => row.bucket || row.focus || 'n/a').join(' | ') : '현재 promotion watchlist queue가 없습니다.')}</div>
            </div>
          </div>
        </div>
      `;
    }

    function renderKillConditionInspector(dashboard) {
      const kill = dashboard?.signal_funnel?.kill_condition_automation || {};
      const source = kill?.source_summary || {};
      const nextMove = kill?.summary
        || dashboard?.blocking_reason_message
        || dashboard?.playbook_message
        || 'kill-condition next move unavailable';
      const currentLockState = [
        dashboard?.kill_switch_active ? 'kill-switch active' : '',
        dashboard?.close_only_active ? 'close-only active' : '',
        Number(source?.active_lock_count || 0) > 0 ? `active locks=${source.active_lock_count}` : '',
      ].filter(Boolean).join(' | ') || 'no active safety stop';

      $('kill-condition-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Kill Condition Inspector</h2>
              <div class="meta">stop review verdict, trigger axis, write scope, manual override, 현재 lock state를 홈 섹션에서 한 번에 읽도록 압축합니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Kill Condition', kill?.kill_condition_state || 'n/a')}
            ${badge('Automation Bias', kill?.automation_bias || 'n/a')}
            ${badge('Trigger Axis', kill?.trigger_axis || 'n/a')}
            ${badge('Write Scope', kill?.write_scope || 'n/a')}
            ${badge('Arm Required', boolLabel(Boolean(kill?.arm_required)))}
            ${badge('Manual Override', boolLabel(Boolean(kill?.active_manual_override)))}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Stop Review Verdict', kill?.kill_condition_state || 'n/a', kill?.summary || 'kill-condition summary unavailable')}
            ${renderSummaryBox('Trigger Axis', kill?.trigger_axis || 'n/a', source?.risk_gate_reason || source?.friction_weakest_axis || source?.generalization_weakest_axis || 'trigger axis unavailable')}
            ${renderSummaryBox('Write Scope', kill?.write_scope || 'n/a', kill?.arm_required ? 'explicit arm is required before any live stop write can happen.' : 'live arm not required in current state')}
            ${renderSummaryBox('Manual Override', kill?.active_manual_override ? 'active' : 'none', kill?.manual_override_reason || 'manual override not active')}
            ${renderSummaryBox('Current Lock State', currentLockState, dashboard?.new_entries_allowed === false ? (dashboard?.blocking_reason_message || 'entries are currently blocked') : 'new entries are currently allowed')}
            ${renderSummaryBox('Source Coverage', String(source?.available_source_count ?? 'n/a'), `risk=${source?.risk_gate_state || 'n/a'} | friction=${source?.friction_state || 'n/a'} | generalization=${source?.generalization_state || 'n/a'} | reconciliation=${source?.reconciliation_state || 'n/a'}`)}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Stop Review Queue</div>
              <div class="body">${esc((kill?.reason_codes || []).length ? kill.reason_codes.join(' | ') : '현재 kill-condition review reason code가 없습니다.')}</div>
            </div>
            <div class="hint-card">
              <div class="title">Live Stop Targets</div>
              <div class="body">${esc((source?.write_targets || []).length ? source.write_targets.join(' | ') : 'live stop target unavailable')}</div>
            </div>
          </div>
          <div class="hint-card" style="margin-top:12px;">
            <div class="title">Kill Condition Next Move</div>
            <div class="body">${esc(nextMove)}</div>
          </div>
        </div>
      `;
    }

    function renderPolicyLockInspector(dashboard) {
      const locks = Array.isArray(dashboard?.active_locks) ? dashboard.active_locks : [];
      const matchingLocks = Array.isArray(dashboard?.matching_locks) ? dashboard.matching_locks : [];
      const policies = Array.isArray(dashboard?.rollout_policies) ? dashboard.rollout_policies : [];
      const topLock = locks[0] || {};
      const topMatchingLock = matchingLocks[0] || {};
      const topPolicy = policies[0] || {};
      const nextMove = dashboard?.playbook_action
        || dashboard?.playbook_message
        || topLock?.reason_message
        || 'policy / lock next move unavailable';

      $('policy-lock-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Policy / Lock Inspector</h2>
              <div class="meta">kill switch, close-only, active lock, matching lock, rollout policy를 홈 섹션에서 한 번에 읽도록 압축합니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Kill Switch', boolLabel(Boolean(dashboard?.kill_switch_active)))}
            ${badge('Close Only', boolLabel(Boolean(dashboard?.close_only_active)))}
            ${badge('Config Close Only', boolLabel(Boolean(dashboard?.config_close_only_active)))}
            ${badge('Active Locks', String(locks.length))}
            ${badge('Rollout Policies', String(policies.length))}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Top Active Lock', topLock?.reason_code || 'n/a', topLock?.reason_message || `${topLock?.scope_type || 'n/a'}:${topLock?.scope_key || '*'}`)}
            ${renderSummaryBox('Top Matching Lock', topMatchingLock?.reason_code || 'n/a', topMatchingLock?.reason_message || `${topMatchingLock?.scope_type || 'n/a'}:${topMatchingLock?.scope_key || '*'}`)}
            ${renderSummaryBox('Top Rollout Policy', topPolicy?.strategy_family || 'n/a', `live=${fmtMaybe(topPolicy?.live_enabled)} | mode=${fmtMaybe(topPolicy?.max_execution_mode)}`)}
            ${renderSummaryBox('Policy Playbook', dashboard?.playbook_action || 'n/a', dashboard?.playbook_message || 'runtime playbook unavailable')}
            ${renderSummaryBox('Entry Policy', dashboard?.new_entries_allowed === false ? 'blocked' : 'allowed', dashboard?.blocking_reason_message || 'entry policy message unavailable')}
            ${renderSummaryBox('Policy Surface', 'runtime authority', 'lock / rollout policy는 기간 필터와 무관한 현재 운영 규칙입니다.')}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Active Lock Queue</div>
              <div class="body">${esc(locks.length ? locks.slice(0, 3).map((row) => row.reason_code || `${row.scope_type}:${row.scope_key || '*'}`).join(' | ') : '현재 활성 lock이 없습니다.')}</div>
            </div>
            <div class="hint-card">
              <div class="title">Rollout Policy Queue</div>
              <div class="body">${esc(policies.length ? policies.slice(0, 3).map((row) => `${row.strategy_family}:${row.max_execution_mode || 'n/a'}`).join(' | ') : '현재 rollout policy가 없습니다.')}</div>
            </div>
          </div>
          <div class="hint-card" style="margin-top:12px;">
            <div class="title">Policy Next Move</div>
            <div class="body">${esc(nextMove)}</div>
          </div>
        </div>
      `;
    }

    function renderIntentExposureInspector(dashboard) {
      const intents = Array.isArray(dashboard?.recent_intents) ? dashboard.recent_intents : [];
      const orders = Array.isArray(dashboard?.open_orders) ? dashboard.open_orders : [];
      const positions = Array.isArray(dashboard?.open_positions) ? dashboard.open_positions : [];
      const latestIntent = intents[0] || {};
      const topOrder = orders[0] || {};
      const topPosition = positions[0] || {};
      const nextMove = latestIntent?.playbook_action
        || latestIntent?.decision_reason_code
        || dashboard?.playbook_action
        || 'recent intent summary unavailable';

      $('intent-exposure-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Intent / Exposure Inspector</h2>
              <div class="meta">최근 intent 흐름, 열린 주문, 열린 포지션, 현재 익스포저 상태를 홈 섹션에서 한 번에 읽도록 압축합니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Recent Intents', String(intents.length))}
            ${badge('Open Orders', String(orders.length))}
            ${badge('Open Positions', String(positions.length))}
            ${badge('Latest Decision', latestIntent?.submit_decision || 'n/a')}
            ${badge('Latest Deployment', latestIntent?.deployment_go_no_go || 'n/a')}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Latest Intent', latestIntent?.submit_decision || 'n/a', latestIntent?.decision_reason_code || latestIntent?.playbook_action || 'recent intent unavailable')}
            ${renderSummaryBox('Latest Intent Family', latestIntent?.strategy_family || 'n/a', latestIntent?.created_at || 'intent timestamp unavailable')}
            ${renderSummaryBox('Top Open Order', topOrder?.symbol || 'n/a', topOrder?.state || topOrder?.client_order_id || 'open order unavailable')}
            ${renderSummaryBox('Top Open Position', topPosition?.symbol || 'n/a', `${fmtMaybe(topPosition?.position_side)} / pnl=${fmtMaybe(topPosition?.unrealized_pnl)}`)}
            ${renderSummaryBox('Exposure Surface', `${orders.length} / ${positions.length}`, 'open orders / open positions')}
            ${renderSummaryBox('Intent Window', `최근 ${dashboard.report_window_days || $('days').value || 7}일`, 'intent는 최근 일수 기준, 주문/포지션은 활성 상태 기준')}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Recent Intent Queue</div>
              <div class="body">${esc(intents.length ? intents.slice(0, 3).map((row) => `${row.submit_decision || 'n/a'}:${row.strategy_family || 'n/a'}`).join(' | ') : '최근 intent queue가 없습니다.')}</div>
            </div>
            <div class="hint-card">
              <div class="title">Live Exposure Queue</div>
              <div class="body">${esc(positions.length ? positions.slice(0, 3).map((row) => `${row.symbol || 'n/a'}:${row.position_side || 'n/a'}`).join(' | ') : (orders.length ? orders.slice(0, 3).map((row) => `${row.symbol || 'n/a'}:${row.state || 'n/a'}`).join(' | ') : '현재 live exposure queue가 없습니다.'))}</div>
            </div>
          </div>
          <div class="hint-card" style="margin-top:12px;">
            <div class="title">Intent Next Move</div>
            <div class="body">${esc(nextMove)}</div>
          </div>
        </div>
      `;
    }

    function renderModeDeploymentInspector(dashboard, checklist, validation) {
      const rollout = validation?.rollout_recommendation_summary || {};
      const modeAdvisory = validation?.mode_advisory_summary || {};
      const multiStrategy = validation?.multi_strategy_ab_summary || {};
      const familyTop = modeAdvisory?.family_top || {};
      const regimeTop = modeAdvisory?.regime_top || {};
      const sessionTop = modeAdvisory?.session_top || {};
      const modeTop = [familyTop, regimeTop, sessionTop].find((row) => row && row.bucket) || familyTop;
      const liveMode = multiStrategy?.mode || 'n/a';
      const nextMove = dashboard?.playbook_action
        || validation?.playbook_action
        || checklist?.playbook_action
        || rollout?.summary
        || 'mode / deployment next move unavailable';

      $('mode-deployment-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Mode / Deployment Inspector</h2>
              <div class="meta">execution mode, entry gate, dashboard-checklist-validation 배포 상태, rollout recommendation, mode advisory를 홈 섹션에서 한 번에 읽도록 압축합니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Execution Mode', dashboard?.execution_mode || 'n/a')}
            ${badge('Live Strategy Mode', liveMode)}
            ${badge('New Entries', dashboard?.new_entries_allowed === false ? 'blocked' : 'allowed')}
            ${badge('Dashboard', dashboard?.deployment_go_no_go || 'n/a')}
            ${badge('Checklist', checklist?.deployment_go_no_go || 'n/a')}
            ${badge('Validation', validation?.deployment_go_no_go || 'n/a')}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Dashboard Deployment', dashboard?.deployment_go_no_go || 'n/a', dashboard?.playbook_action || dashboard?.playbook_message || 'dashboard deployment unavailable')}
            ${renderSummaryBox('Checklist Deployment', checklist?.deployment_go_no_go || 'n/a', checklist?.playbook_action || checklist?.playbook_message || 'checklist deployment unavailable')}
            ${renderSummaryBox('Validation Deployment', validation?.deployment_go_no_go || 'n/a', validation?.playbook_action || validation?.deployment_message || 'validation deployment unavailable')}
            ${renderSummaryBox('Rollout Recommendation', rollout?.recommendation || 'n/a', rollout?.summary || rollout?.confidence || 'rollout recommendation unavailable')}
            ${renderSummaryBox('Mode Advisory', modeTop?.advisory_state || 'n/a', modeTop?.bucket ? `${modeTop.axis || 'bucket'}=${modeTop.bucket}` : 'mode advisory unavailable')}
            ${renderSummaryBox('Multi Strategy Mode', liveMode, multiStrategy?.summary || multiStrategy?.b_cluster?.strategy_cluster_status || 'multi strategy mode unavailable')}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Entry Gate Reason</div>
              <div class="body">${esc(dashboard?.blocking_reason_message || dashboard?.playbook_message || '현재 entry gate reason이 없습니다.')}</div>
            </div>
            <div class="hint-card">
              <div class="title">Top Mode Bucket</div>
              <div class="body">${esc(modeTop?.bucket ? `${modeTop.axis || 'bucket'}=${modeTop.bucket} | ${modeTop.advisory_state || 'n/a'}` : '현재 top mode bucket이 없습니다.')}</div>
            </div>
          </div>
          <div class="hint-card" style="margin-top:12px;">
            <div class="title">Deployment Next Move</div>
            <div class="body">${esc(nextMove)}</div>
          </div>
        </div>
      `;
    }

    function renderApprovalAlignmentInspector(dashboard, checklist, validation, candidate) {
      const operatorPriority = dashboard?.signal_funnel?.operator_action_priority || {};
      const deploymentStatuses = [
        dashboard?.deployment_go_no_go,
        checklist?.deployment_go_no_go,
        validation?.deployment_go_no_go,
      ].filter((value) => value);
      const playbookActions = [
        dashboard?.playbook_action,
        checklist?.playbook_action,
        validation?.playbook_action,
      ].filter((value) => value);
      const deploymentAligned = new Set(deploymentStatuses).size <= 1;
      const playbookAligned = new Set(playbookActions).size <= 1;
      const alignmentState = deploymentAligned && playbookAligned ? 'aligned' : 'diverged';
      const nextMove = operatorPriority?.top_action
        || dashboard?.playbook_action
        || validation?.playbook_action
        || checklist?.playbook_action
        || 'approval alignment next move unavailable';

      $('approval-alignment-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Approval Alignment Inspector</h2>
              <div class="meta">dashboard, checklist, validation, candidate, operator priority가 같은 배포 방향을 가리키는지 홈 섹션에서 한 번에 읽도록 압축합니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Alignment', alignmentState)}
            ${badge('Dashboard', dashboard?.deployment_go_no_go || 'n/a')}
            ${badge('Checklist', checklist?.deployment_go_no_go || 'n/a')}
            ${badge('Validation', validation?.deployment_go_no_go || 'n/a')}
            ${badge('Candidate', candidate?.deployment_go_no_go || candidate?.operator_status || 'n/a')}
            ${badge('Operator Priority', operatorPriority?.priority_level || 'n/a')}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Dashboard Surface', dashboard?.deployment_go_no_go || 'n/a', dashboard?.playbook_action || dashboard?.playbook_message || 'dashboard surface unavailable')}
            ${renderSummaryBox('Checklist Surface', checklist?.deployment_go_no_go || 'n/a', checklist?.playbook_action || checklist?.playbook_message || 'checklist surface unavailable')}
            ${renderSummaryBox('Validation Surface', validation?.deployment_go_no_go || 'n/a', validation?.playbook_action || validation?.approval_topline_summary_line || 'validation surface unavailable')}
            ${renderSummaryBox('Candidate Surface', candidate?.deployment_go_no_go || candidate?.operator_status || 'n/a', candidate?.block_reason_message || candidate?.deployment_message || 'candidate surface unavailable')}
            ${renderSummaryBox('Operator Action Priority', operatorPriority?.top_action || 'n/a', operatorPriority?.top_reason || operatorPriority?.priority_source || 'operator action priority unavailable')}
            ${renderSummaryBox('Playbook Alignment', playbookAligned ? 'aligned' : 'diverged', playbookActions.length ? playbookActions.join(' | ') : 'playbook action unavailable')}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Deployment Message Stack</div>
              <div class="body">${esc([
                dashboard?.blocking_reason_message || dashboard?.playbook_message,
                checklist?.deployment_message || checklist?.playbook_message,
                validation?.deployment_message || validation?.approval_topline_summary_line,
              ].filter(Boolean).join(' | ') || '현재 deployment message stack이 없습니다.')}</div>
            </div>
            <div class="hint-card">
              <div class="title">Approval Next Move</div>
              <div class="body">${esc(nextMove)}</div>
            </div>
          </div>
        </div>
      `;
    }

    function renderDataFreshnessSourceInspector(dashboard, checklist, validation) {
      const validationReport = validation?.validation_report || {};
      const validationPath = validationReport?.path || '';
      const checklistPath = checklist?.report_path || '';
      const executionQualityPath = dashboard?.execution_quality_summary?.report_path || '';
      const dashboardGenerated = dashboard?.generated_at || 'n/a';
      const validationGenerated = validationReport?.generated_at || 'n/a';
      const checklistGenerated = checklist?.generated_at || 'n/a';
      const reportWindow = dashboard?.report_window_days || $('days').value || 'n/a';
      const pathReadyCount = [validationPath, checklistPath, executionQualityPath].filter(Boolean).length;

      $('data-freshness-source-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Data Freshness / Source Inspector</h2>
              <div class="meta">dashboard, validation, checklist, execution-quality source와 generated_at / report path 상태를 홈 섹션에서 바로 확인합니다.</div>
            </div>
          </div>
          <div class="desk-strip">
            ${badge('Report Window', `최근 ${reportWindow}일`)}
            ${badge('Dashboard Generated', dashboardGenerated)}
            ${badge('Validation Generated', validationGenerated)}
            ${badge('Checklist Generated', checklistGenerated)}
            ${badge('Report Paths', String(pathReadyCount))}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Dashboard Source', '/execution/operator-dashboard', dashboardGenerated)}
            ${renderSummaryBox('Validation Source', '/validation/report', validationGenerated)}
            ${renderSummaryBox('Checklist Source', '/operations/checklist', checklistGenerated)}
            ${renderSummaryBox('Execution Quality Source', '/execution/quality', executionQualityPath || 'report path unavailable')}
            ${renderSummaryBox('Validation Report Path', validationPath ? 'ready' : 'missing', validationPath || 'validation report path unavailable')}
            ${renderSummaryBox('Checklist Report Path', checklistPath ? 'ready' : 'missing', checklistPath || 'checklist report path unavailable')}
          </div>
          <div class="grid two" style="margin-top:12px;">
            <div class="hint-card">
              <div class="title">Source Flow</div>
              <div class="body">${esc('/execution/operator-dashboard -> /validation/report -> /operations/checklist -> /execution/quality')}</div>
            </div>
            <div class="hint-card">
              <div class="title">Freshness Note</div>
              <div class="body">${esc(`dashboard/checklist/validation generated_at을 먼저 보고, 더 깊은 근거는 report path로 내려가면 됩니다.`)}</div>
            </div>
          </div>
        </div>
      `;
    }

    function portfolioCandidateRows(portfolio) {
      const accepted = (Array.isArray(portfolio?.accepted_candidates) ? portfolio.accepted_candidates : []).map((row) => ({
        bucket: 'accepted',
        ...row,
      }));
      const blocked = (Array.isArray(portfolio?.blocked_candidates) ? portfolio.blocked_candidates : []).map((row) => ({
        bucket: 'blocked',
        ...row,
      }));
      return [...accepted, ...blocked];
    }

    function renderPortfolioCandidateDrilldown(dashboard) {
      const portfolio = dashboard?.portfolio_summary || {};
      const rows = portfolioCandidateRows(portfolio);
      $('portfolio-candidate-drilldown').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Portfolio Candidate Drilldown</h2>
              <div class="meta">accepted / blocked 후보를 raw JSON 없이 읽기 위해, cluster, allocated risk, outcome bias, capital allocator, A/B posture를 같은 표로 보여줍니다.</div>
            </div>
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Accepted Candidates', String(portfolio?.accepted_candidate_count ?? 0), portfolio?.playbook_action || 'portfolio accepted summary unavailable')}
            ${renderSummaryBox('Blocked Candidates', String(portfolio?.blocked_candidate_count ?? 0), portfolio?.deployment_message || 'portfolio blocked summary unavailable')}
            ${renderSummaryBox('Capital Allocator', portfolio?.capital_allocator_summary?.allocator_state || 'n/a', portfolio?.capital_allocator_summary?.capital_pressure || 'capital allocator summary unavailable')}
            ${renderSummaryBox('Cluster Balance', portfolio?.strategy_cluster_balance_summary?.balance_state || 'n/a', portfolio?.strategy_cluster_balance_summary?.balance_bias || 'cluster balance summary unavailable')}
          </div>
          ${renderTable(
            rows,
            [
              { label: 'Bucket', key: 'bucket' },
              { label: 'Symbol', key: 'symbol' },
              { label: 'Family', key: 'strategy_family' },
              { label: 'Cluster', render: (row) => row.strategy_cluster || row.multi_strategy_overlay?.cluster || 'n/a' },
              { label: 'Risk', render: (row) => `${fmtR(row.recommended_risk_r)} / ${fmtR(row.allocated_risk_r)}` },
              { label: 'Outcome Bias', render: (row) => row.outcome_bias?.tier || 'n/a' },
              { label: 'Allocator', render: (row) => row.capital_allocator?.tier || row.capital_pressure || 'n/a' },
              { label: 'A/B Posture', render: (row) => row.strategy_cluster_balance?.balance_state || row.b_continuation_activation?.activation_state || 'n/a' },
              { label: 'Block / Size', render: (row) => row.block_reason || row.strategy_sizing?.outcome_risk_adjustment?.reason_code || 'n/a' },
            ],
            '현재 portfolio candidate drilldown rows가 없습니다.'
          )}
        </div>
      `;
    }

    function candidateInspectorCard(label, row, emptyText) {
      if (!row) {
        return `
          <div class="panel">
            <h2>${esc(label)}</h2>
            <div class="empty">${esc(emptyText)}</div>
          </div>
        `;
      }
      const abSummary = row?.strategy_cluster_balance?.summary
        || row?.b_continuation_activation?.summary
        || row?.multi_strategy_overlay?.summary
        || row?.expected_summary
        || 'A/B posture summary unavailable';
      const sizingReason = row?.strategy_sizing?.outcome_risk_adjustment?.reason_code || 'n/a';
      const sessionState = row?.session_guidance?.state || row?.session_guidance?.guidance_state || 'n/a';
      const reactionClass = row?.reaction_evidence?.reaction_classification || row?.reaction_evidence?.state || 'n/a';
      const locationRef = row?.location_reference?.label || row?.location_reference?.reference || row?.location_reference?.state || 'n/a';
      const liquidityRef = row?.session_liquidity_reference?.label
        || row?.session_liquidity_reference?.reference
        || row?.session_liquidity_reference?.state
        || 'n/a';
      return `
        <div class="panel">
          <h2>${esc(label)}</h2>
          <div class="desk-strip">
            ${badge('Symbol', row.symbol || 'n/a')}
            ${badge('Family', row.strategy_family || 'n/a')}
            ${badge('Cluster', row.strategy_cluster || row.multi_strategy_overlay?.cluster || 'n/a')}
            ${badge('Bucket', row.block_reason ? 'blocked' : 'accepted')}
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Risk', `${fmtR(row.recommended_risk_r)} / ${fmtR(row.allocated_risk_r)}`, `recommended / allocated | ${sizingReason}`)}
            ${renderSummaryBox('Outcome Bias', row.outcome_bias?.tier || 'n/a', row.outcome_bias?.summary || `score=${fmtMaybe(row.outcome_bias?.score_delta)}`)}
            ${renderSummaryBox('Capital Allocator', row.capital_allocator?.tier || 'n/a', row.capital_pressure || 'capital pressure unavailable')}
            ${renderSummaryBox('A/B Posture', row.strategy_cluster_balance?.balance_state || row.b_continuation_activation?.activation_state || 'n/a', abSummary)}
            ${renderSummaryBox('Session Guidance', sessionState, `penalty=${fmtMaybe(row.session_penalty)}`)}
            ${renderSummaryBox('Reaction Evidence', reactionClass, `location=${locationRef} | liquidity=${liquidityRef}`)}
          </div>
          <div class="hint-card">
            <div class="title">Why This Row Matters</div>
            <div class="body">${esc(row.block_reason || abSummary)}</div>
          </div>
        </div>
      `;
    }

    function renderPortfolioCandidateInspector(dashboard) {
      const portfolio = dashboard?.portfolio_summary || {};
      const accepted = Array.isArray(portfolio?.accepted_candidates) ? portfolio.accepted_candidates[0] : null;
      const blocked = Array.isArray(portfolio?.blocked_candidates) ? portfolio.blocked_candidates[0] : null;
      $('portfolio-candidate-inspector').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Portfolio Candidate Inspector</h2>
              <div class="meta">대표 accepted row 1개와 blocked row 1개를 카드로 다시 압축해, risk, allocator, A/B posture, session, reaction evidence를 바로 읽습니다.</div>
            </div>
          </div>
          <div class="grid two">
            ${candidateInspectorCard('Representative Accepted Candidate', accepted, '대표 accepted candidate가 없습니다.')}
            ${candidateInspectorCard('Representative Blocked Candidate', blocked, '대표 blocked candidate가 없습니다.')}
          </div>
        </div>
      `;
    }

    function checklistEvidenceSummary(check) {
      const evidence = check?.evidence || {};
      if (typeof evidence !== 'object' || evidence == null) {
        return check?.summary || 'evidence unavailable';
      }
      const importantKeys = [
        'top_action',
        'priority_source',
        'recommendation',
        'mode',
        'activation_state',
        'balance_state',
        'state',
        'queue_state',
        'top_review_action',
        'top_remediation_action',
        'clearance_state',
        'top_reopen_action',
        'brief_state',
        'execution_stage',
        'history_state',
        'loop_state',
        'dominant_bottleneck',
        'allocator_state',
      ];
      const parts = [];
      importantKeys.forEach((key) => {
        const value = evidence[key];
        if (value == null || value === '') return;
        if (typeof value === 'object') {
          if (value.reason) {
            parts.push(`${key}=${value.reason}`);
          } else if (value.key) {
            parts.push(`${key}=${value.key}`);
          }
          return;
        }
        parts.push(`${key}=${value}`);
      });
      return parts.length ? parts.join(' | ') : (check?.summary || 'evidence unavailable');
    }

    function renderChecklistEvidenceDrilldown(checklist) {
      const checks = Array.isArray(checklist?.checks) ? checklist.checks : [];
      const rows = checks
        .filter((row) => ['FAIL', 'MANUAL', 'WARN'].includes(String(row?.status || '').toUpperCase()))
        .slice(0, 12)
        .map((row) => ({
          title: row.title || row.item_id || 'n/a',
          status: row.status || 'n/a',
          category: row.category || 'n/a',
          blocking: row.blocking ? 'yes' : 'no',
          summary: row.summary || 'summary unavailable',
          evidence_summary: checklistEvidenceSummary(row),
        }));

      $('checklist-evidence-drilldown').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Checklist Evidence Drilldown</h2>
              <div class="meta">WARN / MANUAL / FAIL 체크를 evidence 중심으로 다시 펼쳐서, raw checklist payload 없이 operator review 포인트를 읽습니다.</div>
            </div>
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Overall Status', checklist?.overall_status || 'n/a', checklist?.deployment_message || 'overall checklist status unavailable')}
            ${renderSummaryBox('Blocking Failures', String(checklist?.blocking_failures ?? 0), checklist?.playbook_action || 'blocking failure summary unavailable')}
            ${renderSummaryBox('Manual Actions', String(checklist?.manual_actions ?? 0), checklist?.playbook_message || 'manual action summary unavailable')}
            ${renderSummaryBox('Warnings', String(checklist?.warnings ?? 0), 'non-blocking operator review count')}
          </div>
          ${renderTable(
            rows,
            [
              { label: 'Title', key: 'title' },
              { label: 'Status', key: 'status' },
              { label: 'Category', key: 'category' },
              { label: 'Blocking', key: 'blocking' },
              { label: 'Summary', key: 'summary' },
              { label: 'Evidence', key: 'evidence_summary' },
            ],
            '현재 checklist evidence drilldown 대상이 없습니다.'
          )}
        </div>
      `;
    }

    function renderReportNavigation(dashboard, checklist, validation) {
      const validationPath = validation?.path || validation?.report_path || '';
      const checklistPath = checklist?.report_path || '';
      const executionQualityPath = dashboard?.execution_quality_summary?.report_path || '';
      $('report-navigation').innerHTML = `
        <div class="panel">
          <div class="section-header">
            <div>
              <h2>Report Navigation</h2>
              <div class="meta">validation / checklist / execution quality 리포트 파일을 raw JSON 없이 바로 열 수 있게 경로와 file link를 같이 보여줍니다.</div>
            </div>
          </div>
          <div class="summary-grid">
            ${renderSummaryBox('Validation Report', validationPath ? 'ready' : 'missing', validationPath || '/validation/report')}
            ${renderSummaryBox('Checklist Report', checklistPath ? 'ready' : 'missing', checklistPath || '/operations/checklist')}
            ${renderSummaryBox('Execution Quality Report', executionQualityPath ? 'ready' : 'missing', executionQualityPath || '/execution/quality')}
            ${renderSummaryBox('Home Review Flow', 'operator-ui -> report', 'home panel에서 요약을 보고 필요할 때 파일 report로 내려갑니다.')}
          </div>
          <div class="grid three" style="margin-top:12px;">
            ${renderFileHint('Validation Report File', validationPath, '/validation/report')}
            ${renderFileHint('Checklist Report File', checklistPath, '/operations/checklist')}
            ${renderFileHint('Execution Quality Report File', executionQualityPath, '/execution/quality')}
          </div>
        </div>
      `;
    }

    function renderOverview(symbol, dashboard, checklist, validation, plan, candidate) {
      const tradeStatus = deriveTradeStatus(dashboard, candidate, plan);
      const reason = deriveTradeReason(dashboard, candidate, plan);
      const family = candidate?.strategy_family || plan?.strategy_family || plan?.validity?.strategy_family || 'n/a';
      const model = candidate?.entry_model || plan?.entry_model || 'n/a';
      const entry = plan?.entry_price ?? candidate?.entry_price;
      const stop = plan?.sl ?? candidate?.sl;
      const tp1 = plan?.tp1 ?? candidate?.tp1;
      const win = plan?.expected_win_prob ?? candidate?.expected_win_prob;
      const ev = plan?.expected_ev_r ?? candidate?.expected_ev_r;
      const risk = (plan?.validity?.recommended_risk_r ?? candidate?.recommended_risk_r);
      const whyNow = candidate?.why_now || plan?.validity?.entry_reason || '현재 대표 플랜 기준';
      $('overview').innerHTML = `
        <div>${badge('현재 상태', tradeStatus)} ${badge('서버 승인', dashboard?.deployment_go_no_go || 'n/a')} ${badge('체크리스트', checklist?.deployment_go_no_go || 'n/a')} ${badge('검증', validation?.deployment_go_no_go || 'n/a')}</div>
        <div class="strong-line">${esc(reason)}</div>
        <div class="summary-grid">
          ${renderSummaryBox('대표 전략', `${fmtMaybe(family)} / ${fmtMaybe(model)}`, candidate?.strategy_grade ? `등급 ${candidate.strategy_grade}` : '')}
          ${renderSummaryBox('진입 / 손절 / 1차목표', `${fmtPrice(entry)} / ${fmtPrice(stop)} / ${fmtPrice(tp1)}`, 'entry / stop / tp1')}
          ${renderSummaryBox('추정 승률 / 기대값', `${fmtPercent(win)} / ${fmtR(ev)}`, plan?.expected_summary || candidate?.expected_summary || '')}
          ${renderSummaryBox('권장 리스크', fmtR(risk), '현재 엔진이 권장하는 size')}
          ${renderSummaryBox('왜 지금 보나', fmtMaybe(whyNow), candidate?.entry_condition || '')}
          ${renderSummaryBox('소스', '서버 런타임 기준', 'chart mirror가 아니라 server truth wins on scanner / portfolio / validation surfaces')}
        </div>
      `;
    }

    function renderCards(dashboard, plan, candidate) {
      const cards = [
        {
          title: '현재 상태',
          metric: deriveTradeStatus(dashboard, candidate, plan),
          meta: deriveTradeReason(dashboard, candidate, plan),
        },
        {
          title: '대표 Family',
          metric: candidate?.strategy_family || plan?.strategy_family || plan?.validity?.strategy_family || 'n/a',
          meta: candidate?.strategy_family_reason || plan?.validity?.strategy_family_reason || '현재 대표 후보 기준',
        },
        {
          title: '진입 방식',
          metric: candidate?.entry_model || plan?.entry_model || 'n/a',
          meta: candidate?.entry_condition || 'entry condition unavailable',
        },
        {
          title: '추정 승률',
          metric: fmtPercent(plan?.expected_win_prob ?? candidate?.expected_win_prob),
          meta: plan?.expected_summary || candidate?.expected_summary || 'expected summary unavailable',
        },
        {
          title: '기대값(R)',
          metric: fmtR(plan?.expected_ev_r ?? candidate?.expected_ev_r),
          meta: `권장 size 반영: ${fmtR(plan?.expected_ev_at_recommended_size_r ?? candidate?.expected_ev_at_recommended_size_r)}`,
        },
        {
          title: '권장 리스크',
          metric: fmtR(plan?.validity?.recommended_risk_r ?? candidate?.recommended_risk_r),
          meta: dashboard?.playbook_action || dashboard?.playbook_message || 'runtime policy unavailable',
        },
      ];
      $('cards').innerHTML = cards.map((card) => `
        <div class="panel">
          <h2>${esc(card.title)}</h2>
          <div class="metric">${esc(card.metric)}</div>
          <div class="meta">${esc(card.meta)}</div>
        </div>
      `).join('');
    }

    function renderApproval(checklist, validation) {
      const checklistHtml = `
        <div>${badge('체크리스트', checklist?.deployment_go_no_go || 'n/a')}</div>
        <div class="meta">${esc(checklist?.deployment_message || '체크리스트 배포 메시지가 없습니다.')}</div>
        <div>${badge('체크리스트 액션', checklist?.playbook_go_no_go || 'n/a')}</div>
        <div class="meta">${esc(checklist?.playbook_action || checklist?.playbook_message || '체크리스트 플레이북 액션이 없습니다.')}</div>
      `;
      const validationHtml = `
        <div>${badge('검증 리포트', validation?.deployment_go_no_go || 'n/a')}</div>
        <div class="meta">${esc(validation?.deployment_message || '검증 배포 메시지가 없습니다.')}</div>
        <div>${badge('최상단 승인', validation?.approval_topline_status || 'n/a')}</div>
        <div class="meta">${esc(validation?.approval_topline_summary_line || validation?.approval_topline_message || '최상단 승인 요약이 없습니다.')}</div>
      `;
      $('approval-summary').innerHTML = checklistHtml + validationHtml;
    }

    function renderRuntime(dashboard) {
      const portfolio = dashboard.portfolio_summary || {};
      const alerts = dashboard.alert_summary || {};
      const latestAlert = alerts.latest_validation_alert || {};
      const quality = dashboard.execution_quality_summary || {};
      $('runtime-summary').innerHTML = `
        <div>${badge('포트폴리오', portfolio.deployment_go_no_go || 'n/a')}</div>
        <div class="meta">${esc(portfolio.playbook_action || portfolio.deployment_message || '포트폴리오 요약이 없습니다.')}</div>
        <div>${badge('최근 검증 알림', latestAlert.deployment_go_no_go || 'n/a')}</div>
        <div class="meta">${esc(latestAlert.approval_playbook_action || latestAlert.deployment_message || '최근 검증 알림이 없습니다.')}</div>
        <div>${badge('체결률', quality.fill_rate == null ? 'n/a' : quality.fill_rate.toFixed(2))}</div>
        <div class="meta">${esc(`목표청산=${quality.target_exit_ratio ?? 'n/a'} 강제청산=${quality.forced_exit_ratio ?? 'n/a'} 정보실패=${quality.information_failure_ratio ?? 'n/a'}`)}</div>
      `;
    }

    function renderPlanList(plans) {
      if (!Array.isArray(plans) || plans.length === 0) {
        $('plan-list').innerHTML = '<div class="empty">활성 플랜이 없습니다.</div>';
        return;
      }
      $('plan-list').innerHTML = plans.slice(0, 6).map((plan, index) => `
        <div class="list-card">
          <div class="title">
            <span>${esc(`#${index + 1} ${plan.direction || 'n/a'} / ${plan.entry_model || 'n/a'}`)}</span>
            <span class="badge ${badgeClass(plan.expected_ev_r)}">${esc(fmtR(plan.expected_ev_r))}</span>
          </div>
          <div class="desc">${esc(plan.expected_summary || '요약 없음')}</div>
          <div class="meta-row">
            ${badge('승률', fmtPercent(plan.expected_win_prob))}
            ${badge('리스크', fmtR(plan.validity?.recommended_risk_r))}
          </div>
          <div class="meta-row">
            ${badge('진입', fmtPrice(plan.entry_price))}
            ${badge('손절', fmtPrice(plan.sl))}
            ${badge('TP1', fmtPrice(plan.tp1))}
          </div>
        </div>
      `).join('');
    }

    function renderCandidateList(scannerRows, symbol) {
      if (!Array.isArray(scannerRows) || scannerRows.length === 0) {
        $('candidate-list').innerHTML = '<div class="empty">실행 가능한 후보가 없습니다.</div>';
        return;
      }
      $('candidate-list').innerHTML = scannerRows.slice(0, 8).map((row, index) => `
        <div class="list-card">
          <div class="title">
            <span>${esc(`#${index + 1} ${row.symbol}${row.symbol === symbol ? ' (현재)' : ''}`)}</span>
            <span class="badge ${badgeClass(row.deployment_go_no_go || row.operator_status)}">${esc(row.deployment_go_no_go || row.operator_status || 'n/a')}</span>
          </div>
          <div class="desc">${esc(row.block_reason_message || row.deployment_message || row.expected_summary || '요약 없음')}</div>
          <div class="meta-row">
            ${badge('Family', row.strategy_family || 'n/a')}
            ${badge('Cluster', row.strategy_cluster || row.multi_strategy_overlay?.cluster || 'n/a')}
            ${badge('Cluster 상태', row.strategy_cluster_status || row.multi_strategy_overlay?.strategy_cluster_status || 'n/a')}
          </div>
          <div class="meta-row">
            ${badge('모델', row.entry_model || 'n/a')}
            ${badge('등급', row.strategy_grade || 'n/a')}
            ${badge('B 상태', row.b_continuation_activation?.activation_state || 'n/a')}
          </div>
          <div class="meta-row">
            ${badge('Est. win', fmtPercent(row.expected_win_prob))}
            ${badge('Est. EV', fmtR(row.expected_ev_r))}
            ${badge('리스크', fmtR(row.recommended_risk_r))}
          </div>
        </div>
      `).join('');
    }

    function renderPassRateTable(title, rows, emptyText) {
      return `
        <div class="panel">
          <h2>${esc(title)}</h2>
          ${renderTable(
            rows || [],
            [
              { label: '구분', key: 'key' },
              { label: '후보 수', render: (row) => String(row.candidates ?? 0) },
              { label: '통과', render: (row) => String(row.accepted ?? 0) },
              { label: '차단', render: (row) => String(row.blocked ?? 0) },
              { label: '통과율', render: (row) => fmtPercent(row.pass_rate) },
              { label: '평균 EV', render: (row) => fmtR(row.avg_expected_ev_r) },
              { label: '평균 승률', render: (row) => fmtPercent(row.avg_expected_win_prob) },
              { label: '평균 리스크', render: (row) => fmtR(row.avg_recommended_risk_r) },
            ],
            emptyText
          )}
        </div>
      `;
    }

    function renderBottleneckTable(title, rows, emptyText) {
      return `
        <div class="panel">
          <h2>${esc(title)}</h2>
          ${renderTable(
            rows || [],
            [
              { label: '구분', key: 'key' },
              { label: '후보 수', render: (row) => String(row.candidates ?? 0) },
              { label: '통과율', render: (row) => fmtPercent(row.pass_rate) },
              { label: '평균 EV', render: (row) => fmtR(row.avg_expected_ev_r) },
              { label: '평균 승률', render: (row) => fmtPercent(row.avg_expected_win_prob) },
            ],
            emptyText
          )}
        </div>
      `;
    }

    function renderSofteningPriorityTable(rows, emptyText) {
      return `
        <div class="panel">
          <h2>완화 우선순위</h2>
          <div class="desc">Quality gate에 해당하는 차단만 대상으로, 어디서 softening 효과가 클지 reason / family / regime / session 기준으로 요약합니다.</div>
          ${renderTable(
            rows || [],
            [
              { label: '사유', key: 'reason' },
              { label: '차단 수', render: (row) => String(row.blocked ?? 0) },
              { label: '대표 Family', key: 'top_family' },
              { label: '대표 Regime', key: 'top_regime' },
              { label: '대표 Session', key: 'top_session' },
              { label: '평균 EV', render: (row) => fmtR(row.avg_expected_ev_r) },
              { label: '평균 승률', render: (row) => fmtPercent(row.avg_expected_win_prob) },
            ],
            emptyText
          )}
        </div>
      `;
    }

    function renderResearchFocusAlignment(alignment, emptyText) {
      const rows = alignment?.focus_items || [];
      return `
        <div class="panel">
          <h2>연구 우선 포커스</h2>
          <div class="desc">Validation decomposition과 alpha research near-miss backlog를 연결해, 지금 먼저 shadow research를 돌릴 축을 보여줍니다.</div>
          <div class="summary-grid">
            ${renderSummaryBox('분석 심볼', alignment?.analysis_symbol || 'n/a', '현재 연구 우선순위 기준 심볼')}
            ${renderSummaryBox('정렬된 후보', String(alignment?.aligned_candidate_count ?? 0), 'focus와 실제 alpha research 후보가 겹치는 수')}
            ${renderSummaryBox('대표 포커스', alignment?.top_focus || 'n/a', alignment?.top_bucket || '')}
            ${renderSummaryBox('전체 research 후보', String(alignment?.alpha_research_candidate_count ?? 0), 'quality near-miss backlog 기준')}
          </div>
          ${renderTable(
            rows,
            [
              { label: '포커스', key: 'focus' },
              { label: '버킷', key: 'bucket' },
              { label: '후보 수', render: (row) => String(row.candidates ?? 0) },
              { label: '지표', key: 'metric' },
              { label: '값', render: (row) => fmtMaybe(row.value == null ? 'n/a' : Number(row.value).toFixed(4)) },
              { label: '대표 사유', key: 'top_reason' },
              { label: '대표 심볼', key: 'top_symbol' },
            ],
            emptyText
          )}
        </div>
      `;
    }

    function renderResearchActionPanel(actionPayload, emptyText) {
      const summary = actionPayload || {};
      const rows = summary?.recommended_actions || [];
      return `
        <div class="panel">
          <h2>추천 연구 액션</h2>
          <div class="desc">이 섹션은 승인 변경이 아니라 shadow research 순서를 안내합니다. hard gate와 live approval은 그대로 유지됩니다.</div>
          <div class="summary-grid">
            ${renderSummaryBox('분석 심볼', summary?.analysis_symbol || 'n/a', '현재 추천 액션 기준 심볼')}
            ${renderSummaryBox('지금 할 일', summary?.recommended_action || 'n/a', summary?.recommended_reason || '')}
            ${renderSummaryBox('연구 범위', summary?.recommended_scope || 'n/a', summary?.bucket || '')}
            ${renderSummaryBox('포커스', summary?.focus || 'n/a', summary?.shadow_experiment_type || '')}
            ${renderSummaryBox('정렬된 후보', String(summary?.aligned_candidates ?? 0), '추천 액션과 실제 backlog가 겹치는 수')}
            ${renderSummaryBox('신뢰도', summary?.confidence || 'n/a', summary?.sample_note || '')}
          </div>
          ${renderTable(
            rows,
            [
              { label: '액션', key: 'recommended_action' },
              { label: '범위', key: 'recommended_scope' },
              { label: '버킷', key: 'bucket' },
              { label: '이유', key: 'recommended_reason' },
              { label: '신뢰도', key: 'confidence' },
              { label: '정렬 후보', render: (row) => String(row.aligned_candidates ?? 0) },
              { label: '관찰 지표', render: (row) => (row.observe_metrics || []).join(', ') },
              { label: '승격 금지 조건', render: (row) => (row.promotion_guardrails || []).join(', ') },
            ],
            emptyText
          )}
        </div>
      `;
    }

    function renderShadowExperimentPanel(experimentPayload, emptyText) {
      const summary = experimentPayload || {};
      const rows = summary?.shadow_experiment_templates || [];
      return `
        <div class="panel">
          <h2>권장 Shadow Experiment</h2>
          <div class="desc">이 섹션은 자동 실행이 아니라, operator가 다음으로 돌릴 shadow experiment 절차와 관찰 기준을 보여줍니다.</div>
          <div class="summary-grid">
            ${renderSummaryBox('분석 심볼', summary?.analysis_symbol || 'n/a', '현재 실험 추천 기준 심볼')}
            ${renderSummaryBox('실험', summary?.title || 'n/a', summary?.experiment_id || '')}
            ${renderSummaryBox('대상', summary?.target || 'n/a', summary?.objective || '')}
            ${renderSummaryBox('연결 액션', summary?.recommended_action || 'n/a', summary?.recommended_scope || '')}
            ${renderSummaryBox('포커스', summary?.focus || 'n/a', summary?.bucket || '')}
            ${renderSummaryBox('신뢰도', summary?.confidence || 'n/a', summary?.sample_note || '')}
          </div>
          ${renderTable(
            rows,
            [
              { label: '실험', key: 'title' },
              { label: 'ID', key: 'experiment_id' },
              { label: '대상', key: 'target' },
              { label: '연결 액션', key: 'recommended_action' },
              { label: '관찰 지표', render: (row) => (row.observe_metrics || []).join(', ') },
              { label: '성공 기준', render: (row) => (row.success_criteria || []).join(', ') },
              { label: '중단 조건', render: (row) => (row.stop_conditions || []).join(', ') },
            ],
            emptyText
          )}
        </div>
      `;
    }

    function renderSignalFunnel(dashboard, validation) {
      const funnel = dashboard.signal_funnel || {};
      const runtimeCandidates = funnel.runtime_candidates ?? 0;
      const acceptedCandidates = funnel.accepted_candidates ?? 0;
      const blockedCandidates = funnel.blocked_candidates ?? 0;
      const passRate = runtimeCandidates > 0 ? acceptedCandidates / runtimeCandidates : 0;
      const blockedReasonCounts = funnel.blocked_reason_counts || {};
      const blockedGateGroupCounts = funnel.blocked_gate_group_counts || {};
      const blockedGateGroups = funnel.blocked_gate_groups || [];
      const hardBlockSummary = funnel.hard_block_summary || {};
      const softeningSummary = funnel.softening_candidate_summary || {};
      const rolloutBlockSummary = funnel.rollout_block_summary || {};
      const qualitySofteningPriorities = funnel.quality_softening_priorities || [];
      const familyBottlenecks = funnel.family_bottlenecks || [];
      const regimeBottlenecks = funnel.regime_bottlenecks || [];
      const sessionBottlenecks = funnel.session_bottlenecks || [];
      const alphaResearchFocusAlignment = funnel.alpha_research_focus_alignment
        || validation?.alpha_research_pipeline?.research_focus_alignment
        || null;
      const alphaResearchRecommendedAction = funnel.alpha_research_recommended_action
        || (
          validation?.alpha_research_pipeline
            ? {
                ...validation.alpha_research_pipeline.recommended_action_summary,
                recommended_actions: validation.alpha_research_pipeline.recommended_actions || [],
              }
            : null
        );
      const alphaResearchTopShadowExperiment = funnel.alpha_research_top_shadow_experiment
        || (
          validation?.alpha_research_pipeline
            ? {
                ...validation.alpha_research_pipeline.top_shadow_experiment,
                shadow_experiment_templates: validation.alpha_research_pipeline.shadow_experiment_templates || [],
              }
            : null
        );
      const currentEntryGateGroup = funnel.current_entry_gate_group || 'unknown';
      const currentEntryGateReason = funnel.current_entry_gate_reason || '현재 신규 진입 차단 사유가 없습니다.';
      const topBlockedReason = Object.entries(blockedReasonCounts)
        .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))[0];
      const topBlockedGateGroup = Object.entries(blockedGateGroupCounts)
        .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))[0];
      const submitDecisionCounts = funnel.submit_decision_counts || {};
      const topSubmitDecision = Object.entries(submitDecisionCounts)
        .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))[0];

      $('signal-funnel').innerHTML = `
        <div class="desk-strip">${badge('기간 필터 적용', `최근 ${dashboard.report_window_days || $('days').value || 7}일`)}</div>
        <div class="summary-grid">
          ${renderSummaryBox('Runtime 후보', String(runtimeCandidates), 'portfolio overlay 직전/직후 기준 후보 수')}
          ${renderSummaryBox('통과 후보', String(acceptedCandidates), '현재 스캐너에서 살아남은 후보')}
          ${renderSummaryBox('차단 후보', String(blockedCandidates), 'runtime gate에서 걸러진 후보')}
          ${renderSummaryBox('통과율', fmtPercent(passRate), 'accepted / runtime candidates')}
          ${renderSummaryBox('최근 Intent', String(funnel.recent_intents ?? 0), '최근 일수 기준')}
          ${renderSummaryBox('열린 주문 / 포지션', `${funnel.open_orders ?? 0} / ${funnel.open_positions ?? 0}`, '활성 상태는 기간 필터 제외')}
        </div>
        <div class="hero-grid">
          <div class="hint-card">
            <div class="title">가장 많이 막는 이유</div>
            <div class="body">${esc(topBlockedReason ? `${topBlockedReason[0]} (${topBlockedReason[1]})` : '현재 차단 이유 집계가 없습니다.')}</div>
          </div>
          <div class="hint-card">
            <div class="title">가장 많이 막는 게이트 유형</div>
            <div class="body">${esc(topBlockedGateGroup ? `${topBlockedGateGroup[0]} (${topBlockedGateGroup[1]})` : '현재 게이트 유형 집계가 없습니다.')}</div>
          </div>
          <div class="hint-card">
            <div class="title">가장 많은 Intent 결정</div>
            <div class="body">${esc(topSubmitDecision ? `${topSubmitDecision[0]} (${topSubmitDecision[1]})` : '최근 intent 집계가 없습니다.')}</div>
          </div>
          <div class="hint-card">
            <div class="title">현재 신규 진입 차단 유형</div>
            <div class="body">${esc(`${currentEntryGateGroup} · ${currentEntryGateReason}`)}</div>
          </div>
          <div class="hint-card">
            <div class="title">유지해야 하는 hard gate</div>
            <div class="body">${esc(hardBlockSummary.top_reason ? `${hardBlockSummary.top_reason} (${hardBlockSummary.top_reason_count})` : '현재 safety/structural 차단이 없습니다.')}</div>
          </div>
          <div class="hint-card">
            <div class="title">완화 검토 1순위</div>
            <div class="body">${esc(softeningSummary.top_reason ? `${softeningSummary.top_reason} (${softeningSummary.top_reason_count})` : '현재 quality softening 후보가 없습니다.')}</div>
          </div>
        </div>
        <div class="panel">
          <h2>게이트 유형별 차단</h2>
          <div class="desc">Safety / Structural은 유지 대상, Quality는 softening 후보, Rollout은 운영 정책 차단입니다.</div>
          ${renderTable(
            blockedGateGroups,
            [
              { label: '유형', key: 'key' },
              { label: '차단 수', render: (row) => String(row.blocked ?? 0) },
              { label: 'runtime 후보 대비 비중', render: (row) => fmtPercent(row.share_of_runtime_candidates) },
            ],
            '현재 게이트 유형 집계가 없습니다.'
          )}
        </div>
        <div class="grid three">
          ${renderGateReasonSummary('유지해야 하는 hard gate', hardBlockSummary, 'Safety / Structural에 해당하는 차단은 softening 대상이 아닙니다.')}
          ${renderGateReasonSummary('완화 검토 후보', softeningSummary, 'Quality gate만 softening 후보로 검토합니다.')}
          ${renderGateReasonSummary('운영 정책 차단', rolloutBlockSummary, 'Rollout은 품질 문제가 아니라 현재 운영 정책 제한입니다.')}
        </div>
        ${renderResearchFocusAlignment(alphaResearchFocusAlignment, '현재 decomposition과 맞물린 alpha research focus가 없습니다.')}
        ${renderResearchActionPanel(alphaResearchRecommendedAction, '현재 바로 실행할 research action이 없습니다.')}
        ${renderShadowExperimentPanel(alphaResearchTopShadowExperiment, '현재 바로 실행할 shadow experiment가 없습니다.')}
        ${renderSofteningPriorityTable(qualitySofteningPriorities, '현재 quality softening priority가 없습니다.')}
        <div class="grid three">
          ${renderPassRateTable('Family 통과율', funnel.family_pass_rates, 'family 기준 집계가 없습니다.')}
          ${renderPassRateTable('Regime 통과율', funnel.regime_pass_rates, 'regime 기준 집계가 없습니다.')}
          ${renderPassRateTable('Session 통과율', funnel.session_pass_rates, 'session 기준 집계가 없습니다.')}
        </div>
        <div class="grid three">
          ${renderBottleneckTable('Family 병목 상위', familyBottlenecks, 'family 병목 집계가 없습니다.')}
          ${renderBottleneckTable('Regime 병목 상위', regimeBottlenecks, 'regime 병목 집계가 없습니다.')}
          ${renderBottleneckTable('Session 병목 상위', sessionBottlenecks, 'session 병목 집계가 없습니다.')}
        </div>
      `;
    }

    function renderGateReasonSummary(title, summary, description) {
      const rows = Object.entries(summary.reason_counts || {}).map(([key, value]) => ({
        key,
        blocked: value,
      })).sort((a, b) => Number(b.blocked || 0) - Number(a.blocked || 0));

      return `
        <div class="panel">
          <h2>${esc(title)}</h2>
          <div class="desc">${esc(description)}</div>
          <div class="summary-grid">
            ${renderSummaryBox('차단 수', String(summary.blocked ?? 0), 'runtime 후보 기준')}
            ${renderSummaryBox('비중', fmtPercent(summary.share_of_runtime_candidates), 'runtime 후보 대비')}
          </div>
          ${renderTable(
            rows,
            [
              { label: '사유', key: 'key' },
              { label: '차단 수', render: (row) => String(row.blocked ?? 0) },
            ],
            '현재 집계가 없습니다.'
          )}
        </div>
      `;
    }

    function renderTable(rows, columns, emptyText) {
      if (!rows || rows.length === 0) return `<div class="empty">${esc(emptyText)}</div>`;
      const head = `<tr>${columns.map((c) => `<th>${esc(c.label)}</th>`).join('')}</tr>`;
      const body = rows.map((row) => `<tr>${columns.map((c) => `<td>${esc(c.render ? c.render(row) : row[c.key])}</td>`).join('')}</tr>`).join('');
      return `<div class="table-wrap"><table><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
    }

    function fileHref(path) {
      const value = String(path || '').trim();
      if (!value) return '';
      return `file://${encodeURI(value)}`;
    }

    function renderFileHint(label, path, endpoint) {
      const value = String(path || '').trim();
      if (!value) {
        return `
          <div class="hint-card">
            <div class="title">${esc(label)}</div>
            <div class="body">${esc(`${endpoint} 기준으로 아직 생성된 report path가 없습니다.`)}</div>
          </div>
        `;
      }
      return `
        <div class="hint-card">
          <div class="title">${esc(label)}</div>
          <div class="body"><a href="${fileHref(value)}" target="_blank" rel="noreferrer">파일 열기</a></div>
          <div class="meta" style="margin-top:8px;">${esc(value)}</div>
          <div class="meta">${esc(`source=${endpoint}`)}</div>
        </div>
      `;
    }

    function renderTopPlan(plan) {
      if (!plan) {
        $('top-plan').innerHTML = '<div class="empty">활성 플랜이 없습니다.</div>';
        return;
      }
      const recommendedRisk = plan.validity?.recommended_risk_r;
      $('top-plan').innerHTML = `
        <div class="desk-strip">${badge('Plan', plan.plan_id)} ${badge('방향', plan.direction)} ${badge('모델', plan.entry_model)}</div>
        <div class="price-line">
          <div class="price-chip"><strong>진입</strong>${esc(fmtPrice(plan.entry_price))}</div>
          <div class="price-chip"><strong>손절</strong>${esc(fmtPrice(plan.sl))}</div>
          <div class="price-chip"><strong>TP1</strong>${esc(fmtPrice(plan.tp1))}</div>
          <div class="price-chip"><strong>TP2</strong>${esc(fmtPrice(plan.tp2))}</div>
          <div class="price-chip"><strong>TP3</strong>${esc(fmtPrice(plan.tp3))}</div>
        </div>
        <div class="hero-grid">
          <div class="hero-stat">
            <div class="label">Est. win</div>
            <div class="value">${esc(fmtPercent(plan.expected_win_prob))}</div>
            <div class="subvalue">차트가 아니라 서버 플랜 기준 추정치</div>
          </div>
          <div class="hero-stat">
            <div class="label">Est. EV</div>
            <div class="value">${esc(fmtR(plan.expected_ev_r))}</div>
            <div class="subvalue">비용 반영 기대값</div>
          </div>
          <div class="hero-stat">
            <div class="label">권장 리스크</div>
            <div class="value">${esc(fmtR(recommendedRisk))}</div>
            <div class="subvalue">엔진 size 권장치</div>
          </div>
          <div class="hero-stat">
            <div class="label">손익비</div>
            <div class="value">${esc(fmtMaybe(plan.rr_base == null ? 'n/a' : plan.rr_base.toFixed(2)))}</div>
            <div class="subvalue">base RR / opt=${esc(fmtMaybe(plan.rr_opt == null ? 'n/a' : plan.rr_opt.toFixed(2)))}</div>
          </div>
        </div>
        <div class="prob-grid">
          <div class="prob-box">
            <div class="label">TP1 도달 확률</div>
            <div class="value">${esc(fmtPercent(plan.expected_tp1_prob))}</div>
          </div>
          <div class="prob-box">
            <div class="label">TP2 도달 확률</div>
            <div class="value">${esc(fmtPercent(plan.expected_tp2_prob))}</div>
          </div>
          <div class="prob-box">
            <div class="label">TP3 도달 확률</div>
            <div class="value">${esc(fmtPercent(plan.expected_tp3_prob))}</div>
          </div>
        </div>
        <div class="hint-card">
          <div class="title">대표 플랜 요약</div>
          <div class="body">${esc(plan.expected_summary || '요약 없음')}</div>
        </div>
      `;
    }

    function renderTopCandidate(candidate, symbol) {
      if (!candidate) {
        $('top-candidate').innerHTML = `<div class="empty">${esc(symbol)} 기준으로 실행 가능한 스캐너 후보가 없습니다.</div>`;
        return;
      }
      const candidateCluster = candidate?.strategy_cluster || candidate?.multi_strategy_overlay?.cluster || 'n/a';
      const candidateClusterStatus = candidate?.strategy_cluster_status
        || candidate?.multi_strategy_overlay?.strategy_cluster_status
        || 'n/a';
      const candidateABSummary = candidate?.strategy_cluster_balance?.summary
        || candidate?.b_continuation_activation?.summary
        || candidate?.multi_strategy_overlay?.summary
        || '현재 row-level A/B posture summary가 없습니다.';
      const candidateSource = candidate.symbol === symbol ? '현재 심볼 기준 후보' : `현재 심볼 후보 없음, 전체 상위 후보=${candidate.symbol}`;
      $('top-candidate').innerHTML = `
        <div>${badge('후보', candidate.symbol)} ${badge('상태', candidate.deployment_go_no_go || candidate.operator_status || 'n/a')} ${badge('Family', candidate.strategy_family || 'n/a')} ${badge('Cluster', candidateCluster)}</div>
        <div class="kv"><div class="k">방향 / 모델</div><div class="v">${esc(`${fmtMaybe(candidate.direction)} / ${fmtMaybe(candidate.entry_model)}`)}</div></div>
        <div class="kv"><div class="k">왜 지금</div><div class="v">${esc(fmtMaybe(candidate.why_now))}</div></div>
        <div class="kv"><div class="k">허용 / 차단 이유</div><div class="v">${esc(fmtMaybe(candidate.block_reason_message || candidate.deployment_message))}</div></div>
        <div class="kv"><div class="k">추정 승률 / EV</div><div class="v">${esc(`${fmtPercent(candidate.expected_win_prob)} / ${fmtR(candidate.expected_ev_r)}`)}</div></div>
        <div class="kv"><div class="k">권장 리스크</div><div class="v">${esc(fmtR(candidate.recommended_risk_r))}</div></div>
        <div class="kv"><div class="k">A/B posture</div><div class="v">${esc(`${candidateClusterStatus} / ${candidateABSummary}`)}</div></div>
        <div class="meta">${esc(candidateSource)}</div>
      `;
    }

    function renderEntryGuide(plan, candidate) {
      const guidePlan = plan || candidate;
      if (!guidePlan) {
        $('entry-guide').innerHTML = '<div class="empty">현재 보여줄 진입 가이드가 없습니다.</div>';
        return;
      }
      const entry = guidePlan.entry_price;
      const stop = guidePlan.sl;
      const tp1 = guidePlan.tp1;
      $('entry-guide').innerHTML = `
        <div class="strong-line">${esc(guidePlan.entry_condition || '진입 조건 설명 없음')}</div>
        <div class="price-line">
          <div class="price-chip"><strong>Mirror entry</strong>${esc(fmtPrice(entry))}</div>
          <div class="price-chip"><strong>Mirror stop</strong>${esc(fmtPrice(stop))}</div>
          <div class="price-chip"><strong>TP1</strong>${esc(fmtPrice(tp1))}</div>
        </div>
        <div class="hero-grid">
          <div class="hero-stat">
            <div class="label">예상 수익</div>
            <div class="value">${esc(fmtR(guidePlan.expected_ev_at_recommended_size_r))}</div>
            <div class="subvalue">권장 size 반영 기대값</div>
          </div>
          <div class="hero-stat">
            <div class="label">추정 승률</div>
            <div class="value">${esc(fmtPercent(guidePlan.expected_win_prob))}</div>
            <div class="subvalue">현재 대표 가이드 기준</div>
          </div>
          <div class="hero-stat">
            <div class="label">손익비</div>
            <div class="value">${esc(fmtMaybe(guidePlan.rr_base == null ? 'n/a' : guidePlan.rr_base.toFixed(2)))}</div>
            <div class="subvalue">기본 손익비</div>
          </div>
        </div>
        <div class="prob-grid">
          <div class="prob-box">
            <div class="label">TP1</div>
            <div class="value">${esc(fmtPercent(guidePlan.expected_tp1_prob))}</div>
          </div>
          <div class="prob-box">
            <div class="label">TP2</div>
            <div class="value">${esc(fmtPercent(guidePlan.expected_tp2_prob))}</div>
          </div>
          <div class="prob-box">
            <div class="label">TP3</div>
            <div class="value">${esc(fmtPercent(guidePlan.expected_tp3_prob))}</div>
          </div>
        </div>
        <div class="hint-card">
          <div class="title">허용 / 차단 이유</div>
          <div class="body">${esc(guidePlan.block_reason_message || guidePlan.expected_summary || '대표 플랜 기준 가이드입니다.')}</div>
        </div>
      `;
    }

    function renderIntents(dashboard) {
      const recentWindow = `최근 ${dashboard.report_window_days || $('days').value || 7}일 기준 목록입니다.`;
      const tableHtml = renderTable(
        dashboard.recent_intents || [],
        [
          { label: 'Plan', key: 'plan_id' },
          { label: 'Family', key: 'strategy_family' },
          { label: '결정', render: (row) => `${row.submit_decision} / ${row.decision_reason_code}` },
          { label: '배포', key: 'deployment_go_no_go' },
          { label: '플레이북', key: 'playbook_action' },
          { label: '시각', key: 'created_at' },
        ],
        '최근 intent가 없습니다.'
      );
      $('intents').innerHTML = `
        <div class="desk-strip">${badge('기간 필터 적용', recentWindow)}</div>
        <div class="meta">이 목록은 입력한 최근 일수 기준으로만 잘라서 보여줍니다.</div>
        <div>${tableHtml}</div>
      `;
    }

    function renderOrdersPositions(dashboard) {
      const ordersHtml = renderTable(
        dashboard.open_orders || [],
        [
          { label: '심볼', key: 'symbol' },
          { label: '상태', key: 'state' },
          { label: '어댑터', key: 'adapter' },
          { label: 'Client Order', key: 'client_order_id' },
          { label: '제출 시각', key: 'submitted_at' },
        ],
        '열린 주문이 없습니다.'
      );
      const positionsHtml = renderTable(
        dashboard.open_positions || [],
        [
          { label: '심볼', key: 'symbol' },
          { label: '방향', key: 'position_side' },
          { label: '수량', key: 'position_amt' },
          { label: '진입가', key: 'entry_price' },
          { label: '미실현 PnL', key: 'unrealized_pnl' },
        ],
        '열린 포지션이 없습니다.'
      );
      $('orders-positions').innerHTML = `
        <div class="desk-strip">${badge('기간 필터 제외', '활성 상태')}</div>
        <div class="meta">열린 주문과 열린 포지션은 운영상 중요하므로 최근 일수와 무관하게 항상 표시합니다.</div>
        <div>${ordersHtml}</div>
        <div>${positionsHtml}</div>
      `;
    }

    function renderLocks(dashboard) {
      const locks = dashboard.active_locks || [];
      const policies = dashboard.rollout_policies || [];
      const locksHtml = renderTable(locks, [
          { label: '범위', render: (row) => `${row.scope_type}:${row.scope_key || '*'}` },
          { label: '심각도', key: 'severity' },
          { label: '이유 코드', key: 'reason_code' },
          { label: '메시지', key: 'reason_message' },
        ], '활성 락이 없습니다.');
      const policiesHtml = renderTable(policies, [
          { label: 'Family', key: 'strategy_family' },
          { label: 'Live 허용', key: 'live_enabled' },
          { label: '최대 모드', key: 'max_execution_mode' },
          { label: '최대 리스크', key: 'max_risk_r' },
          { label: '허용 세션', render: (row) => (row.allowed_sessions || []).join(', ') },
        ], '롤아웃 정책이 없습니다.');
      $('locks').innerHTML = `
        <div class="desk-strip">${badge('기간 필터 제외', '활성 상태')}</div>
        <div class="meta">활성 락과 롤아웃 정책은 현재 운용 규칙이므로 최근 일수와 무관하게 항상 표시합니다.</div>
        <div>${locksHtml}</div>
        <div>${policiesHtml}</div>
      `;
    }

    function renderReconcile(dashboard) {
      const summary = dashboard.recent_reconciliation_summary || {};
      const events = dashboard.recent_reconciliation_events || [];
      $('reconcile').innerHTML = `
        <div class="desk-strip">${badge('기간 필터 적용', `최근 ${dashboard.report_window_days || $('days').value || 7}일`)}</div>
        <div>${badge('정상 여부', summary.healthy ? 'true' : 'false')} ${badge('최고 심각도', summary.highest_severity || 'INFO')}</div>
        <div class="meta">critical=${summary.critical_count || 0} / lockRequired=${summary.lock_required_count || 0}</div>
        <div>${renderTable(events, [
          { label: '심볼', key: 'symbol' },
          { label: '유형', key: 'mismatch_type' },
          { label: '심각도', key: 'severity' },
          { label: '락 필요', render: (row) => row.lock_required ? '필요' : '아니오' },
          { label: '메시지', key: 'message' },
        ], '리컨실리에이션 이벤트가 없습니다.')}</div>
      `;
    }

    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      const text = await response.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
      if (!response.ok) throw new Error(`${response.status} ${url} ${JSON.stringify(data)}`);
      return data;
    }

    async function refresh() {
      const symbol = $('symbol').value.trim();
      const universe = $('universe').value.trim() || 'usdc_perp_top30';
      const days = Math.max(parseInt($('days').value || '7', 10), 1);
      $('status').textContent = '운영 화면 데이터를 불러오는 중...';
      const dashboardUrl = `/execution/operator-dashboard?symbol=${encodeURIComponent(symbol)}&universe=${encodeURIComponent(universe)}&portfolio_limit=10&intent_limit=10&reconcile_limit=10&days=${days}`;
      const plansUrl = `/plans/top?symbol=${encodeURIComponent(symbol)}&tf=5m&limit=5&refresh=true`;
      const scannerUrl = `/scanner/top?universe=${encodeURIComponent(universe)}&limit=50`;
      try {
        const [dashboard, checklist, validation, plans, scannerRows] = await Promise.all([
          fetchJson(dashboardUrl),
          fetchJson(`/operations/checklist?symbol=${encodeURIComponent(symbol)}`, { method: 'POST' }),
          fetchJson(`/validation/report?symbol=${encodeURIComponent(symbol)}`, { method: 'POST' }),
          fetchJson(plansUrl),
          fetchJson(scannerUrl),
        ]);
        const plan = firstPlan(plans);
        const candidate = pickCandidate(scannerRows, symbol);
        renderDecisionSummary(dashboard, checklist, validation);
        renderApprovalDivergenceBanner(dashboard, checklist, validation, candidate);
        renderTopOpportunity(candidate, symbol);
        renderTopBlocker(dashboard);
        renderCurrentOperatingState(dashboard, checklist, validation);
        renderStrategyABPosture(dashboard, candidate);
        renderPromotionOperatingStack(dashboard);
        renderPromotionCaseInspector(dashboard);
        renderValidationChecklistReviewStack(validation, checklist);
        renderValidationCaseInspector(validation);
        renderRuntimeQualityInspector(dashboard);
        renderSignalFunnelInspector(dashboard);
        renderAlphaResearchInspector(dashboard);
        renderKillConditionInspector(dashboard);
        renderPolicyLockInspector(dashboard);
        renderIntentExposureInspector(dashboard);
        renderModeDeploymentInspector(dashboard, checklist, validation);
        renderApprovalAlignmentInspector(dashboard, checklist, validation, candidate);
        renderDataFreshnessSourceInspector(dashboard, checklist, validation);
        renderPortfolioCandidateDrilldown(dashboard);
        renderPortfolioCandidateInspector(dashboard);
        renderChecklistEvidenceDrilldown(checklist);
        renderReportNavigation(dashboard, checklist, validation);
        renderOverview(symbol, dashboard, checklist, validation, plan, candidate);
        renderCards(dashboard, plan, candidate);
        renderCandidateList(scannerRows, symbol);
        renderPlanList(plans);
        renderSignalFunnel(dashboard, validation);
        renderApproval(checklist, validation);
        renderRuntime(dashboard);
        renderTopPlan(plan);
        renderTopCandidate(candidate, symbol);
        renderEntryGuide(plan, candidate);
        renderIntents(dashboard);
        renderOrdersPositions(dashboard);
        renderLocks(dashboard);
        renderReconcile(dashboard);
        asJson('raw-dashboard', dashboard);
        asJson('raw-checklist', checklist);
        $('status').textContent = '운영 화면 데이터 반영 완료.';
        $('updated').textContent = `업데이트 시각: ${new Date().toLocaleString()}`;
      } catch (error) {
        $('status').textContent = `불러오기 실패: ${error.message}`;
      }
    }

    function initNavigation() {
      const navLinks = Array.from(document.querySelectorAll('.nav-link[data-target]'));
      const sectionIds = navLinks.map((link) => link.dataset.target).filter(Boolean);
      const sections = sectionIds
        .map((id) => document.getElementById(id))
        .filter(Boolean);

      function setActive(targetId) {
        navLinks.forEach((link) => {
          link.classList.toggle('active', link.dataset.target === targetId);
        });
      }

      navLinks.forEach((link) => {
        link.addEventListener('click', () => {
          const targetId = link.dataset.target;
          const target = targetId ? document.getElementById(targetId) : null;
          if (!target) return;
          setActive(targetId);
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      });

      if (sections.length === 0) return;

      const observer = new IntersectionObserver(
        (entries) => {
          const visible = entries
            .filter((entry) => entry.isIntersecting)
            .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
          if (visible.length > 0) {
            setActive(visible[0].target.id);
          }
        },
        {
          root: null,
          rootMargin: '-120px 0px -55% 0px',
          threshold: [0.15, 0.35, 0.6],
        }
      );

      sections.forEach((section) => observer.observe(section));
      setActive(sections[0].id);
    }

    $('refresh').addEventListener('click', refresh);
    $('autorefresh').addEventListener('change', (event) => {
      if (timer) clearInterval(timer);
      if (event.target.checked) timer = setInterval(refresh, 30000);
    });
    initNavigation();
    refresh();
  </script>
</body>
</html>"""
    return (
        template.replace("__DEFAULT_SYMBOL__", default_symbol)
        .replace("__DEFAULT_UNIVERSE__", default_universe)
        .replace("__DEFAULT_DAYS__", str(default_days))
    )
