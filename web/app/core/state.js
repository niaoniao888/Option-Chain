const VIEWS = new Set(["chain", "price", "ranking"]);
const SIDES = new Set(["CALL", "PUT"]);
const RANGES = new Set(["LT3", "3_7", "7_30", "30_60", "GT60"]);
const SORTS = new Set([
  "expiry",
  "strike",
  "period_return_pct",
  "annualized_pct",
  "exercise_probability_pct",
  "remaining_seconds",
  "expiry_time",
]);

const canonicalSortKey = (key) =>
  key === "remaining_seconds"
    ? "expiry_time"
    : key === "delta"
      ? "exercise_probability_pct"
      : ["expiration_date", "expiry_ms"].includes(key)
        ? "expiry"
        : key;

export function safeGet(storage, key) {
  try {
    return storage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}
export function safeSet(storage, key, value) {
  try {
    storage?.setItem(key, value);
  } catch {
    /* storage is optional */
  }
}
export function readJson(storage, key) {
  try {
    const value = JSON.parse(safeGet(storage, key) || "null");
    return value && typeof value === "object" && !Array.isArray(value)
      ? value
      : {};
  } catch {
    return {};
  }
}
export function browserStorage(scope = globalThis) {
  try {
    return scope.localStorage;
  } catch {
    return null;
  }
}

export function stateKey({
  market,
  provider = "unknown",
  instrument = "default",
  mode,
}) {
  return `options-panel-ui:v2:${market}:${provider}:${instrument}:${mode}`;
}

export function normalizeUi(input = {}) {
  const positive = (value) =>
    typeof value === "number" && Number.isFinite(value) && value > 0
      ? value
      : null;
  const migrateSort = (sort) =>
    sort ? { ...sort, key: canonicalSortKey(sort.key) } : sort;
  const priceSort = migrateSort(input.priceSort);
  const rankSort = migrateSort(input.rankSort || input.rankingSort);
  const legacyRankKey = canonicalSortKey(input.rankingSortKey);
  return {
    view: VIEWS.has(input.view || input.mobileView)
      ? input.view || input.mobileView
      : "chain",
    selectedExpiry: input.selectedExpiry ?? null,
    priceSide: SIDES.has(input.priceSide) ? input.priceSide : "CALL",
    priceStrikes: {
      CALL: positive(input.priceStrikes?.CALL),
      PUT: positive(input.priceStrikes?.PUT),
    },
    priceGroups: {
      CALL:
        typeof input.priceGroups?.CALL === "string"
          ? input.priceGroups.CALL
          : null,
      PUT:
        typeof input.priceGroups?.PUT === "string"
          ? input.priceGroups.PUT
          : null,
    },
    rankingSide: SIDES.has(input.rankingSide || input.sideFilter)
      ? input.rankingSide || input.sideFilter
      : "CALL",
    rankingRange: RANGES.has(input.rankingRange || input.termFilter)
      ? input.rankingRange || input.termFilter
      : "LT3",
    priceSort:
      priceSort &&
      SORTS.has(priceSort.key) &&
      ["asc", "desc"].includes(priceSort.direction)
        ? priceSort
        : { key: "expiry", direction: "asc" },
    rankSort:
      rankSort &&
      SORTS.has(rankSort.key) &&
      ["asc", "desc"].includes(rankSort.direction)
        ? rankSort
        : {
            key: SORTS.has(legacyRankKey) ? legacyRankKey : "annualized_pct",
            direction: ["asc", "desc"].includes(input.rankingSortDirection)
              ? input.rankingSortDirection
              : "desc",
          },
    rankingPage:
      Number.isInteger(input.rankingPage) && input.rankingPage > 0
        ? input.rankingPage
        : 1,
    farExpiriesOpen: input.farExpiriesOpen === true,
  };
}

export function loadUi(storage, context) {
  const key = stateKey(context);
  const current = readJson(storage, key);
  if (Object.keys(current).length) return { key, value: normalizeUi(current) };
  let legacy = {};
  if (
    context.market === "bitcoin" &&
    context.provider === "binance" &&
    context.mode === "mobile"
  ) {
    legacy = readJson(storage, "btc-options-mobile-ui-v1");
    legacy.view ||= safeGet(storage, "btc-options-mobile-view");
  } else if (
    context.market === "us-equities" &&
    context.provider === "alpaca"
  ) {
    legacy = readJson(storage, `us-options-filters:${context.instrument}`);
    legacy.view ||= safeGet(storage, "us-options-mobile-view");
  }
  const value = normalizeUi(legacy);
  safeSet(storage, key, JSON.stringify(value));
  return { key, value };
}

export function saveUi(storage, key, value) {
  safeSet(storage, key, JSON.stringify(normalizeUi(value)));
}
export const selectedUsSymbol = (storage) =>
  safeGet(storage, "us-options-selected-symbol");
export const saveUsSymbol = (storage, symbol) =>
  safeSet(storage, "us-options-selected-symbol", symbol || "");

export function applySort(currentState, sortName, key) {
  const sort = currentState[sortName];
  key = canonicalSortKey(key);
  if (sort.key === key)
    sort.direction = sort.direction === "asc" ? "desc" : "asc";
  else
    Object.assign(sort, {
      key,
      direction:
        key === "expiry_time" || (sortName === "priceSort" && key === "expiry")
          ? "asc"
          : "desc",
    });
  currentState.rankingPage = 1;
  return sort;
}
