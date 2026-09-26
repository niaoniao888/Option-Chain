import { expect, test } from "@playwright/test";
import fs from "node:fs";

const now = Date.parse("2026-10-01T12:00:00Z");
const btc = {
  fetched_at: new Date(now).toISOString(),
  server_time: new Date(now).toISOString(),
  market_generation_ms: now,
  index_price: 90000,
  next_refresh_seconds: 60,
  status: { status: "healthy", age_seconds: 0 },
  contracts: ["CALL", "PUT"].flatMap((side) =>
    Array.from({ length: 12 }, (_, index) => 85000 + index * 1000).map(
      (strike, index) => ({
        symbol: `BTC-${side}-${strike}`,
        side,
        strike,
        expiry_ms: now + 2 * 86400000 + 1800000,
        remaining_seconds: 2 * 86400 + index,
        annualized_pct: 12 + index,
        period_return_pct: 0.8 + index / 10,
        exercise_probability_pct: 45 + index,
        probability_display_state: "normal",
        time_value_status:
          side === "CALL" && index === 1 ? "negative" : "positive",
        time_value: side === "CALL" && index === 1 ? -0.01 : 1,
        mark_annualized_pct: side === "CALL" && index === 1 ? 7.5 : null,
        open_interest: 2,
      }),
    ),
  ),
};
const us = {
  fetched_at: new Date(now).toISOString(),
  server_time: new Date(now).toISOString(),
  snapshot_version: "fixture:1",
  state: "ready",
  fetch_health: "healthy",
  market_status: "OPEN",
  market_status_valid_until_utc: new Date(now + 3600000).toISOString(),
  fetched_age_seconds: 0,
  next_refresh_seconds: 60,
  underlying_price: 200,
  contracts: ["CALL", "PUT"].flatMap((side) =>
    Array.from({ length: 12 }, (_, index) => 175 + index * 5).map(
      (strike, index) => ({
        contract_symbol: `AAPL-${side}-${strike}`,
        side,
        strike,
        expiration_date: "2026-10-03",
        expires_at_utc: "2026-10-03T12:00:00Z",
        quote_valid_until_utc: new Date(now + 3600000).toISOString(),
        remaining_seconds: 2 * 86400 + index,
        calculation_status: "calculated",
        annualized_pct: 11 + index,
        period_return_pct: 0.7 + index / 10,
        exercise_probability_pct: 40 + index,
        ranking_eligible: true,
        close_reference_eligible: false,
      }),
    ),
  ),
};

async function mockApi(page) {
  await page.route("**/api/v1/modules", (route) =>
    route.fulfill({
      json: [
        {
          id: "bitcoin",
          provider_id: "binance",
          provider: "Binance Options EAPI",
          default_instrument: "BTCUSDT",
        },
        {
          id: "us-equities",
          provider_id: "alpaca",
          provider: "Alpaca",
          default_instrument: "AAPL",
        },
      ],
    }),
  );
  await page.route("**/api/v1/us-equities/watchlist", (route) =>
    route.fulfill({ json: { symbols: ["AAPL", "MSFT"], revision: "w1" } }),
  );
  await page.route("**/api/v1/us-equities/snapshot?**", (route) =>
    route.fulfill({ json: us }),
  );
  await page.route("**/api/v1/bitcoin/snapshot", (route) =>
    route.fulfill({ json: btc }),
  );
}

async function expectMobileTableFits(page, panel, tableSelector) {
  const geometry = await page
    .locator(`[data-panel="${panel}"] .table-wrap`)
    .evaluate((wrap, selector) => {
      const table = wrap.querySelector(selector);
      const wrapBox = wrap.getBoundingClientRect();
      const cells = [
        ...table.querySelectorAll("thead tr:first-child th"),
        ...table.querySelectorAll("tbody tr:first-child td"),
      ].map((cell) => {
        const box = cell.getBoundingClientRect();
        return { left: box.left, right: box.right };
      });
      return {
        clientWidth: wrap.clientWidth,
        scrollWidth: wrap.scrollWidth,
        left: wrapBox.left,
        right: wrapBox.right,
        cells,
      };
    }, tableSelector);
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth + 1);
  for (const cell of geometry.cells) {
    expect(cell.left).toBeGreaterThanOrEqual(geometry.left - 1);
    expect(cell.right).toBeLessThanOrEqual(geometry.right + 1);
  }
}

