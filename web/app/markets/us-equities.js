import { fetchJson } from "../core/polling.js";
import { finite, number, percent } from "../core/formats.js";
import { mergeSnapshot } from "../core/model.js";
import { safeGet, safeSet } from "../core/state.js";

/**
 * US contract fields remain provider-neutral raw API values. Local projection
 * may expire eligibility and countdowns, but never recomputes financial metrics.
 * @typedef {object} UsContract
 * @property {string} contract_symbol
 * @property {string} expiration_date Stable sorting and selection identifier.
 * @property {string} expires_at_utc Verified expiry instant used for display.
 */

export function addCalendarMonths(day, months) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isInteger(months))
    return null;
  const [y, m, d] = day.split("-").map(Number),
    target = m - 1 + months,
    year = y + Math.floor(target / 12),
    month = ((target % 12) + 12) % 12,
    last = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return new Date(Date.UTC(year, month, Math.min(d, last)))
    .toISOString()
    .slice(0, 10);
}
export function defaultUsExpiry(expiries, rows, mode) {
  if (!expiries.length) return null;
  if (mode === "desktop") return expiries[0];
  const within = rows
    .filter(
      (row) =>
        finite(row.remaining_seconds) && row.remaining_seconds <= 15 * 86400,
    )
    .map((row) => row.expiration_date)
    .filter(Boolean)
    .sort();
  return within.at(-1) ?? expiries[0];
}
export function splitUsExpiries(expiries, today) {
  const cutoff = addCalendarMonths(today, 6);
  return {
    near: expiries.filter((value) => !cutoff || value <= cutoff),
    far: expiries.filter((value) => cutoff && value > cutoff),
  };
}

export function validExpiryDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return (
    Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
  );
}

const STOCK_NAMES = Object.freeze({
  AAPL: "苹果",
  GOOG: "谷歌",
  GOOGL: "谷歌",
  MSFT: "微软",
  AMZN: "亚马逊",
  NVDA: "英伟达",
  TSLA: "特斯拉",
  NFLX: "奈飞",
  AMD: "超威半导体",
  INTC: "英特尔",
  BABA: "阿里巴巴",
  JD: "京东",
  PDD: "拼多多",
  BIDU: "百度",
  NTES: "网易",
  BILI: "哔哩哔哩",
  TSM: "台积电",
  NIO: "蔚来",
  XPEV: "小鹏汽车",
  LI: "理想汽车",
  KO: "可口可乐",
  PEP: "百事",
  MCD: "麦当劳",
  SBUX: "星巴克",
  DIS: "迪士尼",
  WMT: "沃尔玛",
  COST: "开市客",
  NKE: "耐克",
  JPM: "摩根大通",
  BAC: "美国银行",
  MA: "万事达",
  PYPL: "贝宝",
  ADBE: "奥多比",
  ORCL: "甲骨文",
  CSCO: "思科",
  QCOM: "高通",
  UBER: "优步",
  DELL: "戴尔",
});

export function stockLabel(symbol) {
  const name = STOCK_NAMES[symbol];
  return name && name !== symbol ? `${symbol}（${name}）` : symbol;
}

