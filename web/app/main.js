import { Dashboard } from "./components/dashboard.js";
import { bindMenu } from "./components/menu.js";
import {
  errorMessage,
  fetchJson,
  PollingController,
  retryDelay,
  withTimeout,
} from "./core/polling.js";
import { createModel } from "./core/model.js";
import {
  applySort,
  browserStorage,
  loadUi,
  safeGet,
  safeSet,
  saveUi,
} from "./core/state.js";
import {
  createMarketAdapter,
  hasMarketAdapter,
  marketLabel,
  routeContext,
} from "./markets/registry.js";

const root = document.querySelector("#app"),
  storage = browserStorage(),
  context = routeContext();
const adapter = createMarketAdapter(context, { storage });
let state,
  storageKey,
  dashboard,
  poller,
  now = () => Date.now(),
  moduleMetadata = null,
  rawSnapshot = null,
  currentModel = null,
  localTimer = null,
  bootTimer = null;
let visibilityBound = false;
let uiBound = false;
let bootInFlight = false;
let initialized = false;
const persist = () => {
  if (storageKey) saveUi(storage, storageKey, state);
};

function marketUrl(market) {
  return `${context.basePath}/${market}/${context.mode}/`;
}
function renderMarketNavigation(modules) {
  const tabs = root.querySelector(".market-tabs");
  tabs.replaceChildren();
  for (const item of modules.filter((entry) => hasMarketAdapter(entry.id))) {
    const link = document.createElement("a");
    link.dataset.market = item.id;
    link.textContent = marketLabel(item.id);
    tabs.append(link);
  }
}
function renderSymbols(select, metadata) {
  select.replaceChildren();
  for (const symbol of metadata.symbols || []) {
    const option = document.createElement("option");
    option.value = symbol;
    option.textContent = symbol;
    option.selected = symbol === metadata.symbol;
    select.append(option);
  }
}
function setTheme(theme, persist = false) {
  const selected = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = selected;
  document
    .querySelectorAll("[data-theme]")
    .forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.theme === selected),
      ),
    );
  if (persist) safeSet(storage, "options-panel-theme", selected);
}
function sortClick(sortName) {
  return (event) => {
    const button = event.target.closest("[data-sort]");
    if (!button) return;
    applySort(state, sortName, button.dataset.sort);
    persist();
    dashboard.render();
  };
}

function bind() {
  if (uiBound) return;
  uiBound = true;
  document.querySelectorAll("[data-market]").forEach((link) => {
    link.href = marketUrl(link.dataset.market);
    link.classList.toggle("active", link.dataset.market === context.market);
    if (link.dataset.market === context.market)
      link.setAttribute("aria-current", "page");
  });
  document
    .querySelectorAll("[data-theme]")
    .forEach(
      (button) => (button.onclick = () => setTheme(button.dataset.theme, true)),
    );
  document.querySelectorAll("[data-view]").forEach(
    (button) =>
      (button.onclick = () => {
        state.view = button.dataset.view;
        persist();
        dashboard.render();
      }),
  );
  root.querySelector("#priceSides").onclick = (event) => {
    const button = event.target.closest("[data-price-side]");
    if (!button) return;
    state.priceSide = button.dataset.priceSide;
    persist();
    dashboard.render();
  };
  root.querySelector("#rankingSides").onclick = (event) => {
    const button = event.target.closest("[data-ranking-side]");
    if (!button) return;
    state.rankingSide = button.dataset.rankingSide;
    state.rankingPage = 1;
    persist();
    dashboard.render();
  };
  root.querySelector("#strikeGroupButtons").onclick = (event) => {
    const button = event.target.closest("[data-strike-group]");
    if (!button) return;
    state.priceGroups[state.priceSide] = button.dataset.strikeGroup;
    persist();
    dashboard.render();
  };
  root.querySelector("#strikeButtons").onclick = (event) => {
    const button = event.target.closest("[data-strike]");
    if (!button) return;
    state.priceStrikes[state.priceSide] = Number(button.dataset.strike);
    persist();
    dashboard.render();
  };
  root.querySelector("#rankingRanges").onclick = (event) => {
    const button = event.target.closest("[data-range]");
    if (!button) return;
    state.rankingRange = button.dataset.range;
    state.rankingPage = 1;
    persist();
    dashboard.render();
  };
  root.querySelector("#expiryButtons").onclick = (event) => {
    const button = event.target.closest("[data-expiry]");
    if (!button) return;
    state.selectedExpiry = adapter.parseExpiryId(button.dataset.expiry);
    persist();
    dashboard.render();
  };
  root.querySelector("#priceHead").onclick = sortClick("priceSort");
  root.querySelector("#rankingHead").onclick = sortClick("rankSort");
  root.querySelector("#rankingPages").onclick = (event) => {
    const button = event.target.closest("[data-page]");
    if (button) {
      state.rankingPage = Number(button.dataset.page);
      persist();
      dashboard.render();
    }
  };
  root.querySelector("#rankingPrev").onclick = () => {
    if (state.rankingPage > 1) {
      state.rankingPage--;
      persist();
      dashboard.render();
    }
  };
  root.querySelector("#rankingNext").onclick = () => {
    state.rankingPage++;
    persist();
    dashboard.render();
  };
  bindMenu({
    trigger: root.querySelector("#expiryTrigger"),
    menu: root.querySelector("#expiryMenu"),
    onSelect: (value) => {
      state.selectedExpiry = adapter.parseExpiryId(value);
      persist();
      dashboard.render();
    },
  });
  bindMenu({
    trigger: root.querySelector("#strikeTrigger"),
    menu: root.querySelector("#strikeMenu"),
    onSelect: (value) => {
      state.priceStrikes[state.priceSide] = Number(value);
      persist();
      dashboard.render();
    },
  });
  document.addEventListener(
    "pointerdown",
    () => (dashboard.pointer = true),
    true,
  );
  const release = () => {
    dashboard.pointer = false;
    setTimeout(() => dashboard.flush(), 0);
  };
  document.addEventListener("pointerup", release, true);
  document.addEventListener("pointercancel", release, true);
  document.addEventListener(
    "pointermove",
    (event) => {
      if (
        dashboard.pointer &&
        event.buttons === 0 &&
        event.pointerType !== "touch"
      )
        release();
    },
    true,
  );
  window.addEventListener("blur", release);
  document.addEventListener("selectionchange", () => dashboard.flush(), true);
  document.addEventListener(
    "focusout",
    () => setTimeout(() => dashboard.flush(), 0),
    true,
  );
  window.addEventListener("pagehide", () => adapter.release());
}