for (const market of ["bitcoin", "us-equities"]) {
  for (const mode of ["desktop", "mobile"]) {
    for (const width of mode === "mobile" ? [320, 390, 430] : [1280, 1920]) {
      test(`${market} ${mode} ${width}px responsive`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await mockApi(page);
        await page.goto(`/${market}/${mode}/`);
        await expect(page.locator("#health")).toHaveText("正常");
        for (const theme of ["light", "dark"]) {
          await page.locator(`button[data-theme="${theme}"]`).click();
          for (const view of ["chain", "price", "ranking"]) {
            await page.locator(`[data-view="${view}"]`).click();
            await expect(page.locator(`[data-panel="${view}"]`)).toBeVisible();
            if (mode === "mobile" && view === "price") {
              await expect(page.locator("#priceHead th")).toHaveCount(5);
              await expectMobileTableFits(page, "price", ".price-table");
            }
            if (mode === "mobile" && view === "ranking") {
              await expectMobileTableFits(page, "ranking", ".ranking-table");
            }
            expect(
              await page.evaluate(
                () =>
                  document.documentElement.scrollWidth <=
                  document.documentElement.clientWidth,
              ),
            ).toBeTruthy();
            await test
              .info()
              .attach(`${market}-${mode}-${width}-${view}-${theme}.png`, {
                body: await page.screenshot(),
                contentType: "image/png",
              });
          }
        }
        const panelRadius = await page
          .locator('[data-panel="ranking"]')
          .evaluate((node) => getComputedStyle(node).borderRadius);
        expect(panelRadius).toBe(mode === "mobile" ? "11px" : "14px");
        await page.locator('[data-view="price"]').click();
        const sizes = await page.locator("#priceSides").evaluate((node) => {
          const button = node.querySelector("button");
          return {
            width: getComputedStyle(node).width,
            height: getComputedStyle(button).height,
            weight: getComputedStyle(button).fontWeight,
          };
        });
        expect(sizes.width).toBe(mode === "mobile" ? "136px" : "240px");
        expect(sizes.height).toBe(mode === "mobile" ? "38px" : "44px");
        expect(sizes.weight).toBe("800");
        for (const theme of ["dark", "light"]) {
          await page.locator(`button[data-theme="${theme}"]`).click();
          await expect(page.locator("html")).toHaveAttribute(
            "data-theme",
            theme,
          );
          const color = await page
            .locator(".tabs button.active")
            .evaluate((node) => getComputedStyle(node).backgroundColor);
          expect(color).toBe(
            theme === "dark" ? "rgb(130, 173, 255)" : "rgb(40, 100, 220)",
          );
        }
      });
    }
  }
}

