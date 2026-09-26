import {
  compactDateHtml,
  dateTime,
  escapeHtml,
  finite,
  number,
  percent,
  remaining,
} from "../core/formats.js";
import { renderMenuOptions } from "./menu.js";

export const termMatches = (seconds, bucket) =>
  bucket === "LT3"
    ? seconds < 3 * 86400
    : bucket === "3_7"
      ? seconds >= 3 * 86400 && seconds < 7 * 86400
      : bucket === "7_30"
        ? seconds >= 7 * 86400 && seconds < 30 * 86400
        : bucket === "30_60"
          ? seconds >= 30 * 86400 && seconds <= 60 * 86400
          : seconds > 60 * 86400;
export function sortNullLast(rows, sort, valueOf = (row, key) => row[key]) {
  return [...rows].sort((a, b) => {
    const av = valueOf(a, sort.key),
      bv = valueOf(b, sort.key),
      am = av == null || (typeof av === "number" && !finite(av)),
      bm = bv == null || (typeof bv === "number" && !finite(bv));
    if (am !== bm) return am ? 1 : -1;
    if (!am) {
      const cmp = typeof av === "string" ? av.localeCompare(bv, "en") : av - bv;
      if (cmp) return sort.direction === "asc" ? cmp : -cmp;
    }
    return String(a.symbol || a.contract_symbol).localeCompare(
      String(b.symbol || b.contract_symbol),
      "en",
    );
  });
}
export function paginationItems(current, pages) {
  if (pages <= 7) return Array.from({ length: pages }, (_, index) => index + 1);
  const values = new Set([1, pages, current - 1, current, current + 1]);
  const ordered = [...values]
      .filter((value) => value >= 1 && value <= pages)
      .sort((a, b) => a - b),
    out = [];
  for (const value of ordered) {
    if (out.length && value - out.at(-1) > 1) out.push("ellipsis");
    out.push(value);
  }
  return out;
}
export function resolvedRankingPage(requested, pages, hasEligibleRows) {
  if (!hasEligibleRows) return { displayPage: 1, storedPage: requested };
  const page = Math.min(Math.max(1, requested), pages);
  return { displayPage: page, storedPage: page };
}
export function groupByStrike(rows) {
  const grouped = new Map();
  for (const row of rows) {
    if (!grouped.has(row.strike))
      grouped.set(row.strike, { CALL: [], PUT: [] });
    grouped.get(row.strike)?.[row.side]?.push(row);
  }
  return grouped;
}
const metric = (row, key, digits = 2) =>
  row.probability_display_state === "settling" &&
  key === "exercise_probability_pct"
    ? "结算中"
    : key.includes("pct")
      ? percent(row[key], digits)
      : number(row[key], digits);
const expiryLabel = (adapter, value, rows = []) =>
  adapter.expiryLabel?.(value, rows) ?? String(value);
const digits = (adapter) => adapter.priceDigits ?? 2;
const remainingText = (adapter, seconds) =>
  adapter.remainingText?.(seconds) ?? remaining(seconds);
export function partitionStrikes(strikes, spot) {
  const sorted = [...new Set(strikes.filter(finite))].sort((a, b) => a - b);
  if (!finite(spot)) return { lower: sorted, higher: [], atMoney: null };
  const atMoney = sorted.includes(spot) ? spot : null;
  return {
    lower: sorted.filter((strike) => strike < spot || strike === atMoney),
    higher: sorted.filter((strike) => strike > spot),
    atMoney,
  };
}
const rankingLabels = {
  expiry: "到期日",
  strike: "行权价",
  period_return_pct:
    '<span class="desktop-label">单期收益率</span><span class="mobile-label">单期收益</span>',
  annualized_pct: "年化",
  exercise_probability_pct: "行权概率",
  remaining_seconds: "剩余时间",
  expiry_time: "到期时间",
};
const expiryTimeHtml = (adapter, row) => {
  const text = adapter.expiryDetail?.(row) ?? "—",
    match = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})$/.exec(text);
  return match
    ? `<span class="expiry-time"><span>${match[1]}</span> <span>${match[2]}</span></span>`
    : escapeHtml(text);
};
const annualMetric = (adapter, row) =>
  adapter.annualHtml?.(row) ?? percent(row?.annualized_pct);