export function projectUsSnapshot(source, nowMs, staleSeconds = 120) {
  if (!source || typeof source !== "object") return source;
  const out = { ...source },
    rows = (source.contracts || []).map((row) => ({ ...row }));
  out.contracts = rows;
  const base = Date.parse(source.server_time),
    transition = Date.parse(source.market_status_valid_until_utc),
    baseAge = Number(source.fetched_age_seconds),
    elapsed = Number.isFinite(base) ? Math.max(0, (nowMs - base) / 1000) : 0,
    age = finite(baseAge) ? Math.max(0, baseAge + elapsed) : null;
  if (finite(age)) out.fetched_age_seconds = age;
  if (finite(out.next_refresh_seconds))
    out.next_refresh_seconds = Math.max(0, out.next_refresh_seconds - elapsed);
  const crossed = Number.isFinite(transition) && nowMs >= transition,
    stale = finite(age) && age >= staleSeconds;
  if (stale) {
    out.fetch_health = "stale";
    if (out.state === "ready") out.state = "stale";
  }
  let live = false,
    closed = false;
  for (const row of rows) {
    const expiry = Date.parse(row.expires_at_utc),
      valid = Date.parse(row.quote_valid_until_utc),
      expired = Number.isFinite(expiry) && expiry <= nowMs;
    if (Number.isFinite(expiry))
      row.remaining_seconds = Math.max(0, (expiry - nowMs) / 1000);
    if (expired) {
      Object.assign(row, {
        calculation_status: "expired",
        annualized_pct: null,
        period_return_pct: null,
        exercise_probability_pct: null,
        probability_reason: "expired",
        remaining_seconds: 0,
        ranking_eligible: false,
        ranking_reason: "expired",
        close_reference_eligible: false,
        close_reference_reason: "expired",
      });
      continue;
    }
    if (row.calculation_status === "calculated") {
      row.ranking_eligible = Number.isFinite(valid) && nowMs <= valid;
      row.ranking_reason = row.ranking_eligible
        ? null
        : Number.isFinite(valid)
          ? "quote_ranking_window_expired"
          : "quote_ranking_window_unverified";
    }
    live ||= row.ranking_eligible === true;
    closed ||= row.close_reference_eligible === true;
  }
  const healthy =
    out.state === "ready" && out.fetch_health === "healthy" && !crossed;
  if (!healthy) {
    out.mode = "unavailable";
    for (const row of rows)
      Object.assign(row, {
        ranking_eligible: false,
        ranking_reason: crossed
          ? "market_transition_requires_refresh"
          : "snapshot_not_healthy",
        close_reference_eligible: false,
        close_reference_reason: crossed
          ? "market_transition_requires_refresh"
          : "snapshot_not_healthy",
      });
  } else if (String(out.market_status).toUpperCase() === "OPEN" && live) {
    out.mode = "live";
    for (const row of rows) {
      row.close_reference_eligible = false;
      row.close_reference_reason = "market_not_closed";
    }
  } else if (String(out.market_status).toUpperCase() === "CLOSED" && closed)
    out.mode = "close_reference";
  else {
    out.mode = "unavailable";
    out.mode_reason = "no_eligible_contracts";
  }
  if (crossed) out.mode_reason = "market_transition_requires_refresh";
  return out;
}