test("restored price groups, compact mobile menus and quotes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockApi(page);
  await page.goto("/bitcoin/desktop/");
  for (const selector of [
    ".chain-table td.itm",
    ".chain-table td.otm",
    ".chain-table td.atm:not(.sticky-strike)",
    ".sticky-strike.atm",
    ".sticky-strike.below",
    ".sticky-strike.above",
  ]) {
    await expect(page.locator(selector).first()).toBeVisible();
  }
  const lightChainColors = await page.evaluate(() => ({
    itm: getComputedStyle(document.querySelector(".chain-table td.itm"))
      .backgroundColor,
    otm: getComputedStyle(document.querySelector(".chain-table td.otm"))
      .backgroundColor,
    strategyAtm: getComputedStyle(
      document.querySelector(".chain-table td.atm:not(.sticky-strike)"),
    ).backgroundColor,
    strikeAtm: getComputedStyle(document.querySelector(".sticky-strike.atm"))
      .backgroundColor,
    low: getComputedStyle(document.querySelector(".sticky-strike.below"))
      .backgroundColor,
    high: getComputedStyle(document.querySelector(".sticky-strike.above"))
      .backgroundColor,
  }));
  expect(lightChainColors).toEqual({
    itm: "rgb(232, 247, 245)",
    otm: "rgb(248, 250, 255)",
    strategyAtm: "rgb(255, 248, 232)",
    strikeAtm: "rgb(255, 244, 214)",
    low: "rgb(248, 244, 240)",
    high: "rgb(240, 245, 251)",
  });
  await page.locator('button[data-theme="dark"]').click();
  const darkChainColors = await page.evaluate(() => ({
    itm: getComputedStyle(document.querySelector(".chain-table td.itm"))
      .backgroundColor,
    otm: getComputedStyle(document.querySelector(".chain-table td.otm"))
      .backgroundColor,
    strategyAtm: getComputedStyle(
      document.querySelector(".chain-table td.atm:not(.sticky-strike)"),
    ).backgroundColor,
    strikeAtm: getComputedStyle(document.querySelector(".sticky-strike.atm"))
      .backgroundColor,
    low: getComputedStyle(document.querySelector(".sticky-strike.below"))
      .backgroundColor,
    high: getComputedStyle(document.querySelector(".sticky-strike.above"))
      .backgroundColor,
  }));
  expect(darkChainColors).toEqual({
    itm: "rgb(23, 58, 59)",
    otm: "rgb(27, 39, 56)",
    strategyAtm: "rgb(58, 51, 34)",
    strikeAtm: "rgb(64, 53, 29)",
    low: "rgb(43, 37, 38)",
    high: "rgb(27, 42, 60)",
  });
  await page.locator('button[data-theme="light"]').click();
  const expiryStyle = await page
    .locator('#expiryButtons button[aria-pressed="true"]')
    .evaluate((node) => {
      const style = getComputedStyle(node);
      return {
        size: style.fontSize,
        weight: style.fontWeight,
        height: style.height,
        color: style.color,
        background: style.backgroundColor,
        borderBottom: style.borderBottomWidth,
      };
    });
  expect(expiryStyle).toEqual({
    size: "18px",
    weight: "700",
    height: "32px",
    color: "rgb(40, 100, 220)",
    background: "rgba(0, 0, 0, 0)",
    borderBottom: "2px",
  });
  const warningColors = await page
    .locator(".tv-warning")
    .first()
    .evaluate((node) => ({
      warning: getComputedStyle(node).color,
      detail: getComputedStyle(node.querySelector("small")).color,
      mark: getComputedStyle(node.querySelector(".mark-value")).color,
    }));
  expect(warningColors).toEqual({
    warning: "rgb(8, 124, 97)",
    detail: "rgb(102, 114, 138)",
    mark: "rgb(40, 100, 220)",
  });
  await page.locator('[data-view="price"]').click();
  await expect(page.locator("#currentStrike")).toHaveText("90,000");
  const priceGeometry = await page.evaluate(() => {
    const sides = document.querySelector("#priceSides").getBoundingClientRect(),
      label = document
        .querySelector("#currentStrikeLabel")
        .getBoundingClientRect(),
      selectedGroup = document.querySelector(
        '#strikeGroupButtons [aria-pressed="true"]',
      ),
      high = document.querySelector(".strike-option-row.high button"),
      th = document.querySelector(".price-table th"),
      td = document.querySelector(".price-table td");
    const read = (node) => {
      const style = getComputedStyle(node);
      return {
        size: style.fontSize,
        weight: style.fontWeight,
        height: style.height,
        color: style.color,
        background: style.backgroundColor,
        border: style.borderColor,
      };
    };
    return {
      gap: Math.round(label.left - sides.right),
      label: read(document.querySelector("#currentStrikeLabel")),
      group: read(selectedGroup),
      high: read(high),
      th: read(th),
      td: read(td),
    };
  });
  expect(priceGeometry.gap).toBe(20);
  expect(priceGeometry.label.size).toBe("19.5px");
  expect(priceGeometry.label.weight).toBe("700");
  expect(priceGeometry.group).toMatchObject({
    size: "18px",
    weight: "700",
    height: "32px",
    color: "rgb(40, 100, 220)",
    background: "rgba(0, 0, 0, 0)",
  });
  expect(priceGeometry.high).toMatchObject({
    size: "18px",
    weight: "750",
    height: "42px",
    color: "rgb(157, 52, 52)",
    background: "rgb(255, 237, 237)",
    border: "rgb(236, 194, 194)",
  });
  expect(priceGeometry.th).toMatchObject({
    size: "16.5px",
    weight: "700",
    color: "rgb(89, 101, 122)",
    background: "rgb(241, 244, 249)",
  });
  expect(priceGeometry.td.size).toBe("19.5px");
  expect(priceGeometry.td.weight).toBe("400");
  await expect(page.locator("#strikeGroupButtons")).toContainText("8万");
  await page.locator('#strikeGroupButtons [data-strike-group="80000"]').click();
  await expect(page.locator("#currentStrike")).toHaveText("90,000");
  await page.locator('#strikeButtons [data-strike="85000"]').click();
  await expect(page.locator("#currentStrike")).toHaveText("85,000");
  await expect(page.locator("#currentStrikeLabel")).toHaveCSS(
    "color",
    "rgb(8, 124, 97)",
  );
  await expect(
    page.locator('.strike-option-row.low [data-strike="85000"]'),
  ).toHaveCSS("background-color", "rgb(40, 100, 220)");
  await expect(
    page.locator('.strike-option-row.low [data-strike="87000"]'),
  ).toHaveCSS("background-color", "rgb(232, 247, 239)");
  await expect(
    page.locator('.strike-option-row.low [data-strike="87000"]'),
  ).toHaveCSS("border-color", "rgb(173, 219, 198)");
  await page.locator('#strikeGroupButtons [data-strike-group="90000"]').click();
  const buttonColors = async (selector) =>
    page.locator(selector).evaluate((node) => {
      const style = getComputedStyle(node);
      return [style.backgroundColor, style.borderColor, style.color];
    });
  expect(await buttonColors('[data-strike="90000"]')).toEqual([
    "rgb(255, 244, 214)",
    "rgb(227, 195, 108)",
    "rgb(118, 82, 7)",
  ]);
  expect(await buttonColors('[data-strike="91000"]')).toEqual([
    "rgb(255, 237, 237)",
    "rgb(236, 194, 194)",
    "rgb(157, 52, 52)",
  ]);
  await page.locator('button[data-theme="dark"]').click();
  expect(await buttonColors('[data-strike="90000"]')).toEqual([
    "rgb(65, 54, 30)",
    "rgb(128, 106, 50)",
    "rgb(255, 224, 154)",
  ]);
  expect(await buttonColors('[data-strike="91000"]')).toEqual([
    "rgb(67, 40, 44)",
    "rgb(112, 67, 74)",
    "rgb(255, 177, 177)",
  ]);
  await page.locator('#strikeGroupButtons [data-strike-group="80000"]').click();
  expect(await buttonColors('[data-strike="87000"]')).toEqual([
    "rgb(23, 58, 50)",
    "rgb(47, 103, 86)",
    "rgb(145, 223, 192)",
  ]);
  await page.locator('button[data-theme="light"]').click();
  fs.mkdirSync("test-results/refactor-evidence", { recursive: true });
  await page.screenshot({
    path: "test-results/refactor-evidence/bitcoin-desktop-price-restored.png",
    fullPage: true,
  });
  const periodSizes = await page
    .locator(".period-metric")
    .first()
    .evaluate((node) => ({
      relative: getComputedStyle(node.querySelector(".period-distance"))
        .fontSize,
      value: getComputedStyle(node.querySelector(".period-return")).fontSize,
      align: getComputedStyle(node).alignItems,
    }));
  expect(periodSizes).toEqual({
    relative: periodSizes.value,
    value: periodSizes.value,
    align: "flex-end",
  });

  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/bitcoin/mobile/");
  await expect(page.locator(".hero .quote")).toBeVisible();
  await expect(page.locator(".hero .quote")).toContainText("BTC：90,000");
  await page.locator("#expiryTrigger").click();
  await expect(page.locator("#expiryMenu [role=option]").first()).toContainText(
    /（剩余2天）/,
  );
  await page.locator("#expiryTrigger").click();
  await page.locator('[data-view="price"]').click();
  await page.locator("#strikeTrigger").click();
  const strikeOption = page.locator("#strikeMenu [role=option]").first();
  await expect(strikeOption.locator(".menu-primary")).toHaveText("85,000");
  await expect(strikeOption.locator(".menu-secondary")).toHaveText(
    "（-5.56%）",
  );
  await page.screenshot({
    path: "test-results/refactor-evidence/bitcoin-mobile-price-restored.png",
    fullPage: true,
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/us-equities/desktop/");
  await page.locator('[data-view="price"]').click();
  await expect(page.locator("#strikeGroupButtons")).toContainText("175–220");
  await page.screenshot({
    path: "test-results/refactor-evidence/us-desktop-price-restored.png",
    fullPage: true,
  });
});

test("mobile chain keeps quote, header and strike visible at both scroll ends", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await mockApi(page);
  for (const market of ["bitcoin", "us-equities"]) {
    await page.goto(`/${market}/mobile/`);
    await expect(page.locator(".hero .quote")).toBeVisible();
    const [quoteBox, themesBox] = await Promise.all([
      page.locator(".hero .quote").boundingBox(),
      page.locator(".themes").boundingBox(),
    ]);
    expect(themesBox.width).toBeLessThan(90);
    expect(Math.abs(quoteBox.y - themesBox.y)).toBeLessThan(12);
    const wrap = page.locator(".chain-wrap"),
      strike = page.locator("#chainBody .sticky-strike").first(),
      header = page.locator(".chain-table thead .sticky-strike");
    for (const side of ["left", "right"]) {
      await wrap.evaluate((node, direction) => {
        node.scrollLeft = direction === "left" ? 0 : node.scrollWidth;
      }, side);
      const [wrapBox, strikeBox, headerBox] = await Promise.all([
        wrap.boundingBox(),
        strike.boundingBox(),
        header.boundingBox(),
      ]);
      expect(strikeBox.x).toBeGreaterThanOrEqual(wrapBox.x - 1);
      expect(strikeBox.x + strikeBox.width).toBeLessThanOrEqual(
        wrapBox.x + wrapBox.width + 1,
      );
      expect(headerBox.y).toBeGreaterThanOrEqual(wrapBox.y - 1);
    }
    fs.mkdirSync("test-results/refactor-evidence", { recursive: true });
    await page.screenshot({
      path: `test-results/refactor-evidence/${market}-mobile-chain-restored.png`,
      fullPage: true,
    });
    for (const width of [320, 390, 430]) {
      await page.setViewportSize({ width, height: 900 });
      await page.locator('[data-view="chain"]').click();
      await page.locator("#expiryTrigger").click();
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth <=
            document.documentElement.clientWidth,
        ),
      ).toBeTruthy();
      await page.locator("#expiryTrigger").click();
      await page.locator('[data-view="price"]').click();
      await page.locator("#strikeTrigger").click();
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth <=
            document.documentElement.clientWidth,
        ),
      ).toBeTruthy();
      await page.locator("#strikeTrigger").click();
    }
  }
});

