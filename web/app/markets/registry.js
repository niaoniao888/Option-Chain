import { createBitcoinAdapter } from "./bitcoin.js";
import { createUsAdapter } from "./us-equities.js";

const factories = new Map([
  ["bitcoin", { factory: createBitcoinAdapter, label: "BTC期权" }],
  ["us-equities", { factory: createUsAdapter, label: "美股期权" }],
]);

export function registerMarketAdapter(
  market,
  factory,
  { label = market } = {},
) {
  if (!market || typeof factory !== "function")
    throw new TypeError("market adapter is required");
  factories.set(market, { factory, label });
}

export const hasMarketAdapter = (market) => factories.has(market);
export const marketLabel = (market) => factories.get(market)?.label || market;

export function routeContext(pathname = location.pathname) {
  const parts = pathname.split("/").filter(Boolean);
  const candidateMode = parts.at(-1);
  const hasMode = candidateMode === "desktop" || candidateMode === "mobile";
  const mode = hasMode ? candidateMode : "desktop";
  const market = hasMode && parts.length > 1 ? parts.at(-2) : "bitcoin";
  const baseParts = hasMode ? parts.slice(0, -2) : [];
  return {
    market,
    mode,
    basePath: baseParts.length ? `/${baseParts.join("/")}` : "",
  };
}

export function createMarketAdapter(context, options = {}) {
  const registration = factories.get(context.market);
  if (!registration) throw new Error(`未注册市场前端适配器：${context.market}`);
  return registration.factory({ ...context, ...options });
}
