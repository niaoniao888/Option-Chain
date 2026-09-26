import { fetchJson } from "../core/polling.js";
import { date, finite, number, percent } from "../core/formats.js";

/**
 * Build the BTC display adapter. The adapter selects and formats existing server
 * fields; it never recalculates annualized return or exercise probability.
 * @param {{basePath?: string, mode: "desktop"|"mobile"}} options
 */

export function projectBitcoinSnapshot(source, nowMs) {
  if (!source || typeof source !== "object") return source;
  const snapshot = { ...source, status: { ...(source.status || {}) } };
  snapshot.contracts = (source.contracts || []).map((raw) => {
    const row = { ...raw };
    const remaining = Math.max(0, (Number(row.expiry_ms) - nowMs) / 1000);
    row.remaining_seconds = remaining;
    if (remaining <= 0)
      Object.assign(row, {
        annualized_pct: null,
        period_return_pct: null,
        mark_annualized_pct: null,
        exercise_probability_pct: null,
        probability_display_state: "expired",
      });
    else if (finite(row.exercise_probability_pct) && remaining <= 1800)
      row.probability_display_state = "settling";
    return row;
  });
  const serverBase = Date.parse(source.server_time),
    elapsed = Number.isFinite(serverBase)
      ? Math.max(0, (nowMs - serverBase) / 1000)
      : 0;
  if (finite(source.next_refresh_seconds))
    snapshot.next_refresh_seconds = Math.max(
      0,
      source.next_refresh_seconds - elapsed,
    );
  if (finite(snapshot.status.age_seconds))
    snapshot.status.age_seconds = Math.max(
      0,
      snapshot.status.age_seconds + elapsed,
    );
  if (snapshot.status.age_seconds >= 120) {
    snapshot.status.stale = true;
    if (snapshot.status.status === "healthy")
      snapshot.status.status = "degraded";
  }
  return snapshot;
}

export function defaultBitcoinExpiry(expiries, nowMs) {
  const sorted = [...expiries]
    .filter((value) => Number(value) > nowMs)
    .sort((a, b) => a - b);
  const cutoff = nowMs + 15 * 86400 * 1000;
  return sorted.filter((value) => value <= cutoff).at(-1) ?? sorted[0] ?? null;
}

export function bitcoinRemaining(seconds) {
  if (!finite(seconds)) return "—";
  const safe = Math.max(0, seconds);
  if (safe > 3 * 86400) return `${Math.floor(safe / 86400)}天`;
  const hours = Math.floor(safe / 3600);
  return `${Math.floor(hours / 24)}天${hours % 24}小时`;
}

export function bitcoinMobileRemaining(seconds) {
  if (!finite(seconds)) return "—";
  const safe = Math.max(0, seconds);
  if (safe < 3600) return "不足1小时";
  if (safe < 86400) return `${Math.floor(safe / 3600)}小时`;
  return `${Math.floor(safe / 86400)}天`;
}

function shanghaiDateTime(value) {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(Number(value)));
  const get = (type) => parts.find((part) => part.type === type)?.value || "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}