test("150 percent zoom and keyboard menu remain usable", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockApi(page);
  await page.goto("/us-equities/desktop/");
  await page.evaluate(() => {
    document.body.style.zoom = "1.5";
  });
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBeTruthy();
  await page.evaluate(() => {
    document.body.style.zoom = "1";
  });
  await page.setViewportSize({ width: 430, height: 900 });
  await page.goto("/us-equities/mobile/");
  await page.locator("#expiryTrigger").press("ArrowDown");
  await expect(page.locator("#expiryMenu")).toBeVisible();
  await expect(
    page.locator('#expiryMenu [role=option][aria-selected="true"]'),
  ).toBeFocused();
  await page.locator("#expiryMenu").press("Escape");
  await expect(page.locator("#expiryTrigger")).toBeFocused();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBeTruthy();
});

test("text selection defers table replacement then flushes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await mockApi(page);
  await page.unroute("**/api/v1/bitcoin/snapshot");
  let requests = 0;
  await page.route("**/api/v1/bitcoin/snapshot", (route) => {
    requests += 1;
    route.fulfill({ json: { ...btc, market_generation_ms: now + requests } });
  });
  await page.goto("/bitcoin/mobile/");
  await expect(
    page.locator("#chainBody .sticky-strike").first(),
  ).toBeVisible();
  await page.evaluate(() => {
    const node = document.querySelector("#chainBody td");
    const range = document.createRange();
    range.selectNodeContents(node);
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    document.body.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, buttons: 1 }),
    );
  });
  await expect(page.locator("#pending")).toBeVisible({ timeout: 7000 });
  await page.evaluate(() => {
    getSelection().removeAllRanges();
    document.dispatchEvent(new Event("selectionchange"));
    document.body.dispatchEvent(
      new PointerEvent("pointerup", { bubbles: true, buttons: 0 }),
    );
  });
  await expect(page.locator("#pending")).toBeHidden();
});

