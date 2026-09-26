"use strict";
const assert = require("node:assert/strict"),
  fs = require("node:fs"),
  path = require("node:path"),
  { pathToFileURL } = require("node:url");
const root = path.resolve(__dirname, ".."),
  load = (relative) => import(pathToFileURL(path.join(root, relative)).href);
(async () => {
  const state = await load("web/app/core/state.js"),
    formats = await load("web/app/core/formats.js"),
    polling = await load("web/app/core/polling.js"),
    dashboard = await load("web/app/components/dashboard.js"),
    menu = await load("web/app/components/menu.js"),
    bitcoin = await load("web/app/markets/bitcoin.js"),
    us = await load("web/app/markets/us-equities.js"),
    registry = await load("web/app/markets/registry.js");
  assert.deepEqual(registry.routeContext("/options/us-equities/mobile/"), {
    market: "us-equities",
    mode: "mobile",
    basePath: "/options",
  });
  assert.deepEqual(registry.routeContext("/bitcoin/desktop/"), {
    market: "bitcoin",
    mode: "desktop",
    basePath: "",
  });
  assert.deepEqual(registry.routeContext("/panel/test-market/mobile/"), {
    market: "test-market",
    mode: "mobile",
    basePath: "/panel",
  });
  assert.deepEqual(
    registry.routeContext("/desktop/archive/us-equities/mobile/"),
    {
      market: "us-equities",
      mode: "mobile",
      basePath: "/desktop/archive",
    },
  );
  registry.registerMarketAdapter("test-market", (options) => ({
    id: "test-market",
    ...options,
  }));
  assert.equal(
    registry.createMarketAdapter({
      market: "test-market",
      mode: "desktop",
      basePath: "/panel",
    }).id,
    "test-market",
  );
  const memory = new Map([
      [
        "btc-options-mobile-ui-v1",
        JSON.stringify({
          priceSide: "PUT",
          rankingRange: "3_7",
          rankingSortKey: "delta",
          rankingSortDirection: "asc",
        }),
      ],
      ["btc-options-mobile-view", "ranking"],
      [
        "us-options-filters:AAPL",
        JSON.stringify({
          mobileView: "price",
          termFilter: "CUSTOM",
          priceSort: { key: "delta", direction: "desc" },
        }),
      ],
    ]),
    store = {
      getItem: (key) => memory.get(key) ?? null,
      setItem: (key, value) => memory.set(key, value),
    };
  const btcUi = state.loadUi(store, {
    market: "bitcoin",
    provider: "binance",
    instrument: "BTCUSDT",
    mode: "mobile",
  }).value;
  assert.equal(btcUi.view, "ranking");
  assert.equal(btcUi.priceSide, "PUT");
  assert.deepEqual(btcUi.rankSort, {
    key: "exercise_probability_pct",
    direction: "asc",
  });
  const usUi = state.loadUi(store, {
    market: "us-equities",
    provider: "alpaca",
    instrument: "AAPL",
    mode: "mobile",
  }).value;
  assert.equal(usUi.view, "price");
  assert.equal(usUi.rankingRange, "LT3");
  assert.deepEqual(usUi.priceSort, {
    key: "exercise_probability_pct",
    direction: "desc",
  });
  assert.notEqual(
    state.stateKey({
      market: "bitcoin",
      provider: "one",
      instrument: "BTC",
      mode: "mobile",
    }),
    state.stateKey({
      market: "bitcoin",
      provider: "two",
      instrument: "BTC",
      mode: "mobile",
    }),
  );
  assert.equal(
    state.browserStorage({
      get localStorage() {
        throw new Error("denied");
      },
    }),
    null,
  );
  assert.doesNotThrow(() =>
    state.saveUi(
      {
        setItem() {
          throw new Error("full");
        },
      },
      "x",
      {},
    ),
  );
  const isolated = new Map(memory);
  const isolatedStore = {
    getItem: (key) => isolated.get(key) ?? null,
    setItem: (key, value) => isolated.set(key, value),
  };
  assert.equal(
    state.loadUi(isolatedStore, {
      market: "bitcoin",
      provider: "other",
      instrument: "BTCUSDT",
      mode: "mobile",
    }).value.view,
    "chain",
  );
  assert.equal(
    state.loadUi(isolatedStore, {
      market: "bitcoin",
      provider: "binance",
      instrument: "BTCUSDT",
      mode: "desktop",
    }).value.view,
    "chain",
  );
  const switched = state.normalizeUi();
  state.applySort(switched, "priceSort", "expiry_time");
  assert.deepEqual(switched.priceSort, {
    key: "expiry_time",
    direction: "asc",
  });
  assert.deepEqual(
    state.normalizeUi({
      priceSort: { key: "remaining_seconds", direction: "desc" },
    }).priceSort,
    { key: "expiry_time", direction: "desc" },
  );
  const now = 1_800_000_000_000,
    btcRaw = {
      contracts: [
        {
          symbol: "A",
          expiry_ms: now + 1800_000,
          annualized_pct: 12,
          period_return_pct: 1,
          exercise_probability_pct: 20,
          probability_display_state: "normal",
        },
        {
          symbol: "B",
          expiry_ms: now - 1,
          annualized_pct: 99,
          period_return_pct: 9,
          exercise_probability_pct: 80,
        },
      ],
    },
    btcProjected = bitcoin.projectBitcoinSnapshot(btcRaw, now);
  assert.equal(btcProjected.contracts[0].annualized_pct, 12);
  assert.equal(btcProjected.contracts[0].probability_display_state, "settling");
  assert.equal(btcProjected.contracts[1].annualized_pct, null);
  const btcAdapter = bitcoin.createBitcoinAdapter({ mode: "desktop" });
  assert.equal(
    formats.chinaDateTimeMinute(Date.parse("2026-10-03T12:00:00Z")),
    "2026-10-03 20:00",
  );
  assert.equal(formats.chinaDateTimeMinute(null), "—");
  assert.equal(formats.chinaDateTimeMinute(""), "—");
  assert.equal(formats.chinaDateTimeMinute(1e20), "—");
  assert.equal(formats.tableRemaining(NaN), "—");
  assert.equal(formats.tableRemaining(Infinity), "—");
  assert.equal(formats.tableRemaining(-1), "—");
  assert.equal(formats.tableRemaining(0), "已到期");
  assert.equal(formats.tableRemaining(1), "<1小时");
  assert.equal(formats.tableRemaining(3599), "<1小时");
  assert.equal(formats.tableRemaining(3600), "1小时");
  assert.equal(formats.tableRemaining(86399), "23小时");
  assert.equal(formats.tableRemaining(86400), "1天");
  assert.equal(formats.tableRemaining(172799), "1天");
  assert.equal(formats.tableRemaining(172800), "2天");
  assert.equal(
    btcAdapter.expiryDetail({
      expiry_ms: Date.parse("2026-10-03T12:00:00Z"),
    }),
    "2026-10-03 20:00",
  );
  assert.equal(btcAdapter.expiryDetail({ expiry_ms: null }), "—");
  assert.equal(btcAdapter.sortValue({ expiry_ms: null }, "expiry_time"), null);
  assert.equal(btcAdapter.expiryInstant({ expiry_ms: "   " }), null);
  assert.equal(btcAdapter.expiryInstant({ expiry_ms: true }), null);
  assert.equal(btcAdapter.expiryInstant({ expiry_ms: 1e20 }), null);
  assert.equal(btcAdapter.expiryInstant({ expiry_ms: String(now) }), now);
  assert.equal(btcAdapter.sortValue({ expiry_ms: now }, "expiry_time"), now);
  assert.equal(
    btcAdapter.sortValue(
      { exercise_probability_pct: 88, probability_display_state: "settling" },
      "exercise_probability_pct",
    ),
    null,
  );
  assert.equal(
    btcAdapter.priceEligible({
      remaining_seconds: 10,
      time_value_status: "negative",
      open_interest: 1,
      annualized_pct: 2,
    }),
    false,
  );
  assert.equal(
    btcAdapter.annualHtml({ open_interest: 0, annualized_pct: 12 }),
    "—",
  );
  assert.match(
    btcAdapter.annualHtml({
      open_interest: 1,
      time_value_status: "negative",
      time_value: -0.001,
      mark_annualized_pct: 3,
    }),
    /Bid &lt; 内在价值.*TV -&lt;0.01.*Mark 3.0%/,
  );
  assert.match(
    btcAdapter.annualHtml({
      open_interest: 1,
      time_value_status: "zero",
      time_value: 0,
    }),
    /Bid = 内在价值.*TV 0.00/,
  );
  assert.equal(
    btcAdapter.probabilityHtml({
      open_interest: 0,
      exercise_probability_pct: 80,
    }),
    "—",
  );
  assert.equal(
    btcAdapter.probabilityHtml({
      open_interest: 1,
      exercise_probability_pct: 0.01,
    }),
    "&lt;0.1%",
  );
  assert.equal(
    btcAdapter.probabilityHtml({
      open_interest: 1,
      exercise_probability_pct: 99.99,
    }),
    "&gt;99.9%",
  );
  assert.equal(
    btcAdapter.probabilityHtml({
      open_interest: 1,
      exercise_probability_pct: null,
    }),
    "—",
  );
  assert.equal(
    btcAdapter.periodParts(
      {
        side: "PUT",
        strike: 90,
        open_interest: 1,
        time_value_status: "positive",
        period_return_pct: 1,
      },
      100,
    ).showRelative,
    false,
  );
  assert.equal(
    btcAdapter.status({ status: { status: "healthy" } }).health,
    "unknown",
  );
  assert.equal(
    bitcoin.defaultBitcoinExpiry(
      [now + 2 * 864e5, now + 15 * 864e5, now + 16 * 864e5],
      now,
    ),
    now + 15 * 864e5,
  );
  assert.equal(bitcoin.bitcoinRemaining(4 * 86400 + 7200), "4天");
  assert.equal(bitcoin.bitcoinRemaining(3 * 86400), "3天0小时");
  assert.equal(bitcoin.bitcoinRemaining(3599), "0天0小时");
  assert.equal(bitcoin.bitcoinMobileRemaining(3599), "不足1小时");
  assert.equal(bitcoin.bitcoinMobileRemaining(23 * 3600), "23小时");
  assert.equal(bitcoin.bitcoinMobileRemaining(2 * 86400), "2天");
  assert.deepEqual(
    btcAdapter
      .strikeGroups([79500, 80000, 89999, 90000])
      .map((group) => [group.id, group.label, group.strikes]),
    [
      ["70000", "7万", [79500]],
      ["80000", "8万", [80000, 89999]],
      ["90000", "9万", [90000]],
    ],
  );
  const usRaw = {
    state: "ready",
    fetch_health: "healthy",
    market_status: "OPEN",
    server_time: new Date(now).toISOString(),
    fetched_age_seconds: 0,
    market_status_valid_until_utc: new Date(now + 10_000).toISOString(),
    contracts: [
      {
        contract_symbol: "LIVE",
        expires_at_utc: new Date(now + 864e5).toISOString(),
        quote_valid_until_utc: new Date(now + 1).toISOString(),
        calculation_status: "calculated",
        ranking_eligible: true,
        close_reference_eligible: true,
        annualized_pct: 1,
      },
      {
        contract_symbol: "EXPIRED",
        expires_at_utc: new Date(now - 1).toISOString(),
        calculation_status: "calculated",
        annualized_pct: 2,
      },
    ],
  };
  const atNow = us.projectUsSnapshot(usRaw, now),
    crossed = us.projectUsSnapshot(usRaw, now + 10_001);
  assert.equal(atNow.mode, "live");
  assert.equal(atNow.contracts[0].close_reference_reason, "market_not_closed");
  assert.equal(crossed.mode, "unavailable");
  assert.equal(crossed.mode_reason, "market_transition_requires_refresh");
  assert.equal(
    crossed.contracts[0].ranking_reason,
    "market_transition_requires_refresh",
  );
  assert.equal(crossed.contracts[1].probability_reason, "expired");
  assert.equal(
    us.defaultUsExpiry(
      ["2026-10-01", "2026-10-10"],
      [{ expiration_date: "2026-10-10", remaining_seconds: 15 * 86400 }],
      "mobile",
    ),
    "2026-10-10",
  );
  assert.equal(
    us.defaultUsExpiry(["2026-10-01", "2026-10-10"], [], "desktop"),
    "2026-10-01",
  );
  assert.deepEqual(
    us.splitUsExpiries(["2026-09-01", "2027-05-01"], "2026-09-30"),
    { near: ["2026-09-01"], far: ["2027-05-01"] },
  );
  assert.equal(us.validExpiryDate("2026-02-31"), false);
  assert.equal(us.stockLabel("AAPL"), "AAPL（苹果）");
  assert.equal(
    us
      .createUsAdapter({ mode: "desktop", storage: store })
      .expiryLabel("2026-10-03", [
        {
          expiration_date: "2026-10-03",
          expires_at_utc: "2026-10-03T20:00:00Z",
        },
        {
          expiration_date: "2026-10-03",
          expires_at_utc: "2026-10-03T21:00:00Z",
        },
      ]),
    "—",
  );
  const usFormatAdapter = us.createUsAdapter({
    mode: "desktop",
    storage: store,
  });
  assert.equal(
    usFormatAdapter.expiryDetail({ expires_at_utc: "2026-10-03T12:00:00Z" }),
    "2026-10-03 20:00",
  );
  assert.equal(usFormatAdapter.expiryDetail({ expires_at_utc: null }), "—");
  assert.equal(usFormatAdapter.expiryDetail({ expires_at_utc: 0 }), "—");
  assert.equal(usFormatAdapter.expiryDetail({ expires_at_utc: "   " }), "—");
  assert.equal(usFormatAdapter.expiryInstant({ expires_at_utc: null }), null);
  assert.equal(usFormatAdapter.expiryInstant({ expires_at_utc: 0 }), null);
  assert.equal(usFormatAdapter.expiryInstant({ expires_at_utc: "   " }), null);
  assert.equal(
    usFormatAdapter.sortValue(
      { expires_at_utc: "2026-10-03T12:00:00Z" },
      "expiry_time",
    ),
    Date.parse("2026-10-03T12:00:00Z"),
  );
  assert.equal(usFormatAdapter.remainingText(4 * 86400 + 7200), "4天");
  assert.equal(usFormatAdapter.remainingText(3 * 86400), "3天0小时");
  assert.equal(usFormatAdapter.remainingText(3599), "59分钟");
  assert.equal(usFormatAdapter.remainingText(30), "1分钟");
  assert.equal(
    usFormatAdapter.todayForExpirySplit(new Date("2026-09-27T02:30:00Z")),
    "2026-09-26",
  );
  assert.deepEqual(
    usFormatAdapter.strikeGroups(
      Array.from({ length: 12 }, (_, index) => 100 + index),
    ),
    [
      {
        id: "0",
        label: "100–109",
        strikes: [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
      },
      { id: "1", label: "110–111", strikes: [110, 111] },
    ],
  );
  const escapedMenu = menu.menuOptions(
    ['x" onfocus="globalThis.injected=1'],
    null,
    () => "<img src=x onerror=globalThis.injected=1>",
  );
  assert(!escapedMenu.includes("<img"));
  assert(!escapedMenu.includes('data-value="x" onfocus='));
  const signatureAdapter = {
    contractId: (row) => row.id,
    expiry: (row) => row.expiry,
  };
  const signature = dashboard.Dashboard.prototype.projectionSignature.bind({
    adapter: signatureAdapter,
  });
  const baseSignature = {
    underlying_price: 1,
    contracts: [
      {
        id: "a",
        expiry: "2026-10-01",
        remaining_seconds: 3660,
        annualized_pct: 1,
      },
    ],
  };
  assert.notEqual(
    signature(baseSignature),
    signature({ ...baseSignature, underlying_price: 2 }),
  );
  assert.notEqual(
    signature(baseSignature),
    signature({
      ...baseSignature,
      contracts: [{ ...baseSignature.contracts[0], remaining_seconds: 3540 }],
    }),
  );
  const duplicate = dashboard.groupByStrike([
    { strike: 100, side: "CALL", contract_symbol: "A" },
    { strike: 100, side: "CALL", contract_symbol: "B" },
    { strike: 100, side: "PUT", contract_symbol: "P" },
  ]);
  assert.deepEqual(
    duplicate.get(100).CALL.map((row) => row.contract_symbol),
    ["A", "B"],
  );
  assert.deepEqual(dashboard.paginationItems(50, 100), [
    1,
    "ellipsis",
    49,
    50,
    51,
    "ellipsis",
    100,
  ]);
  assert(dashboard.paginationItems(50, 100).length <= 7);
  assert.deepEqual(dashboard.resolvedRankingPage(5, 1, false), {
    displayPage: 1,
    storedPage: 5,
  });
  assert.deepEqual(dashboard.resolvedRankingPage(5, 2, true), {
    displayPage: 2,
    storedPage: 2,
  });
  assert.deepEqual(dashboard.partitionStrikes([80, 90, 100, 110], 100), {
    lower: [80, 90, 100],
    higher: [110],
    atMoney: 100,
  });
  assert.equal(polling.retryDelay({ retryAfter: 999 }), 300000);
  assert.equal(polling.retryDelay({ retryAfter: -2 }), 5000);
  assert.equal(polling.retryDelay({ retryAfter: "bad" }), 5000);
  assert.equal(
    bitcoin
      .createBitcoinAdapter({ mode: "desktop" })
      .periodParts(
        { side: "CALL", strike: 100, open_interest: 0, period_return_pct: 1 },
        90,
      ).unavailable,
    true,
  );
  assert.equal(dashboard.termMatches(60 * 86400, "30_60"), true);
  assert.equal(dashboard.termMatches(60 * 86400, "GT60"), false);
  assert.deepEqual(
    dashboard
      .sortNullLast(
        [
          { v: null, id: "z" },
          { v: 2, id: "b" },
          { v: 1, id: "a" },
        ],
        { key: "v", direction: "asc" },
      )
      .map((x) => x.id),
    ["a", "b", "z"],
  );
  const timers = new Map();
  let timerId = 0,
    requests = 0,
    commits = 0,
    resolveRequest;
  const fakeTimers = {
    setTimeout(fn) {
      const id = ++timerId;
      timers.set(id, fn);
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
  };
  const controller = new polling.PollingController({
    request: () => {
      requests++;
      return new Promise((resolve) => (resolveRequest = resolve));
    },
    commit: () => {
      commits++;
    },
    interval: 5,
    timeout: 50,
    documentRef: { hidden: false },
    timers: fakeTimers,
  });
  controller.start();
  controller.schedule();
  assert.equal(requests, 1);
  assert(controller.pendingTimers <= 2);
  resolveRequest({ ok: true });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(commits, 1);
  controller.hidden();
  assert.equal(controller.pendingTimers, 0);
  controller.stop();
  const documentRef = { hidden: false };
  let visibleRequests = 0,
    visibilityFailures = 0;
  const visibility = new polling.PollingController({
    request: (signal) => {
      visibleRequests++;
      return new Promise((resolve, reject) =>
        signal.addEventListener("abort", () => reject(signal.reason), {
          once: true,
        }),
      );
    },
    commit: () => {},
    fail: () => visibilityFailures++,
    interval: 100,
    timeout: 100,
    documentRef,
  });
  visibility.start();
  documentRef.hidden = true;
  visibility.hidden();
  documentRef.hidden = false;
  visibility.visible();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(visibleRequests, 2);
  visibility.stop();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(visibilityFailures, 0);
  await assert.rejects(
    polling.withTimeout(
      (signal) =>
        new Promise((resolve, reject) =>
          signal.addEventListener("abort", () => reject(signal.reason), {
            once: true,
          }),
        ),
      1,
    ),
    /请求超时/,
  );
  assert.equal(polling.errorMessage("network offline"), "network offline");
  assert.equal(polling.errorMessage(null), "未知错误");
  assert.equal(polling.errorMessage({}), "未知错误");
  assert.equal(
    polling.errorMessage({
      get message() {
        throw new Error("unsafe getter");
      },
    }),
    "未知错误",
  );
  const timeoutTimers = new Map();
  let timeoutTimerId = 0,
    timeoutFailure;
  const timeoutController = new polling.PollingController({
    request: (signal) =>
      new Promise((resolve, reject) =>
        signal.addEventListener("abort", () => reject(signal.reason), {
          once: true,
        }),
      ),
    commit: () => {},
    fail: (error) => {
      timeoutFailure = error;
    },
    timeout: 50,
    documentRef: { hidden: false },
    timers: {
      setTimeout(fn) {
        const id = ++timeoutTimerId;
        timeoutTimers.set(id, fn);
        return id;
      },
      clearTimeout(id) {
        timeoutTimers.delete(id);
      },
    },
  });
  timeoutController.start();
  timeoutTimers.get(1)();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(timeoutFailure?.message, "请求超时");
  timeoutController.stop();
  const originalFetch = global.fetch;
  const bodyController = new AbortController();
  global.fetch = async (url, options) => ({
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: () =>
      new Promise((resolve, reject) =>
        options.signal.addEventListener(
          "abort",
          () => reject(options.signal.reason),
          { once: true },
        ),
      ),
  });
  const bodyRequest = polling.fetchJson("/body-abort", {
    signal: bodyController.signal,
  });
  await Promise.resolve();
  bodyController.abort("timeout");
  await assert.rejects(bodyRequest, /请求超时/);
  let releasedUrl = "";
  global.fetch = async (url) => {
    releasedUrl = String(url);
    return { ok: true };
  };
  const usAdapter = us.createUsAdapter({ mode: "desktop", storage: store });
  assert.equal(
    usAdapter.expiryLabel("2026-10-03", [
      { expiration_date: "2026-10-03", expires_at_utc: "2026-10-03T20:00:00Z" },
    ]),
    "2026-10-04",
  );
  usAdapter.setSymbol("AAPL");
  usAdapter.release();
  assert.match(releasedUrl, /active=0/);
  assert.match(releasedUrl, /activity_seq=1/);
  global.fetch = originalFetch;
  usAdapter.merge(usRaw);
  usAdapter.setLocalError("temporary failure");
  const failedProjection = usAdapter.project(now);
  assert.equal(failedProjection.mode, "unavailable");
  assert.equal(failedProjection.fetch_health, "failed");
  const html = fs.readFileSync(path.join(root, "web/app/index.html"), "utf8");
  assert(html.includes('type="module"'));
  assert.equal((html.match(/data-panel=/g) || []).length, 3);
  for (const legacy of [
    "web/desktop",
    "web/mobile",
    "web/us-equities/app.js",
    "web/us-equities/style.css",
  ])
    assert(!fs.existsSync(path.join(root, legacy)));
  // Run thousands of refreshes without real time or network. Include failures,
  // timeouts and hide/resume while retaining only a single in-flight request.
  const stressTimers = new Map();
  const stressDocument = { hidden: false };
  let stressNow = 0,
    stressId = 0,
    stressRequests = 0,
    stressActive = 0,
    stressPeak = 0,
    stressCommits = 0,
    stressFailures = 0,
    lastStressSequence = 0;
  const stressClock = {
    setTimeout(fn, delay) {
      const id = ++stressId;
      stressTimers.set(id, { at: stressNow + delay, fn });
      return id;
    },
    clearTimeout(id) {
      stressTimers.delete(id);
    },
  };
  const flushStress = async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  };
  const stress = new polling.PollingController({
    timers: stressClock,
    documentRef: stressDocument,
    interval: 5,
    timeout: 50,
    request: (signal, sequence) =>
      new Promise((resolve, reject) => {
        stressRequests++;
        stressPeak = Math.max(stressPeak, ++stressActive);
        let settled = false;
        const finish = (error) => {
          if (settled) return;
          settled = true;
          stressActive--;
          stressClock.clearTimeout(timer);
          signal.removeEventListener("abort", abort);
          if (error) reject(error);
          else resolve(sequence);
        };
        const abort = () =>
          finish(
            Object.assign(new Error("interrupted"), {
              name: signal.reason === "timeout" ? "Error" : "AbortError",
            }),
          );
        const timer = stressClock.setTimeout(
          () => finish(sequence % 7 === 0 ? new Error("offline") : null),
          sequence % 11 === 0 ? 100 : 10,
        );
        signal.addEventListener("abort", abort, { once: true });
      }),
    commit: (sequence) => {
      assert(sequence > lastStressSequence);
      lastStressSequence = sequence;
      stressCommits++;
    },
    fail: () => {
      stressFailures++;
      return 15;
    },
  });
  stress.start();
  for (let step = 0; stressRequests < 2000 && step < 10000; step++) {
    const next = [...stressTimers.entries()].sort(
      (a, b) => a[1].at - b[1].at,
    )[0];
    assert(next, "poller must recover after every failure");
    stressNow = next[1].at;
    stressTimers.delete(next[0]);
    next[1].fn();
    await flushStress();
    if (step % 97 === 0) {
      stressDocument.hidden = true;
      stress.hidden();
      await flushStress();
      assert.equal(stressTimers.size, 0);
      stressDocument.hidden = false;
      stress.visible();
    }
    assert(stressTimers.size <= 3);
    assert(stress.pendingTimers <= 2);
  }
  stress.stop();
  await flushStress();
  assert.equal(stressRequests, 2000);
  assert.equal(stressPeak, 1);
  assert.equal(stressActive, 0);
  assert.equal(stressTimers.size, 0);
  assert(stressCommits > 1000 && stressFailures > 200);
  console.log("Unified UI modules: PASS (including 2000 virtual refreshes)");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
