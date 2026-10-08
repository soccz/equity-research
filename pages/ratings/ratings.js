/* The monthly ratings page. Reads only files deployed next to it: data/index.json
   (state, months, gates, evaluation), data/<month>.json (compact rows) and
   glossary.ko.json. Stored labels are shown as registered; nothing is recomputed. */
(function () {
  "use strict";

  var LABELS = ["선호", "관찰", "회피"];
  var MARKETS = { US: { name: "미국", zone: "America/New_York" }, KR: { name: "한국", zone: "Asia/Seoul" } };
  var PAGE_SIZE = 100;
  var GATE_WAIT_DAYS = 3; // the operation may record a gate up to three days after its date
  var GATE_LOST_DAYS = 8; // a gate part not captured by then never will be (its five-session window)
  var TENTATIVE_PERIODS = 12; // fewer completed periods than this: shown as tentative
  var LEDGER_URL = "https://github.com/soccz/equity-research/tree/main/data/ratings";
  var MOBILE = window.matchMedia("(max-width: 600px)");
  var state = { index: null, glossary: null, month: null, view: null, rows: [], previous: null, previousMonths: {},
    previousError: null, shown: PAGE_SIZE, market: "ALL", label: "ALL", sector: "ALL", sort: "percentile", query: "", token: 0 };

  function h(tag, attrs) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "text") node.textContent = value;
      else if (key === "class") node.className = value;
      else if (key.slice(0, 2) === "on") node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    });
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child === null || child === undefined || child === false) continue;
      if (Array.isArray(child)) child.forEach(function (c) { if (c) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
      else node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }
  function $(id) { return document.getElementById(id); }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

  function localDay(market) {
    return new Intl.DateTimeFormat("en-CA", { timeZone: MARKETS[market].zone, year: "numeric", month: "2-digit", day: "2-digit" })
      .format(new Date()).slice(0, 10);
  }
  function addDays(day, n) {
    var d = new Date(day + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function kst(iso) {
    if (!iso) return "–";
    var text = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(iso));
    return text.replace(",", "") + " KST";
  }
  function pct(value, digits) {
    if (value === null || value === undefined) return "–";
    return (value * 100).toFixed(digits === undefined ? 1 : digits) + "%";
  }
  function signed(value, digits) {
    if (value === null || value === undefined) return "–";
    var text = (value * 100).toFixed(digits === undefined ? 2 : digits) + "%p";
    return value > 0 ? "+" + text : text;
  }
  function num(value, digits) { return value === null || value === undefined ? "–" : Number(value).toFixed(digits); }
  function money(value, currency) {
    if (value === null || value === undefined) return "–";
    try {
      return new Intl.NumberFormat("ko-KR", { notation: "compact", style: "currency", currency: currency || "USD", maximumFractionDigits: 1 }).format(value);
    } catch (e) { return String(value); }
  }
  function price(value, currency) {
    if (value === null || value === undefined) return "–";
    try {
      return new Intl.NumberFormat("ko-KR", { style: "currency", currency: currency || "USD", maximumFractionDigits: currency === "KRW" ? 0 : 2 }).format(value);
    } catch (e) { return String(value); }
  }
  function short(hash) { return hash ? String(hash).slice(0, 12) : "–"; }
  function displayName(r) {
    // SEC registrant names carry state suffixes such as " /DE/" or " /NEW"; the page drops them.
    return String(r.name || r.id).replace(/\s*\/(?:[A-Z]{2,4})?\/?\s*$/, "");
  }
  function currencyOf(r) { return r.currency || marketCurrency(r); }  // filing currency
  function marketCurrency(r) { return r.market === "KR" ? "KRW" : "USD"; }

  function fetchJson(path) {
    return fetch(path, { cache: "no-cache" }).then(function (response) {
      if (!response.ok) throw new Error(path + ": HTTP " + response.status);
      return response.json();
    });
  }

  function badge(label, reason) {
    if (label === "선호") return h("span", { class: "badge prefer", text: "선호" });
    if (label === "관찰") return h("span", { class: "badge watch", text: "관찰" });
    if (label === "회피") return h("span", { class: "badge avoid", text: "회피" });
    return h("span", { class: "badge none", text: reason === "excluded" ? "금융 제외" : "자료 부족" });
  }
  function issueText(code) {
    var g = state.glossary || {};
    return (g.issues && g.issues[code]) || (g.periods && g.periods[code]) || "설명 미등록: " + code;
  }
  function issuePill(code) {
    var g = state.glossary || {}, info = (g.issueInfo || []).indexOf(code) >= 0;
    return h("span", { class: info ? "pill" : "pill caution", title: issueText(code), text: (g.issueShort || {})[code] || code });
  }
  function sectorName(code, long) {
    var entry = ((state.glossary || {}).sectors || {})[code];
    return entry ? entry[long ? 1 : 0] : (code || "–");
  }

  /* ---- state cards ------------------------------------------------------- */
  // A gate whose part was never captured can never be recorded: the market is out of v1
  // once its five-session window has closed, or once a month registered without it.
  function isLost(market, today) {
    var index = state.index, sched = index.schedule || {};
    if ((index.gates || {})[market] || (index.gateParts || {})[market] !== false) return false;
    if (today >= addDays(sched.gateAsOf, GATE_LOST_DAYS)) return true;
    return (index.months || []).some(function (m) { return !m.preview && m.labels && !m.labels[market]; });
  }
  function inV1(market) {
    var gates = state.index.gates || {}, gate = gates[market];
    if ((gates.US || {}).verdict === "fail") return false;
    if (gate) return gate.verdict === "pass";
    return !isLost(market, localDay(market));
  }
  function gateCard(market) {
    var index = state.index, gate = (index.gates || {})[market], sched = index.schedule || {}, states = state.glossary.states;
    var today = localDay(market), card = h("article", { class: "status-card" });
    var title, body, figure = null;
    var threshold = (sched.thresholds || {})[market];
    var lost = isLost(market, today);
    var usFailed = market !== "US" && ((index.gates || {}).US || {}).verdict === "fail";
    var other = market === "US" ? "KR" : "US";
    if (lost) {
      title = "점검 기록 불가 — v1에서 제외"; body = states.gate_lost; card.className += " caution";
      if (inV1(other)) body += " " + states.gate_lost_other;
    } else if (!gate) {
      if (today < sched.gateDate) { title = "계산 가능률 점검 전"; body = states.gate_before; }
      else if (today <= addDays(sched.gateDate, GATE_WAIT_DAYS)) { title = "점검 기록 대기"; body = states.gate_wait; }
      else { title = "점검 미기록"; body = states.gate_unrecorded; card.className += " caution"; }
      if (threshold !== undefined) body += " " + MARKETS[market].name + " 기준 " + pct(threshold, 0) + ".";
    } else {
      var passed = gate.verdict === "pass";
      title = passed ? "계산 가능률 점검 통과" : "계산 가능률 미달";
      figure = pct(gate.rate, 1);
      if (!passed) card.className += " caution";
      body = "신호 2개 이상 " + (gate.computable !== undefined ? gate.computable + "/" + gate.nonFinancial : "") +
        " (기준 " + pct(gate.threshold, 0) + ", 기준일 " + (gate.asOf || sched.gateAsOf) + ", 원장 기록 " + String(gate.recordedAt || "").slice(0, 10) + ")";
      if (!passed) body += " " + states["gate_fail_" + market];
    }
    var months = (index.months || []).filter(function (m) { return !m.preview && m.labels && m.labels[market]; });
    var reg = null;
    if (usFailed) reg = states.us_failed;
    else if (lost) reg = null;
    else if (months.length) {
      var last = months[months.length - 1];
      reg = "최근 등록: " + last.month + " (기준일 " + ((last.asOf || {})[market] || "–") + ", 등록 " + kst(last.registeredAt) + ")";
    } else if (!gate || gate.verdict === "pass") {
      var deadline = addDays(sched.firstAsOf, 7);  // five sessions after T fall within a week (D3)
      if (today <= deadline) reg = states.before_first;
      else { reg = states.first_missing; card.className += " caution"; }
    }
    card.appendChild(h("span", { class: "market", text: market + " · " + MARKETS[market].name }));
    card.appendChild(h("h3", { text: title }));
    if (figure) card.appendChild(h("p", { class: "figure", text: figure }));
    card.appendChild(h("p", { text: body }));
    if (reg) card.appendChild(h("p", { text: reg }));
    card.appendChild(h("p", { text: "현지 날짜 " + today }));
    return card;
  }

  function renderStatus() {
    var box = clear($("status"));
    box.appendChild(gateCard("US"));
    box.appendChild(gateCard("KR"));
  }

  function renderMetadata() {
    var index = state.index, meta = clear($("metadata"));
    meta.appendChild(h("span", null, "프로토콜 ", h("span", { class: "mono", text: short(index.protocol && index.protocol.hash) })));
    meta.appendChild(h("span", { text: index.status === "ledger_invalid" ? "원장 검증 실패" : "원장 이벤트 " + ((index.ledger && index.ledger.events) || 0) + "건" }));
    $("provenance").textContent = "프로토콜 " + short(index.protocol && index.protocol.hash) + " · 원장 머리 " +
      short(index.ledger && index.ledger.head) + " · 내용 지문 " + short(index.contentDigest) + (index.commit ? " · 커밋 " + short(index.commit) : "");
  }

  function renderLegend() {
    var box = clear($("legend")), labels = state.glossary.labels || {};
    LABELS.forEach(function (label) {
      box.appendChild(h("div", null, badge(label), h("span", { text: labels[label] || "" })));
    });
  }

  /* ---- month table ------------------------------------------------------- */
  function rowObjects(view) {
    var cols = view.columns;
    return view.rows.map(function (values) {
      var row = {};
      cols.forEach(function (c, i) { row[c] = values[i]; });
      return row;
    });
  }

  function pressed(box, value) {
    Array.prototype.forEach.call(box.querySelectorAll("button"), function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-value") === value));
    });
  }

  function buildMonthButtons() {
    var box = clear($("month-buttons"));
    (state.index.months || []).slice().reverse().forEach(function (m) {
      box.appendChild(h("button", { type: "button", "data-value": m.month, "aria-pressed": "false",
        text: m.preview ? m.month.replace("-preview", "") + " (미리보기)" : m.month,
        onclick: function () { selectMonth(m.month); } }));
    });
  }

  function buildFilters() {
    var market = clear($("market-filter")), label = clear($("label-filter"));
    [["ALL", "전체"], ["US", "미국"], ["KR", "한국"]].forEach(function (p) {
      market.appendChild(h("button", { type: "button", "data-value": p[0], "aria-pressed": "false", text: p[1],
        onclick: function () { state.market = p[0]; state.shown = PAGE_SIZE; refresh(); } }));
    });
    [["ALL", "전체"], ["선호", "선호"], ["관찰", "관찰"], ["회피", "회피"], ["NONE", "자료 부족"], ["EXCLUDED", "금융 제외"]].forEach(function (p) {
      label.appendChild(h("button", { type: "button", "data-value": p[0], "aria-pressed": "false", text: p[1],
        onclick: function () { state.label = p[0]; state.shown = PAGE_SIZE; refresh(); } }));
    });
  }

  function buildSectors() {
    var sectors = {}, select = clear($("sector-filter"));
    state.rows.forEach(function (r) { if (r.sector) sectors[r.sector] = true; });
    if (state.sector !== "ALL" && !sectors[state.sector]) state.sector = "ALL";
    select.appendChild(h("option", { value: "ALL", text: "전체" }));
    Object.keys(sectors).sort(function (a, b) { return sectorName(a).localeCompare(sectorName(b), "ko"); }).forEach(function (s) {
      select.appendChild(h("option", { value: s, text: sectorName(s), selected: s === state.sector }));
    });
  }

  function labelStrip() {
    var box = clear($("label-strip")), counts = { "선호": 0, "관찰": 0, "회피": 0, "자료 부족": 0, "금융 제외": 0 };
    state.rows.forEach(function (r) {
      if (state.market !== "ALL" && r.market !== state.market) return;
      if (r.label) counts[r.label] += 1;
      else counts[r.labelReason === "excluded" ? "금융 제외" : "자료 부족"] += 1;
    });
    Object.keys(counts).forEach(function (k) { box.appendChild(h("div", null, h("span", { text: k }), h("strong", { text: String(counts[k]) }))); });
  }

  function filtered() {
    var q = state.query.trim().toLowerCase();
    var rows = state.rows.filter(function (r) {
      if (state.market !== "ALL" && r.market !== state.market) return false;
      if (state.sector !== "ALL" && r.sector !== state.sector) return false;
      if (state.label === "NONE" && (r.label || r.labelReason === "excluded")) return false;
      if (state.label === "EXCLUDED" && r.labelReason !== "excluded") return false;
      if (LABELS.indexOf(state.label) >= 0 && r.label !== state.label) return false;
      if (q && displayName(r).toLowerCase().indexOf(q) < 0 && String(r.ticker || "").toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
    var key = state.sort;
    rows.sort(function (a, b) {
      if (key === "name") return displayName(a).localeCompare(displayName(b), "ko");
      if (key === "cap") {  // dollars and won are never compared: by market, then by size
        if (a.market !== b.market) return a.market === "US" ? -1 : 1;
        return (b.marketCap || -1) - (a.marketCap || -1);
      }
      var pa = a.percentile === null ? -1 : a.percentile, pb = b.percentile === null ? -1 : b.percentile;
      return key === "percentile-asc" ? (pa < 0 ? 2 : pa) - (pb < 0 ? 2 : pb) : pb - pa;
    });
    return rows;
  }

  function note(r) {
    var bits = [], reasons = (state.glossary || {}).reasons || {};
    if (r.previousLabel && r.label && r.previousLabel !== r.label) bits.push(h("span", { class: "pill", text: "지난 등록 " + r.previousLabel }));
    if (r.labelReason === "hysteresis") bits.push(h("span", { class: "pill", title: reasons.hysteresis, text: "회전 완화" }));
    var signals = [r.fcfYield, r.cashProfitability, r.momentum12_1].filter(function (v) { return v !== null; }).length;
    if (r.label && signals < 3) bits.push(h("span", { class: "pill", title: "세 신호 중 계산된 신호 수", text: "신호 " + signals + "/3" }));
    (r.issues || []).slice(0, 3).forEach(function (code) { bits.push(issuePill(code)); });
    if ((r.issues || []).length > 3) bits.push(h("span", { class: "pill", text: "+" + (r.issues.length - 3) }));
    return bits;
  }

  function detail(r) {
    var cur = currencyOf(r);
    var dl = h("dl", null,
      h("dt", { text: "종합 점수(z 평균)" }), h("dd", { text: num(r.composite, 3) }),
      h("dt", { text: "z: FCF·현금·모멘텀" }), h("dd", { text: [num(r.zFcfYield, 2), num(r.zCashProfitability, 2), num(r.zMomentum, 2)].join(" · ") }),
      h("dt", { text: "시가총액" }), h("dd", { text: money(r.marketCap, marketCurrency(r)) }),
      h("dt", { text: "영업현금흐름(1년)" }), h("dd", { text: money(r.cfoTTM, cur) }),
      h("dt", { text: "유형자산 취득(1년)" }), h("dd", { text: money(r.capexTTM, cur) }),
      h("dt", { text: "총자산" }), h("dd", { text: money(r.assets, cur) }),
      h("dt", { text: "기준일 종가" }), h("dd", { text: price(r.close, marketCurrency(r)) + (r.closeDate ? " (" + r.closeDate + ")" : "") }),
      h("dt", { text: "최근 공시 제출일" }), h("dd", { text: r.filedAt || "–" }),
      h("dt", { text: "표준화 기준" }), h("dd", { text: (r.zBasis || []).map(function (b) { return { sector: "업종 평균", market: "시장 평균(업종 5개 미만)" }[b] || b; }).join(", ") || "–" })
    );
    var box = h("div", { class: "detail" }, dl);
    if (r.reason) box.appendChild(h("p", { text: "사유: " + (((state.glossary || {}).reasonCodes || {})[r.reason] || r.reason) }));
    var issues = r.issues || [];
    if (issues.length) box.appendChild(h("ul", null, issues.map(function (code) { return h("li", { text: issueText(code) + " (" + code + ")" }); })));
    if (r.fundamentalsError) {
      box.appendChild(h("details", { class: "raw-log" }, h("summary", { text: "원문 수집 로그(영문, 참고용)" }),
        h("p", { class: "mono", text: r.fundamentalsError })));
    }
    return h("details", { class: "row-detail" }, h("summary", null, "근거 보기", h("span", { class: "sr-only", text: " — " + displayName(r) })), box);
  }

  function tableRow(r) {
    return h("tr", null,
      h("th", { scope: "row" }, h("div", { class: "company", text: displayName(r) }, h("small", { text: (r.ticker || "") + " · " + r.market })), detail(r)),
      h("td", { class: "sector", title: sectorName(r.sector, true), text: sectorName(r.sector) }),
      h("td", null, badge(r.label, r.labelReason)),
      h("td", { class: "num", text: r.percentile === null ? "–" : pct(r.percentile, 1) }),
      h("td", { class: "num", text: pct(r.fcfYield, 1) }),
      h("td", { class: "num", text: pct(r.cashProfitability, 1) }),
      h("td", { class: "num", text: pct(r.momentum12_1, 1) }),
      h("td", null, note(r))
    );
  }

  function card(r) {
    return h("article", { class: "card" },
      h("div", { class: "card-head" },
        h("h3", { class: "company", text: displayName(r) }, h("small", { text: (r.ticker || "") + " · " + r.market + " · " + sectorName(r.sector) })),
        badge(r.label, r.labelReason)),
      h("div", { class: "card-figures" },
        h("div", null, "FCF 수익률", h("b", { text: pct(r.fcfYield, 1) })),
        h("div", null, "현금 수익성", h("b", { text: pct(r.cashProfitability, 1) })),
        h("div", null, "12-1 모멘텀", h("b", { text: pct(r.momentum12_1, 1) }))),
      h("p", { class: "row-count", text: "백분위 " + (r.percentile === null ? "–" : pct(r.percentile, 1)) + "(높을수록 상위)" }),
      h("div", null, note(r)),
      detail(r));
  }

  function clearTable() {
    clear($("rows")); clear($("cards")); clear($("label-strip"));
    $("row-count").textContent = "";
    $("more").hidden = true;
    $("csv").disabled = true;
    $("changes-section").hidden = true;
  }

  function refresh() {
    pressed($("market-filter"), state.market);
    pressed($("label-filter"), state.label);
    if (!state.view) { clearTable(); return; }
    labelStrip();
    var rows = filtered(), body = clear($("rows")), cards = clear($("cards"));
    var visible = rows.slice(0, state.shown), mobile = MOBILE.matches;
    if (!rows.length) {
      var empty = "조건에 맞는 종목이 없습니다.";
      if (mobile) cards.appendChild(h("p", { class: "empty", text: empty }));
      else body.appendChild(h("tr", null, h("td", { colspan: "8", class: "empty", text: empty })));
    }
    visible.forEach(function (r) { if (mobile) cards.appendChild(card(r)); else body.appendChild(tableRow(r)); });
    $("row-count").textContent = rows.length + "개 중 " + visible.length + "개 표시";
    $("more").hidden = visible.length >= rows.length;
    $("csv").disabled = !rows.length;
    renderChanges();
  }

  function selectMonth(name) {
    var token = state.token = state.token + 1;
    state.month = name;
    state.view = null; state.rows = []; state.previous = null; state.previousMonths = {}; state.previousError = null;
    state.shown = PAGE_SIZE;
    pressed($("month-buttons"), name);
    clearTable();
    var entry = (state.index.months || []).filter(function (m) { return m.month === name; })[0];
    $("preview-banner").hidden = !(entry && entry.preview);
    $("month-note").textContent = "불러오는 중…";
    fetchJson(entry.data).then(function (view) {
      if (token !== state.token) return null;
      state.view = view;
      state.rows = rowObjects(view);
      buildSectors();
      var asOf = view.asOf || {};
      $("month-note").textContent = "기준일 " + Object.keys(asOf).map(function (m) { return m + " " + asOf[m]; }).join(", ") +
        (view.preview ? " · 시험 실행(공식 등급 아님)" : " · 등록 " + kst(view.registeredAt) + " · 원장 #" +
        (view.ledger && view.ledger.sequence) + " " + short(view.ledger && view.ledger.eventHash));
      // Each market is compared with the latest earlier registration that holds it (D16).
      var earlier = (state.index.months || []).filter(function (m) { return !m.preview && m.month < name; });
      var wanted = {};
      Object.keys(asOf).forEach(function (market) {
        for (var k = earlier.length - 1; k >= 0; k--) {
          if (earlier[k].labels && earlier[k].labels[market]) { (wanted[earlier[k].month] = wanted[earlier[k].month] || []).push(market); break; }
        }
      });
      state.previousMonths = wanted;
      refresh();  // the month at once; the optional comparison follows
      var months = Object.keys(wanted).sort();
      if (view.preview || !months.length) return null;
      // The comparison is optional: a missing earlier file never hides this month.
      return Promise.all(months.map(function (m) { return fetchJson("data/" + m + ".json"); })).then(function (views) {
        if (token !== state.token) return;
        var rows = [];
        views.forEach(function (v, k) {
          rowObjects(v).forEach(function (r) { if (wanted[months[k]].indexOf(r.market) >= 0) rows.push(r); });
        });
        state.previous = rows;
      }, function (error) {
        if (token === state.token) state.previousError = error.message;
      });
    }).then(function () { if (token === state.token) renderChanges(); }, function (error) {
      if (token !== state.token) return;
      $("month-note").textContent = "이 달의 표를 불러오지 못했습니다(" + error.message + ").";
      clearTable();
    });
  }

  /* ---- changes ---------------------------------------------------------- */
  function kind(r) { return r.label || (r.labelReason === "excluded" ? "금융 제외" : "자료 부족"); }

  function renderChanges() {
    var section = $("changes-section"), box = clear($("changes"));
    if (!state.view || state.view.preview) { section.hidden = true; return; }
    if (state.previousError) {
      section.hidden = false;
      $("changes-note").textContent = "지난 등록 파일을 불러오지 못해 비교하지 않았습니다(" + state.previousError + ").";
      return;
    }
    if (!state.previous) { section.hidden = true; return; }
    section.hidden = false;
    var compared = {};
    Object.keys(state.previousMonths || {}).forEach(function (m) { state.previousMonths[m].forEach(function (k) { compared[k] = true; }); });
    var inMarket = function (r) { return compared[r.market] && (state.market === "ALL" || r.market === state.market); };
    var before = {}, seen = {}, groups = {}, moved = 0, entered = 0;
    state.previous.forEach(function (r) { if (inMarket(r)) before[r.id] = r; });
    state.rows.forEach(function (r) {
      if (!inMarket(r)) return;
      seen[r.id] = true;
      var p = before[r.id];
      if (!p) { entered += 1; return; }
      var from = kind(p), to = kind(r);
      if (from === to) return;
      moved += 1;
      (groups[from + ">" + to] = groups[from + ">" + to] || { from: p, to: r, rows: [] }).rows.push(r);
    });
    var left = Object.keys(before).filter(function (id) { return !seen[id]; }).length;
    var since = Object.keys(state.previousMonths || {}).map(function (m) { return m + "(" + state.previousMonths[m].join("·") + ")"; }).join(", ");
    var first = Object.keys(state.view.asOf || {}).filter(function (k) { return !compared[k]; })
      .map(function (k) { return MARKETS[k] ? MARKETS[k].name : k; });
    $("changes-note").textContent = since + " 등록과 비교: " + moved + "개 종목의 등급이 바뀌었습니다. 새로 들어옴 " + entered + " · 빠짐 " + left + "." +
      (first.length ? " " + first.join("·") + "은 이번이 첫 등록이라 비교하지 않았습니다." : "");
    if (!moved) { box.appendChild(h("p", { class: "empty", text: "바뀐 등급이 없습니다." })); return; }
    var order = ["선호", "관찰", "회피", "자료 부족", "금융 제외"];
    var keys = Object.keys(groups).sort(function (a, b) {
      var x = a.split(">"), y = b.split(">");
      return order.indexOf(x[0]) - order.indexOf(y[0]) || order.indexOf(x[1]) - order.indexOf(y[1]);
    });
    box.appendChild(h("ul", { class: "changes-list", "aria-label": "등급이 바뀐 종목(전환별)" }, keys.map(function (key) {
      var g = groups[key], names = g.rows.slice(0, 15).map(function (r) { return displayName(r) + " (" + (r.ticker || "") + ")"; }).join(", ");
      if (g.rows.length > 15) names += " 외 " + (g.rows.length - 15) + "개";
      return h("li", null,
        h("div", { class: "transition" }, badge(g.from.label, g.from.labelReason), h("span", { class: "arrow", text: "→" }),
          badge(g.to.label, g.to.labelReason), h("strong", { text: g.rows.length + "개" })),
        h("p", { class: "names", text: names }));
    })));
  }

  /* ---- performance ------------------------------------------------------ */
  function renderPerformance() {
    var box = clear($("performance-body")), ev = state.index.evaluation;
    if (!inV1("US") && !inV1("KR")) {
      box.appendChild(h("p", { class: "empty", text: state.glossary.states.nothing_published }));
      return;
    }
    if (!ev) {
      box.appendChild(h("p", { class: "empty", text: "성과 평가 전입니다. 진입은 등록 다음 거래일 종가이며, 첫 완료 기간은 다음 달 등록 때 끝납니다." }));
      return;
    }
    var mean = function (m) { return m && m.mean !== null && m.mean !== undefined ? m.mean : null; };
    ["US", "KR"].forEach(function (market) {
      var s = (ev.summary || {})[market];
      if (!s) return;
      var complete = s.complete || 0;
      box.appendChild(h("h3", { class: "market-heading", text: MARKETS[market].name }));
      box.appendChild(h("p", { class: "empty", text: "평가 기준일 " + ((ev.valuedThrough || {})[market] || ev.through || "–") + " · 완료 " + complete +
        " · 진행 중 " + (s.inProgress || 0) + " · 진입 전 " + (s.pending || 0) + " · 동결 " + (s.frozen || 0) }));
      if (complete && mean(s.primary) !== null) {
        var n = s.primary.periods, tentative = n < TENTATIVE_PERIODS;
        var shown = function (value, text) { return h("strong", { class: tentative ? "tentative" : null, text: value === null ? "–" : text }); };
        box.appendChild(h("div", { class: "fact-strip metrics" },
          h("div", null, h("span", { text: "1차 지표: 선호 − 업종(비용 차감)" }),
            shown(mean(s.primary), signed(mean(s.primary)) + " (n=" + n + (tentative ? ", 해석 보류" : "") + ")")),
          h("div", null, h("span", { text: "회피 − 업종(비용 차감 전)" }), shown(mean(s.avoid), signed(mean(s.avoid)))),
          h("div", null, h("span", { text: "선호 − 회피(비용 차감 전)" }), shown(mean(s.spread), signed(mean(s.spread)))),
          h("div", null, h("span", { text: "IC 평균(2028 판정에 씀)" }), shown(mean(s.ic), num(mean(s.ic), 3))),
          h("div", null, h("span", { text: "판정일" }), h("strong", { text: (state.index.schedule || {}).reviewDate || "–" }))));
      } else {
        box.appendChild(h("p", { class: "empty", text: "완료된 기간이 아직 없습니다. 진행 중 기간의 수치는 잠정이며 판정에 쓰지 않습니다." }));
      }
    });
    box.appendChild(h("p", { class: "empty", text: "평균은 완료된 기간만 씁니다. IC는 종합 점수 순위와 다음 기간 수익률 순위의 상관입니다. " +
      "미국 과거 재현의 월별 IC 변동으로 보면 IC 0.03을 통계적으로 확인하는 데 약 6년이 걸립니다. 한국은 과거 재현을 하지 않았지만 변동이 더 커 그보다 오래 걸릴 것으로 봅니다. " +
      "효과가 작으면 2028 판정은 우연에 크게 좌우됩니다. 판정 전에는 업계보다 낫다고 주장하지 않습니다." }));
    var periods = ev.periods || [];
    if (!periods.length) return;
    var statusText = { pending: "진입 전", in_progress: "진행 중(잠정)", complete: "완료" };
    var table = h("table", null, h("caption", { class: "sr-only", text: "기간별 상태" }),
      h("thead", null, h("tr", null, ["시장", "등록 월", "상태", "진입", "청산", "선호 − 업종(비용 차감)", "표시"].map(function (t) { return h("th", { scope: "col", text: t }); }))),
      h("tbody", null, periods.slice().reverse().map(function (p) {
        var stat = (statusText[p.status] || p.status) + (p.frozen ? " · 동결" : "");
        return h("tr", null, h("td", { text: MARKETS[p.market] ? MARKETS[p.market].name : p.market }), h("td", { text: p.month }), h("td", { text: stat }),
          h("td", { text: p.entry || "–" }), h("td", { text: p.exit || "–" }),
          h("td", { class: "num", text: p.status === "complete" ? signed(p.preferNetSectorExcess) : "–" }),
          h("td", null, (p.flags || []).map(issuePill)));
      })));
    box.appendChild(h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "기간별 성과 표" }, table));
  }

  /* ---- CSV -------------------------------------------------------------- */
  function csv() {
    var cols = ["month", "asOf", "preview", "market", "ticker", "name", "sector", "sectorName", "label", "labelReason", "percentile", "composite",
      "fcfYield", "cashProfitability", "momentum12_1", "marketCap", "close", "marketCurrency", "cfoTTM", "capexTTM", "assets", "filingCurrency", "issues"];
    var view = state.view || {}, asOf = view.asOf || {};
    var lines = [cols.join(",")].concat(filtered().map(function (r) {
      return cols.map(function (c) {
        var v = { month: view.month, asOf: asOf[r.market], preview: !!view.preview, sectorName: sectorName(r.sector),
          marketCurrency: marketCurrency(r), filingCurrency: currencyOf(r) }[c];
        if (v === undefined) v = r[c];
        if (Array.isArray(v)) v = v.join(" ");
        if (v === null || v === undefined) v = "";
        v = String(v);
        return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
      }).join(",");
    }));
    var blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    var link = h("a", { href: URL.createObjectURL(blob), download: "ratings-" + state.month + ".csv" });
    document.body.appendChild(link); link.click(); link.remove();
  }

  /* ---- start ------------------------------------------------------------ */
  function ledgerLink() { return h("a", { href: LEDGER_URL, text: "원장과 등록 파일(data/ratings)" }); }

  function fail(message) {
    clear($("status")).appendChild(h("div", { class: "error-panel" }, "자료를 불러오지 못했습니다(" + message + "). ", ledgerLink(),
      h("button", { type: "button", text: "다시 시도", onclick: function () { location.reload(); } })));
    $("performance").hidden = true;
    $("provenance").textContent = "자료를 불러오지 못했습니다";
  }

  function start() {
    var typing = null;
    $("more").addEventListener("click", function () {
      var first = state.shown;  // keep the keyboard place: the first newly shown row
      state.shown += PAGE_SIZE;
      refresh();
      var added = (MOBILE.matches ? $("cards").children : $("rows").children)[first];
      var target = added && added.querySelector("summary");
      if (target) target.focus();
    });
    $("csv").addEventListener("click", csv);
    $("sector-filter").addEventListener("change", function (e) { state.sector = e.target.value; state.shown = PAGE_SIZE; refresh(); });
    $("sort-order").addEventListener("change", function (e) { state.sort = e.target.value; refresh(); });
    $("search").addEventListener("input", function (e) {
      clearTimeout(typing);
      typing = setTimeout(function () { state.query = e.target.value; state.shown = PAGE_SIZE; refresh(); }, 150);
    });
    var relayout = function () { if (state.view) refresh(); };
    if (MOBILE.addEventListener) MOBILE.addEventListener("change", relayout); else MOBILE.addListener(relayout);
    Promise.all([fetchJson("data/index.json"), fetchJson("glossary.ko.json")]).then(function (loaded) {
      state.index = loaded[0]; state.glossary = loaded[1];
      renderMetadata();
      if (state.index.status === "ledger_invalid") {
        clear($("status")).appendChild(h("div", { class: "error-panel" }, state.glossary.states.ledger_invalid + " ", ledgerLink()));
        $("performance").hidden = true;
        document.querySelector(".skip").hidden = true;
        return;
      }
      $("preview-banner").hidden = !state.index.preview;
      renderStatus();
      renderPerformance();
      var months = state.index.months || [];
      document.querySelector(".skip").hidden = !months.length;
      if (!months.length) return;
      renderLegend();
      buildMonthButtons();
      buildFilters();
      $("month-section").hidden = false;
      selectMonth(months[months.length - 1].month);
    }).catch(function (error) { fail(error.message); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