test("same snapshot generation keeps table DOM stable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await mockApi(page);
  await page.unroute("**/api/v1/bitcoin/snapshot");
  let requests = 0;
  await page.route("**/api/v1/bitcoin/snapshot", async (route) => {
    requests += 1;
    if (requests === 1)
      await new Promise((resolve) => setTimeout(resolve, 750));
    await route.fulfill({ json: btc });
  });
  await page.goto("/bitcoin/mobile/");
  await expect(
    page.locator("#chainBody .sticky-strike").first(),
  ).toBeVisible();
  expect(
    await page.evaluate(() => {
      const row = document.querySelector("#chainBody tr");
      if (!row) return false;
      window.__firstChainRow = row;
      return true;
    }),
  ).toBeTruthy();
  await page.waitForTimeout(5500);
  expect(requests).toBeGreaterThanOrEqual(2);
  expect(
    await page.evaluate(
      () => window.__firstChainRow === document.querySelector("#chainBody tr"),
    ),
  ).toBeTruthy();
});

test("US sorting pagination and symbol state stay isolated", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockApi(page);
  await page.goto("/us-equities/desktop/");
  await page.locator('[data-view="ranking"]').click();
  await expect(page.locator('#rankingPages [data-page="2"]')).toBeVisible();
  await page.locator('#rankingPages [data-page="2"]').click();
  await expect(page.locator('#rankingPages [aria-current="page"]')).toHaveText(
    "2",
  );
  await page.locator("#symbolSelect").selectOption("MSFT");
  await expect(page.locator('#rankingPages [aria-current="page"]')).toHaveText(
    "1",
  );
  await page.locator('[data-view="price"]').click();
  await page.locator('#priceHead [data-sort="remaining_seconds"]').click();
  await expect(
    page.locator(
      '#priceHead th[aria-sort="ascending"] [data-sort="remaining_seconds"]',
    ),
  ).toBeVisible();
  await page.locator("#symbolSelect").selectOption("AAPL");
  await page.locator('[data-view="ranking"]').click();
  await expect(page.locator('#rankingPages [aria-current="page"]')).toHaveText(
    "2",
  );
});

