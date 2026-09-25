"use strict";
// One presentation contract for chain, price comparison, ranking and future views.
// The premium return is supplied by the backend snapshot; never recalculate it here.
(() => {
  const number = value => value.toLocaleString("zh-CN", {minimumFractionDigits:2, maximumFractionDigits:2});
  function model(contract, indexPrice) {
    if (!contract || contract.open_interest === 0) return null;
    const premium = contract.time_value_status === "positive" && Number.isFinite(contract.period_return_pct)
      ? contract.period_return_pct : null;
    const showDistance = contract.side !== "PUT";
    let distance = null;
    if (showDistance && Number.isFinite(indexPrice) && indexPrice > 0 && Number.isFinite(contract.strike) && contract.strike > 0) {
      const value = (contract.strike / indexPrice - 1) * 100;
      if (Number.isFinite(value)) distance = value;
    }
    return {premium, distance, showDistance};
  }
  function render(contract, indexPrice) {
    const value = model(contract, indexPrice);
    if (!value) return "—";
    const premium = value.premium === null ? "—" : `${number(value.premium)}%`;
    // A figure space reserves a sign position without changing the numeric value.
    const pad = value.showDistance && value.premium !== null && value.premium >= 0 && !Object.is(value.premium,-0) ? "\u2007" : "";
    const income = `<span class="period-return" title="单期收益">${pad}${premium}</span>`;
    if (!value.showDistance) return `<span class="period-metric">${income}</span>`;
    const tone = value.distance === null || Math.abs(value.distance) < 1e-12 ? "neutral" : value.distance > 0 ? "positive" : "negative";
    const distance = value.distance === null ? "—" : `${value.distance > 0 ? "+" : ""}${number(value.distance)}%`;
    return `<span class="period-metric"><span class="period-distance ${tone}" title="行权价距现价">${distance}</span>${income}</span>`;
  }
  globalThis.OptionsPeriodReturn = Object.freeze({model, render});
})();