function bindVisibility() {
  if (visibilityBound) return;
  visibilityBound = true;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      adapter.release();
      poller?.hidden();
      if (bootTimer !== null) {
        clearTimeout(bootTimer);
        bootTimer = null;
      }
    } else if (initialized) {
      dashboard.updateProjection(adapter.project(now()));
      if (poller) poller.visible();
      else startPolling();
    } else {
      boot();
    }
  });
}

async function bootstrap() {
  if (bootTimer !== null) {
    clearTimeout(bootTimer);
    bootTimer = null;
  }
  setTheme(safeGet(storage, "options-panel-theme") || "light");
  const [modules, metadata] = await withTimeout((signal) =>
    Promise.all([
      fetchJson(`${context.basePath}/api/v1/modules`, { signal }),
      adapter.initialize(signal),
    ]),
  );
  moduleMetadata = modules.find((item) => item.id === adapter.id) || {};
  renderMarketNavigation(modules);
  adapter.provider = moduleMetadata.provider_id || "unknown";
  adapter.footer = `数据来源：${moduleMetadata.provider || "未确认"}`;
  if (adapter.supportsSymbols) {
    root.querySelector("#symbolBar").hidden = false;
    const select = root.querySelector("#symbolSelect");
    renderSymbols(select, metadata);
    select.onchange = () => {
      adapter.release();
      adapter.setSymbol(select.value);
      rawSnapshot = null;
      currentModel = null;
      initializeState();
      poller.stop();
      startPolling();
    };
  }
  initializeState();
  bind();
  if (!document.hidden) startPolling();
  if (localTimer === null)
    localTimer = setInterval(() => {
      if (!document.hidden && dashboard?.snapshot) {
        currentModel = createModel(rawSnapshot, adapter.project(now()));
        dashboard.updateProjection(currentModel.projected);
      }
    }, 1000);
}
function initializeState() {
  const instrument =
      adapter.symbol || moduleMetadata?.default_instrument || "default",
    loaded = loadUi(storage, {
      market: adapter.id,
      provider: adapter.provider,
      instrument,
      mode: context.mode,
    });
  state = loaded.value;
  storageKey = loaded.key;
  dashboard = new Dashboard({ root, adapter, state, onState: persist });
  root.className = `market-${adapter.id} mode-${context.mode}`;
  const footer = root.querySelector("#footer");
  footer.textContent = adapter.footer;
  const providerMatchesDefault = adapter.provider === adapter.defaultProvider;
  if (providerMatchesDefault && adapter.footerUrl)
    footer.href = adapter.footerUrl;
  else footer.removeAttribute("href");
}
function syncSymbols(metadata) {
  if (!metadata?.changed) return;
  if (metadata.symbolChanged) initializeState();
  const select = root.querySelector("#symbolSelect");
  renderSymbols(select, metadata);
}
function startPolling() {
  poller = new PollingController({
    request: async (signal) => {
      let metadata = null;
      if (adapter.refreshMetadata) {
        try {
          metadata = await adapter.refreshMetadata(signal);
        } catch (error) {
          if (!adapter.symbol) throw error;
          adapter.setMetadataError?.(
            `自选与状态读取失败，保留现有资料：${errorMessage(error)}`,
          );
        }
      }
      const payload = await adapter.request(signal);
      return { metadata, payload };
    },
    commit: (result) => {
      syncSymbols(result.metadata);
      const raw = adapter.merge(result.payload);
      rawSnapshot = raw;
      const received = performance.now();
      now = adapter.serverNow(raw, received);
      currentModel = createModel(raw, adapter.project(now()));
      dashboard.setSnapshot(currentModel.projected);
    },
    fail: (error) => {
      const message = errorMessage(error);
      adapter.setLocalError?.(`读取失败，保留显示：${message}`);
      const projected = adapter.project(now());
      if (projected) dashboard.setSnapshot(projected);
      else {
        root.querySelector("#notice").hidden = false;
        root.querySelector("#notice").textContent = `读取失败：${message}`;
      }
      return retryDelay(error);
    },
    interval: 5000,
    documentRef: document,
  });
  poller.start();
}

function boot() {
  bindVisibility();
  if (document.hidden || bootInFlight || initialized) return;
  bootInFlight = true;
  bootstrap()
    .then(() => {
      initialized = true;
    })
    .catch((error) => {
      const message = errorMessage(error);
      root.querySelector("#notice").hidden = false;
      root.querySelector("#notice").textContent =
        `初始化失败：${message}；5秒后重试`;
      if (!document.hidden && bootTimer === null)
        bootTimer = setTimeout(() => {
          bootTimer = null;
          boot();
        }, 5000);
    })
    .finally(() => {
      bootInFlight = false;
    });
}
boot();