test("US metadata failure recovers without stopping snapshot polling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockApi(page);
  await page.unroute("**/api/v1/us-equities/watchlist");
  let calls = 0;
  await page.route("**/api/v1/us-equities/watchlist", (route) => {
    calls += 1;
    if (calls === 2)
      return route.fulfill({ status: 503, json: { error: "temporary" } });
    return route.fulfill({
      json: { symbols: ["AAPL", "MSFT"], revision: `w${calls}` },
    });
  });
  await page.goto("/us-equities/desktop/");
  await expect(page.locator("#health")).toHaveText("异常");
  await expect(page.locator("#notice")).toContainText("保留现有资料");
  await expect(page.locator("#health")).toHaveText("正常", { timeout: 8000 });
  expect(calls).toBeGreaterThanOrEqual(3);
});

test("cross-symbol abort cannot commit a late previous snapshot", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockApi(page);
  await page.unroute("**/api/v1/us-equities/snapshot?**");
  let aaplCalls = 0;
  await page.route("**/api/v1/us-equities/snapshot?**", async (route) => {
    const symbol = new URL(route.request().url()).searchParams.get("symbol");
    if (symbol === "AAPL") {
      aaplCalls += 1;
      if (aaplCalls > 1)
        await new Promise((resolve) => setTimeout(resolve, 900));
    }
    await route.fulfill({
      json: {
        ...us,
        symbol,
        underlying_price: symbol === "MSFT" ? 333 : 111,
        snapshot_version: `${symbol}:${aaplCalls}`,
      },
    });
  });
  await page.goto("/us-equities/desktop/");
  await expect(page.locator("[data-quote-price]").first()).toHaveText("111.00");
  await page.waitForTimeout(5200);
  await page.locator("#symbolSelect").selectOption("MSFT");
  await expect(page.locator("[data-quote-symbol]").first()).toContainText(
    "MSFT",
  );
  await expect(page.locator("[data-quote-price]").first()).toHaveText("333.00");
  await page.waitForTimeout(1200);
  await expect(page.locator("[data-quote-price]").first()).toHaveText("333.00");
});