const probabilityMetric = (adapter, row) =>
  adapter.probabilityHtml?.(row) ?? percent(row?.exercise_probability_pct, 1);
const periodMetric = (adapter, row, spot) => {
  if (!row) return "—";
  const parts = adapter.periodParts(row, spot);
  if (parts.unavailable) return "—";
  const relative = parts.showRelative
    ? `<span class="period-distance ${!finite(parts.relative) || Math.abs(parts.relative) < 1e-12 ? "neutral" : parts.relative > 0 ? "relative-up" : "relative-down"}">${finite(parts.relative) && parts.relative > 0 ? "+" : ""}${percent(parts.relative)}</span>`
    : "";
  const pad =
    parts.showRelative && finite(parts.value) && parts.value >= 0 ? " " : "";
  return `<span class="period-metric">${relative}<span class="period-return">${pad}${percent(parts.value)}</span></span>`;
};

export class Dashboard {
  constructor({ root, adapter, state, onState }) {
    Object.assign(this, { root, adapter, state, onState });
    this.snapshot = null;
    this.pending = false;
    this.pointer = false;
    this.$ = (id) => root.querySelector(`#${id}`);
  }
  protected() {
    const selection = getSelection?.();
    return (
      this.pointer ||
      Boolean(selection && !selection.isCollapsed) ||
      Boolean(document.activeElement?.matches("input,textarea")) ||
      Boolean(this.root.querySelector(".picker-menu:not([hidden])"))
    );
  }
  projectionSignature(value) {
    return JSON.stringify([
      value?.state,
      value?.fetch_health,
      value?.mode,
      value?.index_price ?? value?.underlying_price,
      (value?.contracts || []).map((row) => [
        this.adapter.contractId(row),
        this.adapter.expiry(row),
        row.side,
        row.strike,
        row.annualized_pct,
        row.period_return_pct,
        row.exercise_probability_pct,
        row.calculation_status,
        row.probability_display_state,
        row.ranking_eligible,
        row.close_reference_eligible,
        remainingText(this.adapter, row.remaining_seconds),
      ]),
    ]);
  }
  expiryDetail(value, rows) {
    return (
      this.adapter.expiryDetailFor?.(value, rows) ??
      this.adapter.expiryDetail?.(
        rows.find((row) => this.adapter.expiry(row) === value),
      ) ??
      expiryLabel(this.adapter, value, rows)
    );
  }
  expirySummary(detail, seconds) {
    const separator = this.adapter.mode === "mobile" ? "\n" : " · ";
    return `到期时间：${detail}${separator}剩余 ${remainingText(this.adapter, seconds)}`;
  }
  needsFullRender(next, previous) {
    if (!previous) return true;
    const nextVersion = this.adapter.snapshotVersion?.(next);
    const previousVersion = this.adapter.snapshotVersion?.(previous);
    if (nextVersion != null || previousVersion != null)
      return (
        nextVersion !== previousVersion ||
        this.projectionSignature(next) !== this.projectionSignature(previous)
      );
    return (
      this.projectionSignature(next) !== this.projectionSignature(previous)
    );
  }
  setSnapshot(snapshot, force = false) {
    const changed = force || this.needsFullRender(snapshot, this.snapshot);
    this.snapshot = snapshot;
    this.renderStatus();
    if (!changed) {
      this.updateExpiryDetail();
      return;
    }
    if (this.protected()) {
      this.pending = true;
      this.$("pending").hidden = false;
      return;
    }
    this.pending = false;
    this.$("pending").hidden = true;
    this.render();
  }
  updateProjection(snapshot) {
    this.setSnapshot(snapshot);
  }
  updateExpiryDetail() {
    const rows = this.rows(),
      selected = rows.find(
        (row) => this.adapter.expiry(row) === this.state.selectedExpiry,
      ),
      detail = selected
        ? this.expiryDetail(this.state.selectedExpiry, rows)
        : null;
    this.$("expiryDetail").textContent = selected
      ? this.expirySummary(detail, selected.remaining_seconds)
      : "没有有效到期日";
  }
  flush() {
    if (this.pending && !this.protected())
      this.setSnapshot(this.snapshot, true);
  }
  rows() {
    return (this.snapshot?.contracts || []).filter((row) =>
      this.adapter.displayable(row),
    );
  }
  expiries(rows = this.rows()) {
    return [
      ...new Set(rows.map((row) => this.adapter.expiry(row)).filter(Boolean)),
    ].sort((a, b) => (a > b ? 1 : -1));
  }
  ensureSelections() {
    this.state.priceGroups ||= { CALL: null, PUT: null };
    const rows = this.rows(),
      expiries = this.expiries(rows),
      now = Date.now();
    if (!expiries.includes(this.state.selectedExpiry))
      this.state.selectedExpiry = this.adapter.defaultExpiry(
        expiries,
        rows,
        now,
      );
    const priceRows = rows.filter(
        (row) => this.adapter.priceEligible?.(row) ?? true,
      ),
      sides = { CALL: [], PUT: [] };
    priceRows.forEach((row) => {
      if (sides[row.side] && !sides[row.side].includes(row.strike))
        sides[row.side].push(row.strike);
    });
    Object.values(sides).forEach((values) => values.sort((a, b) => a - b));
    const saved = this.state.priceStrikes[this.state.priceSide],
      spot = this.snapshot?.index_price ?? this.snapshot?.underlying_price,
      choices = sides[this.state.priceSide];
    if (!choices.includes(saved)) {
      const strike =
        choices.length && finite(spot)
          ? choices.reduce((best, x) =>
              Math.abs(x - spot) < Math.abs(best - spot) ? x : best,
            )
          : (choices[0] ?? null);
      this.state.priceStrikes[this.state.priceSide] = strike;
    }
    const groups = this.adapter.strikeGroups?.(choices) || [
        { id: "all", label: "全部", strikes: choices },
      ],
      selectedStrike = this.state.priceStrikes[this.state.priceSide],
      selectedGroup = groups.find((group) =>
        group.strikes.includes(selectedStrike),
      ),
      storedGroup = groups.find(
        (group) => group.id === this.state.priceGroups[this.state.priceSide],
      );
    if (!storedGroup)
      this.state.priceGroups[this.state.priceSide] =
        selectedGroup?.id ?? groups[0]?.id ?? null;
    this.onState();
    return { rows, expiries, sides, groups };
  }
  renderStatus() {
    const info = this.adapter.status(this.snapshot),
      price = this.snapshot?.index_price ?? this.snapshot?.underlying_price;
    this.$("title").textContent = this.adapter.title;
    this.root
      .querySelectorAll("[data-quote-symbol]")
      .forEach(
        (node) =>
          (node.textContent =
            this.adapter.symbolLabel?.(this.adapter.symbol) ||
            this.adapter.symbol ||
            "—"),
      );
    this.root
      .querySelectorAll("[data-quote-price]")
      .forEach(
        (node) => (node.textContent = number(price, digits(this.adapter))),
      );
    this.$("marketStatusItem").hidden = !this.adapter.showMarketStatus;
    this.$("marketStatus").textContent = info.market;
    this.$("dataTime").textContent = dateTime(info.fetchedAt);
    this.$("countdown").textContent = finite(info.countdown)
      ? `${Math.ceil(info.countdown)}秒`
      : typeof info.countdown === "string"
        ? info.countdown
        : "—";
    this.$("health").textContent =
      info.health === "healthy"
        ? "正常"
        : info.health === "error"
          ? "异常"
          : "等待校对";
    this.$("health").dataset.tone = info.health;
    this.$("notice").textContent = info.notice || "";
    this.$("notice").hidden = !info.notice;
  }
  render() {
    if (!this.snapshot) return;
    const { rows, expiries } = this.ensureSelections();
    this.renderTabs();
    this.root
      .querySelectorAll("[data-price-side]")
      .forEach((button) =>
        button.classList.toggle(
          "active",
          button.dataset.priceSide === this.state.priceSide,
        ),
      );
    this.root
      .querySelectorAll("[data-ranking-side]")
      .forEach((button) =>
        button.classList.toggle(
          "active",
          button.dataset.rankingSide === this.state.rankingSide,
        ),
      );
    this.root
      .querySelectorAll("[data-range]")
      .forEach((button) =>
        button.classList.toggle(
          "active",
          button.dataset.range === this.state.rankingRange,
        ),
      );
    this.renderExpiry(expiries, rows);
    this.renderChain(rows);
    this.renderPrice(rows);
    this.renderRanking(rows);
  }
  renderTabs() {
    this.root.querySelectorAll("[data-view]").forEach((button) => {
      const active = button.dataset.view === this.state.view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    this.root
      .querySelectorAll("[data-panel]")
      .forEach(
        (panel) => (panel.hidden = panel.dataset.panel !== this.state.view),
      );
  }
  renderExpiry(expiries, rows) {
    this.$("expiryValue").textContent = this.state.selectedExpiry
      ? expiryLabel(this.adapter, this.state.selectedExpiry, rows)
      : "—";
    renderMenuOptions(
      this.$("expiryMenu"),
      expiries,
      this.state.selectedExpiry,
      (value) => {
        const matching = rows.filter(
            (row) => this.adapter.expiry(row) === value,
          ),
          seconds = matching.find((row) =>
            finite(row.remaining_seconds),
          )?.remaining_seconds,
          remain =
            this.adapter.mobileRemainingText?.(seconds) ??
            remainingText(this.adapter, seconds);
        return `${expiryLabel(this.adapter, value, rows)}（剩余${remain}）`;
      },
    );
    const selected = rows.find(
        (row) => this.adapter.expiry(row) === this.state.selectedExpiry,
      ),
      detail = selected
        ? this.expiryDetail(this.state.selectedExpiry, rows)
        : null;
    this.$("expiryDetail").textContent = selected
      ? this.expirySummary(detail, selected.remaining_seconds)
      : "没有有效到期日";
    const renderButton = (value) =>
        `<button data-expiry="${escapeHtml(value)}" aria-pressed="${value === this.state.selectedExpiry}">${escapeHtml(expiryLabel(this.adapter, value, rows))}</button>`,
      split = this.adapter.splitExpiries?.(
        expiries,
        this.adapter.todayForExpirySplit?.() ??
          new Date().toISOString().slice(0, 10),
      );
    const farOpen =
      split?.far.includes(this.state.selectedExpiry) ||
      this.state.farExpiriesOpen;
    this.$("expiryButtons").innerHTML = split
      ? `${split.near.map(renderButton).join("")}${split.far.length ? `<details id="farExpiries" ${farOpen ? "open" : ""}><summary>更远到期日（${split.far.length}）</summary><div>${split.far.map(renderButton).join("")}</div></details>` : ""}`
      : expiries.map(renderButton).join("");
    const farExpiries = this.$("farExpiries");
    if (farExpiries)
      farExpiries.ontoggle = () => {
        this.state.farExpiriesOpen = farExpiries.open;
        this.onState();
      };
  }
  renderChain(rows) {
    const selected = rows.filter(
        (row) => this.adapter.expiry(row) === this.state.selectedExpiry,
      ),
      grouped = groupByStrike(selected),
      strikes = [...grouped.keys()].sort((a, b) => a - b),
      all = (strike, side) => grouped.get(strike)?.[side] || [],
      cell = (items, render) =>
        items.length ? items.map(render).join("") : "—",
      spot = this.snapshot?.index_price ?? this.snapshot?.underlying_price,
      validSpot = finite(spot) && spot > 0,
      divider = () =>
        `<tr class="spot-divider"><td colspan="3"></td><td class="sticky-strike"><span>现价 <b>${number(spot, digits(this.adapter))}</b></span></td><td colspan="3"></td></tr>`;
    let crossed = false;
    const rendered = [];
    for (const strike of strikes) {
      if (validSpot && !crossed && strike > spot) {
        rendered.push(divider());
        crossed = true;
      }
      const calls = all(strike, "CALL"),
        puts = all(strike, "PUT"),
        relative = validSpot ? (strike / spot - 1) * 100 : null,
        atSpot = validSpot && strike === spot;
      if (atSpot) crossed = true;
      const callTone = this.adapter.chainTone?.("CALL", strike, spot) || "",
        putTone = this.adapter.chainTone?.("PUT", strike, spot) || "",
        strikeTone = atSpot
          ? "atm"
          : validSpot && strike < spot
            ? "below"
            : validSpot
              ? "above"
              : "";
      rendered.push(
        `<tr><td class="${callTone}">${cell(calls, (row) => probabilityMetric(this.adapter, row))}</td><td class="${callTone}">${cell(calls, (row) => periodMetric(this.adapter, row, spot))}</td><td class="${callTone}">${cell(calls, (row) => annualMetric(this.adapter, row))}</td><td class="sticky-strike ${strikeTone}"><span>${number(strike, digits(this.adapter))}</span>${finite(relative) ? `<small class="${relative < 0 ? "relative-down" : relative > 0 ? "relative-up" : ""}">${relative >= 0 ? "+" : ""}${percent(relative)}</small>` : ""}${atSpot ? `<span class="spot-badge">现价 <b>${number(spot, digits(this.adapter))}</b></span>` : ""}</td><td class="${putTone}">${cell(puts, (row) => annualMetric(this.adapter, row))}</td><td class="${putTone}">${cell(puts, (row) => periodMetric(this.adapter, row, spot))}</td><td class="${putTone}">${cell(puts, (row) => probabilityMetric(this.adapter, row))}</td></tr>`,
      );
    }
    if (validSpot && strikes.length && !crossed) rendered.push(divider());
    this.$("chainBody").innerHTML =
      rendered.join("") ||
      '<tr><td colspan="7">该到期日没有可显示合约</td></tr>';
  }
  renderPrice(rows) {
    const eligible = rows.filter(
        (row) => this.adapter.priceEligible?.(row) ?? true,
      ),
      strike = this.state.priceStrikes[this.state.priceSide],
      selected = eligible.filter(
        (row) => row.side === this.state.priceSide && row.strike === strike,
      ),
      sorted = sortNullLast(selected, this.state.priceSort, (row, key) =>
        this.adapter.sortValue(row, key),
      ),
      spot = this.snapshot?.index_price ?? this.snapshot?.underlying_price;
    this.$("priceAnnualLabel").innerHTML =
      this.adapter.priceAnnualLabel?.(this.state.priceSide) ?? "年化";
    this.$("strikeValue").textContent = finite(strike)
      ? number(strike, digits(this.adapter))
      : "—";
    const strikes = [
      ...new Set(
        eligible
          .filter((row) => row.side === this.state.priceSide)
          .map((row) => row.strike),
      ),
    ].sort((a, b) => a - b);
    this.$("currentStrike").textContent = finite(strike)
      ? number(strike, digits(this.adapter))
      : "—";
    this.$("currentStrike").className =
      finite(strike) && finite(spot)
        ? strike > spot
          ? "relative-up"
          : strike < spot
            ? "relative-down"
            : "neutral"
        : "neutral";
    this.$("currentStrikeLabel").className =
      `current-strike ${this.$("currentStrike").className}`;
    renderMenuOptions(this.$("strikeMenu"), strikes, strike, (value) => {
      const relative =
        finite(spot) && spot > 0 ? (value / spot - 1) * 100 : null;
      return {
        primary: number(value, digits(this.adapter)),
        secondary: finite(relative)
          ? `（${relative >= 0 ? "+" : ""}${percent(relative)}）`
          : "",
        tone: !finite(relative)
          ? ""
          : relative > 0
            ? "relative-up"
            : relative < 0
              ? "relative-down"
              : "neutral",
      };
    });
    const groups = this.adapter.strikeGroups?.(strikes) || [
        { id: "all", label: "全部", strikes },
      ],
      selectedGroupId = this.state.priceGroups[this.state.priceSide],
      selectedGroup =
        groups.find((group) => group.id === selectedGroupId) || groups[0];
    this.$("strikeGroupButtons").innerHTML = groups
      .map(
        (group) =>
          `<button data-strike-group="${escapeHtml(group.id)}" aria-pressed="${group.id === selectedGroup?.id}">${escapeHtml(group.label)}</button>`,
      )
      .join("");
    const partitions = partitionStrikes(selectedGroup?.strikes || [], spot),
      strikeButton = (value) =>
        `<button class="${value === partitions.atMoney ? "atm" : ""}" data-strike="${value}" aria-pressed="${value === strike}"><span>${number(value, digits(this.adapter))}</span>${value === partitions.atMoney ? "<small>平值</small>" : ""}</button>`,
      row = (label, values, tone) =>
        values.length
          ? `<div class="strike-option-row ${tone}"><b>${label}</b><div>${values.map(strikeButton).join("")}</div></div>`
          : "";
    this.$("strikeButtons").innerHTML =
      row(
        !finite(spot)
          ? "行权价"
          : partitions.atMoney != null
            ? "低于 / 等于现价"
            : "低于现价",
        partitions.lower,
        "low",
      ) + row(finite(spot) ? "高于现价" : "行权价", partitions.higher, "high");
    this.$("priceBody").innerHTML =
      sorted
        .map(
          (row) =>
            `<tr><td>${compactDateHtml(expiryLabel(this.adapter, this.adapter.expiry(row), rows))}</td><td>${annualMetric(this.adapter, row)}</td><td>${periodMetric(this.adapter, row, spot)}</td><td>${probabilityMetric(this.adapter, row)}</td><td>${expiryTimeHtml(this.adapter, row)}</td></tr>`,
        )
        .join("") ||
      '<tr><td colspan="5">该方向与行权价暂无可显示指标</td></tr>';
    this.sortHeaders("priceHead", this.state.priceSort);
  }
  renderRanking(rows) {
    const columns = this.adapter.rankingColumns;
    const annualLabel = `${this.state.rankingSide === "PUT" ? "Sell Put" : "Covered Call"}<br>年化`;
    this.$("rankingHeadRow").innerHTML = columns
      .map(
        (key) =>
          `<th><button data-sort="${key}">${key === "annualized_pct" ? annualLabel : rankingLabels[key] || key} <span class="arrow"></span></button></th>`,
      )
      .join("");
    const eligible = rows.filter(
        (row) =>
          row.side === this.state.rankingSide &&
          termMatches(row.remaining_seconds, this.state.rankingRange) &&
          this.adapter.rankingEligible(row, this.snapshot),
      ),
      sorted = sortNullLast(eligible, this.state.rankSort, (row, key) =>
        this.adapter.sortValue(row, key),
      ),
      pages = Math.max(1, Math.ceil(sorted.length / 10)),
      spot = this.snapshot?.index_price ?? this.snapshot?.underlying_price;
    const resolved = resolvedRankingPage(
      this.state.rankingPage,
      pages,
      sorted.length > 0,
    );
    this.state.rankingPage = resolved.storedPage;
    const displayPage = resolved.displayPage,
      page = sorted.slice((displayPage - 1) * 10, displayPage * 10);
    const cell = (row, key) => {
      if (key === "expiry")
        return compactDateHtml(
          expiryLabel(this.adapter, this.adapter.expiry(row), rows),
        );
      if (key === "strike") return number(row.strike, digits(this.adapter));
      if (key === "period_return_pct")
        return periodMetric(this.adapter, row, spot);
      if (key === "annualized_pct") return annualMetric(this.adapter, row);
      if (key === "exercise_probability_pct")
        return probabilityMetric(this.adapter, row);
      if (key === "remaining_seconds")
        return remainingText(this.adapter, row.remaining_seconds);
      if (key === "expiry_time") return expiryTimeHtml(this.adapter, row);
      return "—";
    };
    this.$("rankingBody").innerHTML =
      page
        .map(
          (row) =>
            `<tr>${columns.map((key) => `<td>${cell(row, key)}</td>`).join("")}</tr>`,
        )
        .join("") ||
      `<tr><td colspan="${columns.length}">没有符合条件的合约</td></tr>`;
    this.$("rankingPages").innerHTML = paginationItems(displayPage, pages)
      .map((item) =>
        item === "ellipsis"
          ? '<span class="page-ellipsis" aria-hidden="true">…</span>'
          : `<button data-page="${item}" aria-current="${item === displayPage ? "page" : "false"}">${item}</button>`,
      )
      .join("");
    this.$("rankingPrev").disabled = !sorted.length || displayPage <= 1;
    this.$("rankingNext").disabled = !sorted.length || displayPage >= pages;
    this.sortHeaders("rankingHead", this.state.rankSort);
  }
  sortHeaders(id, sort) {
    this.$(id)
      .querySelectorAll("[data-sort]")
      .forEach((button) => {
        const active = button.dataset.sort === sort.key;
        button.querySelector(".arrow").textContent = active
          ? sort.direction === "asc"
            ? "▲"
            : "▼"
          : "";
        button
          .closest("th")
          .setAttribute(
            "aria-sort",
            active
              ? sort.direction === "asc"
                ? "ascending"
                : "descending"
              : "none",
          );
      });
  }
}