export function createUsAdapter({ basePath = "", mode, storage }) {
  let source = null,
    symbol = null,
    symbols = [],
    watchRevision = null,
    localError = null,
    metadataError = null,
    clientId =
      globalThis.crypto?.randomUUID?.() ||
      `tab-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    activity = 0;
  const url = (active = true, version = null) => {
    const query = new URLSearchParams({
      symbol,
      client_id: clientId,
      active: active ? "1" : "0",
      activity_seq: String(++activity),
    });
    if (version) query.set("if_version", version);
    return `${basePath}/api/v1/us-equities/snapshot?${query}`;
  };
  return {
    id: "us-equities",
    mode,
    provider: "alpaca",
    defaultProvider: "alpaca",
    navigationLabel: "美股期权",
    title: "美股期权看板",
    currency: "USD",
    footer: "数据来源：Alpaca 免费参考行情",
    footerUrl: "https://alpaca.markets/data",
    supportsSymbols: true,
    showMarketStatus: true,
    priceDigits: 2,
    parseExpiryId: String,
    remainingText(seconds) {
      if (!finite(seconds)) return "—";
      if (seconds <= 0) return "已到期";
      if (seconds > 3 * 86400) return `${Math.floor(seconds / 86400)}天`;
      if (seconds < 3600) return `${Math.max(1, Math.floor(seconds / 60))}分钟`;
      const days = Math.floor(seconds / 86400),
        hours = Math.floor((seconds % 86400) / 3600);
      return days ? `${days}天${hours}小时` : `${hours}小时`;
    },
    mobileRemainingText(seconds) {
      return this.remainingText(seconds);
    },
    strikeGroups(strikes) {
      const groups = [];
      for (let index = 0; index < strikes.length; index += 10) {
        const values = strikes.slice(index, index + 10);
        groups.push({
          id: `${index / 10}`,
          label:
            values.length === 1
              ? number(values[0], 0)
              : `${number(values[0], 0)}–${number(values.at(-1), 0)}`,
          strikes: values,
        });
      }
      return groups;
    },
    todayForExpirySplit(now = new Date()) {
      const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/New_York",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).formatToParts(now);
      const get = (type) =>
        parts.find((part) => part.type === type)?.value || "";
      return `${get("year")}-${get("month")}-${get("day")}`;
    },
    rankingColumns: [
      "expiry",
      "strike",
      "period_return_pct",
      "annualized_pct",
      "exercise_probability_pct",
      "remaining_seconds",
    ],
    priceAnnualLabel() {
      return "参考年化";
    },
    get symbol() {
      return symbol;
    },
    symbolLabel(value) {
      return stockLabel(value);
    },
    async initialize(signal) {
      const watch = await fetchJson(
        `${basePath}/api/v1/us-equities/watchlist`,
        { signal },
      );
      symbols = Array.isArray(watch)
        ? watch
        : watch.symbols || watch.watchlist || [];
      watchRevision = watch.revision || null;
      const remembered = safeGet(storage, "us-options-selected-symbol");
      symbol = symbols.includes(remembered) ? remembered : symbols[0] || null;
      return { symbols, symbol };
    },
    async refreshMetadata(signal) {
      const watch = await fetchJson(
          `${basePath}/api/v1/us-equities/watchlist`,
          { signal },
        ),
        next = Array.isArray(watch)
          ? watch
          : watch.symbols || watch.watchlist || [],
        changed =
          watch.revision !== watchRevision ||
          next.join(",") !== symbols.join(","),
        previous = symbol;
      watchRevision = watch.revision || null;
      metadataError = null;
      symbols = next;
      if (!symbol || !symbols.includes(symbol)) {
        symbol = symbols[0] || null;
        source = null;
        safeSet(storage, "us-options-selected-symbol", symbol || "");
      }
      return { changed, symbolChanged: previous !== symbol, symbols, symbol };
    },
    setSymbol(value) {
      symbol = value;
      source = null;
      safeSet(storage, "us-options-selected-symbol", value || "");
    },
    async request(signal) {
      if (!symbol)
        return {
          contracts: [],
          state: "configuration_required",
          fetch_health: "awaiting_configuration",
          error: "自选列表为空，请先在本机管理页添加股票。",
        };
      let payload = await fetchJson(url(true, source?.snapshot_version), {
        signal,
      });
      if (payload.unchanged && !source)
        payload = await fetchJson(url(true), { signal });
      return payload;
    },
    merge(payload) {
      localError = null;
      source = mergeSnapshot(source, payload);
      return source;
    },
    setLocalError(message) {
      localError = message || "读取失败";
    },
    setMetadataError(message) {
      metadataError = message || "自选资料读取失败";
    },
    project(nowMs) {
      const snapshot = projectUsSnapshot(source, nowMs);
      if (snapshot && (localError || metadataError)) {
        const message = [localError, metadataError].filter(Boolean).join("；");
        snapshot.state = "degraded";
        snapshot.fetch_health = "failed";
        snapshot.mode = "unavailable";
        snapshot.error = message;
        for (const row of snapshot.contracts || []) {
          row.ranking_eligible = false;
          row.ranking_reason = "snapshot_not_healthy";
          row.close_reference_eligible = false;
          row.close_reference_reason = "snapshot_not_healthy";
        }
      }
      return snapshot;
    },
    serverNow(snapshot, receivedAt = performance.now()) {
      const epoch = Date.parse(snapshot?.server_time);
      return () =>
        Number.isFinite(epoch)
          ? epoch + Math.max(0, performance.now() - receivedAt)
          : Date.now();
    },
    expiry(row) {
      return row.expiration_date;
    },
    contractId(row) {
      return row.contract_symbol;
    },
    expiryLabel(value, rows = []) {
      const matching = rows.filter((item) => item.expiration_date === value),
        instants = new Set(
          matching.map((row) => Date.parse(row.expires_at_utc)),
        );
      if (instants.size !== 1) return "—";
      const time = [...instants][0];
      if (!Number.isFinite(time)) return "—";
      return new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      })
        .format(new Date(time))
        .replaceAll("/", "-");
    },
    displayable(row) {
      return (
        row.calculation_status !== "expired" &&
        finite(row.strike) &&
        row.strike > 0 &&
        validExpiryDate(row.expiration_date) &&
        ["CALL", "PUT"].includes(row.side) &&
        [
          row.annualized_pct,
          row.period_return_pct,
          row.exercise_probability_pct,
        ].some(finite)
      );
    },
    priceEligible(row) {
      return this.displayable(row);
    },
    rankingEligible(row, snapshot) {
      return (
        row.calculation_status === "calculated" &&
        (snapshot?.mode === "live"
          ? row.ranking_eligible === true
          : snapshot?.mode === "close_reference"
            ? row.close_reference_eligible === true
            : false)
      );
    },
    defaultExpiry(expiries, rows) {
      return defaultUsExpiry(expiries, rows, mode);
    },
    splitExpiries: splitUsExpiries,
    sortValue(row, key) {
      return key === "expiry" ? row.expiration_date : row[key];
    },
    periodParts(row, spot) {
      const relative =
        finite(row?.strike) && row.strike > 0 && finite(spot) && spot > 0
          ? (row.strike / spot - 1) * 100
          : null;
      return { relative, value: row?.period_return_pct, showRelative: true };
    },
    annualHtml(row) {
      return percent(row?.annualized_pct);
    },
    probabilityHtml(row) {
      return percent(row?.exercise_probability_pct, 1);
    },
    expiryDetail(row) {
      const value = Date.parse(row?.expires_at_utc);
      if (!Number.isFinite(value)) return row?.expiration_date || "—";
      const parts = new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).formatToParts(new Date(value));
      const get = (type) =>
        parts.find((part) => part.type === type)?.value || "";
      return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
    },
    expiryDetailFor(value, rows = []) {
      const matching = rows.filter((row) => row.expiration_date === value),
        instants = new Set(
          matching.map((row) => Date.parse(row.expires_at_utc)),
        );
      if (instants.size !== 1) return "—";
      return this.expiryDetail(matching[0]);
    },
    snapshotVersion(snapshot) {
      return snapshot?.snapshot_version;
    },
    status(snapshot) {
      const healthy =
          snapshot?.state === "ready" && snapshot?.fetch_health === "healthy",
        abnormal =
          ["degraded", "stale", "error"].includes(snapshot?.state) ||
          ["stale", "failed"].includes(snapshot?.fetch_health);
      const seconds = finite(snapshot?.next_refresh_seconds)
        ? `${Math.ceil(snapshot.next_refresh_seconds)}秒`
        : "—";
      const countdown =
        {
          refreshing: "刷新中",
          queued: "排队中",
          waiting: seconds,
          cooldown: `限流等待 · ${seconds}`,
          inactive: "未激活",
        }[snapshot?.schedule_state] || snapshot?.next_refresh_seconds;
      return {
        market:
          snapshot?.market_status === "OPEN"
            ? "盘中"
            : snapshot?.market_status === "CLOSED"
              ? "休市"
              : "未确认",
        health: healthy ? "healthy" : abnormal ? "error" : "unknown",
        fetchedAt: snapshot?.fetched_at,
        countdown,
        notice: snapshot?.error || "",
      };
    },
    release() {
      if (!symbol) return;
      fetch(url(false), { cache: "no-store", keepalive: true }).catch(() => {});
    },
  };
}