test("untrusted watchlist text is rendered as text", async ({ page }) => {
  await mockApi(page);
  await page.unroute("**/api/v1/us-equities/watchlist");
  const malicious = '<img src=x onerror="globalThis.injected=1">';
  await page.route("**/api/v1/us-equities/watchlist", (route) =>
    route.fulfill({ json: { symbols: [malicious], revision: "unsafe" } }),
  );
  await page.goto("/us-equities/desktop/");
  await expect(page.locator("#symbolSelect option")).toHaveText(malicious);
  expect(await page.locator("#symbolSelect img").count()).toBe(0);
  expect(await page.evaluate(() => globalThis.injected)).toBeUndefined();
});

test("a registered third market renders through the shared dashboard", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockApi(page);
  await page.goto("/bitcoin/desktop/");
  const result = await page.evaluate(async () => {
    const registry = await import("/bitcoin/desktop/markets/registry.js");
    const { Dashboard } = await import(
      "/bitcoin/desktop/components/dashboard.js"
    );
    const { normalizeUi } = await import("/bitcoin/desktop/core/state.js");
    registry.registerMarketAdapter(
      "fixture-market",
      () => ({
        id: "fixture-market",
        title: "Fixture 期权",
        symbol: "FIX",
        showMarketStatus: false,
        priceDigits: 3,
        parseExpiryId: String,
        rankingColumns: ["expiry", "strike", "annualized_pct"],
        expiry: (row) => row.expiry,
        expiryLabel: (value) => value,
        contractId: (row) => row.id,
        displayable: () => true,
        priceEligible: () => true,
        rankingEligible: () => true,
        defaultExpiry: (values) => values[0],
        sortValue: (row, key) => row[key],
        periodParts: (row) => ({
          value: row.period_return_pct,
          showRelative: false,
        }),
        annualHtml: (row) => `${row.annualized_pct.toFixed(2)}%`,
        probabilityHtml: (row) => `${row.exercise_probability_pct.toFixed(1)}%`,
        status: () => ({ market: "", health: "healthy", countdown: 10 }),
      }),
      { label: "Fixture期权" },
    );
    const adapter = registry.createMarketAdapter({
      market: "fixture-market",
      mode: "desktop",
      basePath: "",
    });
    const state = normalizeUi({ view: "ranking" });
    const dashboard = new Dashboard({
      root: document.querySelector("#app"),
      adapter,
      state,
      onState() {},
    });
    dashboard.setSnapshot({
      underlying_price: 1.2,
      contracts: [
        {
          id: "F-1",
          expiry: '<img src=x onerror="globalThis.fixtureInjected=1">',
          side: "CALL",
          strike: 1.234,
          remaining_seconds: 1000,
          annualized_pct: 9,
          period_return_pct: 1,
          exercise_probability_pct: 2,
        },
      ],
    });
    return {
      title: document.querySelector("#title").textContent,
      columns: document.querySelectorAll("#rankingHead th").length,
      row: document
        .querySelector("#rankingBody")
        .textContent.replaceAll(/\s/g, ""),
      label: registry.marketLabel("fixture-market"),
      injected: globalThis.fixtureInjected,
      images: document.querySelectorAll("#expiryButtons img,#expiryMenu img")
        .length,
    };
  });
  expect(result).toEqual({
    title: "Fixture 期权",
    columns: 3,
    row: "—1.2349.00%",
    label: "Fixture期权",
    injected: undefined,
    images: 0,
  });
});