export function createBitcoinAdapter({ basePath = "", mode }) {
  let source = null,
    localError = null;
  return {
    id: "bitcoin",
    mode,
    provider: "binance",
    defaultProvider: "binance",
    navigationLabel: "BTC期权",
    title: "BTC 期权看板",
    symbol: "BTC",
    currency: "USDT",
    footer: "数据来源：币安 Binance Options EAPI",
    footerUrl:
      "https://developers.binance.com/docs/derivatives/option/market-data",
    supportsSymbols: false,
    showMarketStatus: false,
    priceDigits: 0,
    parseExpiryId: Number,
    expiryLabel: (value) => date(value),
    expiryDetailFor: (value) => shanghaiDateTime(value),
    remainingText: bitcoinRemaining,
    mobileRemainingText: bitcoinMobileRemaining,
    strikeGroups(strikes) {
      const grouped = new Map();
      for (const strike of strikes) {
        const start = Math.floor(strike / 10000) * 10000;
        const id = String(start);
        if (!grouped.has(id))
          grouped.set(id, {
            id,
            label: `${number(start / 10000, 0)}万`,
            strikes: [],
          });
        grouped.get(id).strikes.push(strike);
      }
      return [...grouped.values()];
    },
    chainTone(side, strike, spot) {
      if (!finite(spot) || !finite(strike)) return "";
      if (strike === spot) return "atm";
      const itm = side === "CALL" ? strike < spot : strike > spot;
      return itm ? "itm" : "otm";
    },
    rankingColumns: [
      "expiry",
      "strike",
      "period_return_pct",
      "annualized_pct",
      "exercise_probability_pct",
    ],
    priceAnnualLabel(side) {
      return `${side === "CALL" ? "Covered Call" : "Sell Put"}<br>年化`;
    },
    async initialize() {
      return null;
    },
    async request(signal) {
      source = await fetchJson(`${basePath}/api/v1/bitcoin/snapshot`, {
        signal,
      });
      return source;
    },
    merge(payload) {
      localError = null;
      source = payload;
      return payload;
    },
    setLocalError(message) {
      localError = message || "读取失败";
    },
    project(nowMs) {
      const snapshot = projectBitcoinSnapshot(source, nowMs);
      if (snapshot && localError) {
        snapshot.status = {
          ...(snapshot.status || {}),
          status: "degraded",
          market_error: localError,
        };
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
      return row.expiry_ms;
    },
    contractId(row) {
      return row.symbol;
    },
    displayable(row) {
      return row.remaining_seconds > 0;
    },
    priceEligible(row) {
      return (
        row.remaining_seconds > 0 &&
        row.time_value_status !== "negative" &&
        row.open_interest !== 0 &&
        finite(row.annualized_pct)
      );
    },
    rankingEligible(row) {
      return (
        row.remaining_seconds > 0 &&
        row.time_value_status === "positive" &&
        row.open_interest !== 0 &&
        finite(row.annualized_pct)
      );
    },
    defaultExpiry(expiries, rows, nowMs) {
      const remaining = new Map(
        rows.map((row) => [row.expiry_ms, row.remaining_seconds]),
      );
      const within = expiries.filter(
        (value) =>
          finite(remaining.get(value)) &&
          remaining.get(value) > 0 &&
          remaining.get(value) <= 15 * 86400,
      );
      return (
        within.at(-1) ??
        expiries.find((value) => remaining.get(value) > 0) ??
        defaultBitcoinExpiry(expiries, nowMs)
      );
    },
    snapshotVersion(snapshot) {
      return snapshot?.market_generation_ms ?? snapshot?.fetched_at;
    },
    sortValue(row, key) {
      return key === "expiry"
        ? row.expiry_ms
        : key === "exercise_probability_pct" &&
            row.probability_display_state === "settling"
          ? null
          : row[key];
    },
    periodParts(row, spot) {
      const relative =
        finite(row?.strike) && row.strike > 0 && finite(spot) && spot > 0
          ? (row.strike / spot - 1) * 100
          : null;
      return {
        unavailable: row?.open_interest === 0,
        relative,
        value:
          row?.open_interest === 0 || row?.time_value_status !== "positive"
            ? null
            : row?.period_return_pct,
        showRelative: row?.side === "CALL",
      };
    },
    annualHtml(row) {
      if (row?.open_interest === 0) return "—";
      if (["negative", "zero"].includes(row?.time_value_status)) {
        const label =
          row.time_value_status === "negative"
            ? "Bid &lt; 内在价值"
            : "Bid = 内在价值";
        const value = !finite(row.time_value)
          ? "—"
          : row.time_value === 0
            ? "0.00"
            : Math.abs(row.time_value) < 0.01
              ? `${row.time_value < 0 ? "-" : ""}&lt;0.01`
              : number(row.time_value, 2);
        const mark = finite(row.mark_annualized_pct)
          ? ` · <span class="mark-value">Mark ${number(row.mark_annualized_pct, 1)}%</span>`
          : "";
        return `<span class="tv-warning">${label}<small>TV ${value}${mark}</small></span>`;
      }
      return percent(row?.annualized_pct);
    },
    probabilityHtml(row) {
      if (row?.open_interest === 0) return "—";
      if (row?.probability_display_state === "settling") return "结算中";
      const value = row?.exercise_probability_pct;
      if (!finite(value)) return "—";
      if (value < 0.1) return "&lt;0.1%";
      if (value > 99.9) return "&gt;99.9%";
      return percent(value, 1);
    },
    status(snapshot) {
      const status = snapshot?.status || {},
        hasSnapshot = Boolean(snapshot?.fetched_at),
        error = [
          status.market_error,
          status.catalog_error,
          status.mark_warning,
        ].filter(Boolean);
      const abnormal =
        hasSnapshot &&
        (["degraded", "error"].includes(status.status) ||
          status.stale === true ||
          error.length > 0);
      const healthy = hasSnapshot && status.status === "healthy" && !abnormal;
      return {
        market: "连续交易",
        health: healthy ? "healthy" : abnormal ? "error" : "unknown",
        fetchedAt: snapshot?.fetched_at,
        countdown: hasSnapshot ? snapshot?.next_refresh_seconds : null,
        notice: error.join("；"),
      };
    },
    release() {},
  };
}
