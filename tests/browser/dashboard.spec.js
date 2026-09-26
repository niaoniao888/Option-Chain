import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

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

async function installVisibilityControl(page) {
  await page.addInitScript(() => {
    globalThis.__testHidden = false;
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => globalThis.__testHidden,
    });
  });
}

async function setPageHidden(page, hidden) {
  await page.evaluate((value) => {
    globalThis.__testHidden = value;
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);
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

async function expectStickyHeaderUncovered(page, panel) {
  const result = await page
    .locator(`[data-panel="${panel}"] .table-wrap`)
    .evaluate(async (wrap) => {
      wrap.style.maxHeight = "180px";
      wrap.scrollTop = wrap.scrollHeight;
      wrap.scrollLeft = wrap.scrollWidth;
      await new Promise((resolve) => requestAnimationFrame(resolve));

      const wrapBox = wrap.getBoundingClientRect();
      const cells = [...wrap.querySelectorAll("thead th")]
        .map((cell) => {
          const box = cell.getBoundingClientRect();
          const left = Math.max(box.left, wrapBox.left);
          const right = Math.min(box.right, wrapBox.right);
          const top = Math.max(box.top, wrapBox.top);
          const bottom = Math.min(box.bottom, wrapBox.bottom);
          if (right - left < 4 || bottom - top < 4) return null;
          const hit = document.elementFromPoint(
            left + (right - left) / 2,
            top + (bottom - top) / 2,
          );
          return {
            text: cell.textContent.trim(),
            hitHeader: hit?.closest("th") === cell,
          };
        })
        .filter(Boolean);

      return {
        clientHeight: wrap.clientHeight,
        scrollHeight: wrap.scrollHeight,
        scrollTop: wrap.scrollTop,
        cells,
      };
    });

  expect(result.scrollHeight).toBeGreaterThan(result.clientHeight);
  expect(result.scrollTop).toBeGreaterThan(0);
  expect(result.cells.length).toBeGreaterThan(0);
  expect(result.cells.filter((cell) => !cell.hitHeader)).toEqual([]);
}

async function expiryTriggerGeometry(page) {
  return page.locator("#expiryTrigger").evaluate((button) => {
    const value = button.querySelector("#expiryValue");
    const arrow = button.querySelector("span:last-child");
    const range = document.createRange();
    range.selectNodeContents(value);
    const textRects = [...range.getClientRects()];
    const buttonRect = button.getBoundingClientRect();
    const arrowRect = arrow.getBoundingClientRect();
    return {
      buttonWidth: buttonRect.width,
      textLineCount: new Set(
        textRects.map((rect) => Math.round(rect.top * 10) / 10),
      ).size,
      textRight: Math.max(...textRects.map((rect) => rect.right)),
      arrowLeft: arrowRect.left,
      arrowRight: arrowRect.right,
      buttonRight: buttonRect.right,
      whiteSpace: getComputedStyle(value).whiteSpace,
    };
  });
}

function expectExpiryTriggerFits(geometry) {
  expect(geometry.buttonWidth).toBe(112);
  expect(geometry.textLineCount).toBe(1);
  expect(geometry.whiteSpace).toBe("nowrap");
  expect(geometry.textRight).toBeLessThanOrEqual(geometry.arrowLeft);
  expect(geometry.arrowRight).toBeLessThanOrEqual(geometry.buttonRight);
}

for (const market of ["bitcoin", "us-equities"]) {
  for (const mode of ["desktop", "mobile"]) {
    for (const theme of ["light", "dark"]) {
      test(`fixed-data visual baseline ${market} ${mode} ${theme}`, async ({
        page,
      }) => {
        await page.clock.install({ time: now });
        await page.clock.pauseAt(now);
        await page.setViewportSize({
          width: mode === "mobile" ? 390 : 1280,
          height: mode === "mobile" ? 844 : 900,
        });
        await mockApi(page);
        await page.goto(`/${market}/${mode}/`);
        await page.locator(`button[data-theme="${theme}"]`).click();
        await expect(page.locator("#chainBody tr").first()).toBeVisible();
        await expect(page.locator("#app")).toHaveScreenshot(
          `${market}-${mode}-${theme}.png`,
          {
            animations: "disabled",
            caret: "hide",
            maxDiffPixelRatio: 0.01,
          },
        );
        const currentBaselineDir = path.join(
          "test-results",
          "current-baselines",
        );
        fs.mkdirSync(currentBaselineDir, { recursive: true });
        await page.locator("#app").screenshot({
          path: path.join(
            currentBaselineDir,
            `${market}-${mode}-${theme}-${process.platform}.png`,
          ),
          animations: "disabled",
          caret: "hide",
        });
      });
    }
  }
}

test("strike column colors use shared variables in every market layout", async ({
  page,
}) => {
  await mockApi(page);
  for (const mode of ["desktop", "mobile"]) {
    await page.setViewportSize({
      width: mode === "mobile" ? 390 : 1280,
      height: mode === "mobile" ? 844 : 900,
    });
    for (const theme of ["light", "dark"]) {
      const colorsByMarket = {};
      for (const market of ["bitcoin", "us-equities"]) {
        await page.goto(`/${market}/${mode}/`);
        await page.locator(`button[data-theme="${theme}"]`).click();
        for (const selector of [
          ".sticky-strike.atm",
          ".sticky-strike.below",
          ".sticky-strike.above",
        ]) {
          await expect(page.locator(selector).first()).toBeVisible();
        }
        const colors = await page.evaluate(() => {
          const resolveBackground = (variable) => {
            const probe = document.createElement("span");
            probe.style.background = `var(${variable})`;
            document.body.append(probe);
            const color = getComputedStyle(probe).backgroundColor;
            probe.remove();
            return color;
          };
          return {
            actual: {
              atm: getComputedStyle(
                document.querySelector(".sticky-strike.atm"),
              ).backgroundColor,
              below: getComputedStyle(
                document.querySelector(".sticky-strike.below"),
              ).backgroundColor,
              above: getComputedStyle(
                document.querySelector(".sticky-strike.above"),
              ).backgroundColor,
            },
            expected: {
              atm: resolveBackground("--strike-atm"),
              below: resolveBackground("--strike-low"),
              above: resolveBackground("--strike-high"),
            },
          };
        });
        expect(colors.actual).toEqual(colors.expected);
        colorsByMarket[market] = colors.actual;
      }
      expect(colorsByMarket["us-equities"]).toEqual(colorsByMarket.bitcoin);
    }
  }
});

for (const market of ["bitcoin", "us-equities"]) {
  for (const mode of ["desktop", "mobile"]) {
    test(`sticky table headers stay above rows ${market} ${mode}`, async ({
      page,
    }) => {
      await page.setViewportSize({
        width: mode === "mobile" ? 390 : 1280,
        height: 900,
      });
      await mockApi(page);

      const makeDenseContracts = (snapshot, marketId) =>
        ["CALL", "PUT"].flatMap((side) =>
          Array.from({ length: 12 }, (_, expiryIndex) =>
            Array.from({ length: 12 }, (_, strikeIndex) => {
              const source = snapshot.contracts.find(
                (row) => row.side === side,
              );
              const expiresAt = new Date(
                now + (expiryIndex + 1) * 86400000 + 1800000,
              );
              const strike =
                marketId === "bitcoin"
                  ? 85000 + strikeIndex * 1000
                  : 175 + strikeIndex * 5;
              return marketId === "bitcoin"
                ? {
                    ...source,
                    symbol: `BTC-${side}-${expiryIndex}-${strike}`,
                    strike,
                    expiry_ms: expiresAt.getTime(),
                    remaining_seconds: (expiryIndex + 1) * 86400 + 1800,
                  }
                : {
                    ...source,
                    contract_symbol: `AAPL-${side}-${expiryIndex}-${strike}`,
                    strike,
                    expiration_date: expiresAt.toISOString().slice(0, 10),
                    expires_at_utc: expiresAt.toISOString(),
                    remaining_seconds: (expiryIndex + 1) * 86400 + 1800,
                  };
            }),
          ).flat(),
        );

      await page.unroute("**/api/v1/bitcoin/snapshot");
      await page.unroute("**/api/v1/us-equities/snapshot?**");
      await page.route("**/api/v1/bitcoin/snapshot", (route) =>
        route.fulfill({
          json: {
            ...btc,
            contracts: makeDenseContracts(btc, "bitcoin"),
          },
        }),
      );
      await page.route("**/api/v1/us-equities/snapshot?**", (route) =>
        route.fulfill({
          json: {
            ...us,
            contracts: makeDenseContracts(us, "us-equities"),
          },
        }),
      );

      await page.goto(`/${market}/${mode}/`);
      for (const view of ["chain", "price", "ranking"]) {
        await page.locator(`[data-view="${view}"]`).click();
        await expect(page.locator(`#${view}Body tr`).first()).toBeVisible();
        await expectStickyHeaderUncovered(page, view);
      }
    });
  }
}

for (const market of ["bitcoin", "us-equities"]) {
  for (const mode of ["desktop", "mobile"]) {
    for (const width of mode === "mobile" ? [320, 390, 430] : [1280, 1920]) {
      test(`${market} ${mode} ${width}px responsive`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await mockApi(page);
        if (mode === "mobile") {
          await page.route("**/styles.css", async (route) => {
            const response = await route.fetch();
            await route.fulfill({
              response,
              body: `${await response.text()}\n.font-stress #expiryTrigger { font-family: Arial, sans-serif; font-size: 16px; }`,
            });
          });
        }
        await page.goto(`/${market}/${mode}/`);
        await expect(page.locator("#health")).toHaveText("正常");
        if (mode === "mobile") {
          await expect(page.locator("#expiryValue")).toHaveText("2026-10-03");
          expectExpiryTriggerFits(await expiryTriggerGeometry(page));
          await page
            .locator("html")
            .evaluate((node) => node.classList.add("font-stress"));
          expectExpiryTriggerFits(await expiryTriggerGeometry(page));
          await page
            .locator("html")
            .evaluate((node) => node.classList.remove("font-stress"));
          await expect(page.locator("#expiryDetail")).toContainText(
            market === "bitcoin"
              ? "到期时间：2026-10-03 20:30"
              : "到期时间：2026-10-03 20:00",
          );
          await page.locator("#expiryTrigger").click();
          await expect(
            page.locator("#expiryMenu [role=option]").first(),
          ).toContainText(
            market === "bitcoin" ? "2026-10-03（剩余2天）" : "2026-10-03（剩余",
          );
          await page.locator("#expiryTrigger").click();
        }
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

test("desktop tables share one total width and expiry time sorts by instant", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 1200 });
  await mockApi(page);
  await page.unroute("**/api/v1/bitcoin/snapshot");
  const denseContracts = ["CALL", "PUT"].flatMap((side) =>
      Array.from({ length: 40 }, (_, index) => ({
        ...btc.contracts.find((row) => row.side === side),
        symbol: `BTC-${side}-DENSE-${index}`,
        strike: 70000 + index * 1000,
      })),
    ),
    earlier = {
      ...denseContracts.find(
        (row) => row.side === "CALL" && row.strike === 90000,
      ),
      symbol: "BTC-CALL-90000-EARLIER",
      expiry_ms: now + 2 * 86400000,
      remaining_seconds: 2 * 86400,
    };
  await page.route("**/api/v1/bitcoin/snapshot", (route) =>
    route.fulfill({
      json: { ...btc, contracts: [...denseContracts, earlier] },
    }),
  );
  await page.goto("/bitcoin/desktop/");
  const measure = (selector) =>
    page.locator(selector).evaluate((table) => ({
      width: table.getBoundingClientRect().width,
      left: table.getBoundingClientRect().left,
      right: table.getBoundingClientRect().right,
      wrapWidth: table.closest(".table-wrap").getBoundingClientRect().width,
      wrapClientHeight: table.closest(".table-wrap").clientHeight,
      wrapScrollHeight: table.closest(".table-wrap").scrollHeight,
      columns: [...table.querySelectorAll("thead tr:first-child th")].map(
        (cell) => cell.getBoundingClientRect().width,
      ),
    }));
  for (const viewportWidth of [1280, 1920]) {
    await page.setViewportSize({ width: viewportWidth, height: 1200 });
    await page.locator('[data-view="chain"]').click();
    const chain = await measure(".chain-table");
    await page.locator('[data-view="price"]').click();
    const price = await measure(".price-table");
    await page.locator('[data-view="ranking"]').click();
    const ranking = await measure(".ranking-table");
    for (const table of [chain, price, ranking])
      expect(table.width).toBeCloseTo(1200, 0);
    for (const width of chain.columns) expect(width).toBeCloseTo(1200 / 7, 0);
    for (const width of price.columns) expect(width).toBeCloseTo(1200 / 5, 0);
    for (const width of ranking.columns) expect(width).toBeCloseTo(1200 / 6, 0);
    expect(chain.wrapScrollHeight).toBeGreaterThan(chain.wrapClientHeight);
    expect(ranking.wrapScrollHeight).toBeLessThanOrEqual(
      ranking.wrapClientHeight,
    );
    expect(price.left).toBeCloseTo(chain.left, 0);
    expect(ranking.left).toBeCloseTo(chain.left, 0);
    expect(price.right).toBeCloseTo(chain.right, 0);
    expect(ranking.right).toBeCloseTo(chain.right, 0);
    if (viewportWidth === 1920)
      expect(chain.wrapWidth).toBeGreaterThan(chain.width);
  }
  await expect(page.locator(".floating-quote")).toHaveCSS("width", "200px");

  await page.setViewportSize({ width: 1280, height: 1200 });
  await page.locator('[data-view="price"]').click();
  await page.locator('#priceHead [data-sort="expiry_time"]').click();
  await expect(
    page.locator('#priceHead th[aria-sort="ascending"]'),
  ).toContainText("到期时间");
  await expect(page.locator("#priceBody tr")).toHaveCount(2);
  await expect(page.locator("#priceBody tr td:last-child").first()).toHaveText(
    "1天",
  );
  await page.locator('[data-view="ranking"]').click();
  await expect(page.locator("#rankingHead th")).toHaveCount(6);
  await expect(page.locator("#rankingHead th:last-child")).toContainText(
    "到期时间",
  );
  await page.locator('#rankingHead [data-sort="expiry_time"]').click();
  await expect(
    page.locator('#rankingHead th[aria-sort="ascending"]'),
  ).toContainText("到期时间");
  await expect(
    page.locator("#rankingBody tr td:last-child").first(),
  ).toHaveText("1天");
});

test("table expiry duration is shared by both markets and escapes less-than text", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await mockApi(page);
  await page.unroute("**/api/v1/bitcoin/snapshot");
  await page.unroute("**/api/v1/us-equities/snapshot?**");
  await page.route("**/api/v1/bitcoin/snapshot", (route) =>
    route.fulfill({
      json: {
        ...btc,
        contracts: btc.contracts.map((row) => ({
          ...row,
          expiry_ms: now + 1000 * 1000,
          remaining_seconds: 1000,
        })),
      },
    }),
  );
  await page.route("**/api/v1/us-equities/snapshot?**", (route) =>
    route.fulfill({
      json: {
        ...us,
        contracts: us.contracts.map((row) => ({
          ...row,
          expiration_date: "2026-10-01",
          expires_at_utc: new Date(now + 1000 * 1000).toISOString(),
          remaining_seconds: 1000,
        })),
      },
    }),
  );
  for (const market of ["bitcoin", "us-equities"]) {
    await page.goto(`/${market}/mobile/`);
    for (const view of ["price", "ranking"]) {
      await page.locator(`[data-view="${view}"]`).click();
      const body = page.locator(`#${view}Body`);
      await expect(body.locator("tr td:last-child").first()).toHaveText(
        "<1小时",
      );
      expect(await body.locator("tr td:last-child span").count()).toBe(0);
    }
  }
});

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
  await expect(page.locator("#chainBody .sticky-strike").first()).toBeVisible();
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
  await expect(page.locator("#chainBody .sticky-strike").first()).toBeVisible();
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
  await page.locator('#priceHead [data-sort="expiry_time"]').click();
  await expect(
    page.locator(
      '#priceHead th[aria-sort="ascending"] [data-sort="expiry_time"]',
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

test("US snapshot failure keeps the previous table and recovers", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockApi(page);
  await page.unroute("**/api/v1/us-equities/snapshot?**");
  let calls = 0;
  await page.route("**/api/v1/us-equities/snapshot?**", (route) => {
    calls += 1;
    if (calls === 2) return route.abort("timedout");
    return route.fulfill({
      json: {
        ...us,
        underlying_price: calls >= 3 ? 222 : 111,
        snapshot_version: `recovery:${calls}`,
      },
    });
  });
  await page.goto("/us-equities/desktop/");
  await expect(page.locator("[data-quote-price]").first()).toHaveText("111.00");
  const previousRow = await page.locator("#chainBody tr").first().innerText();
  await expect(page.locator("#notice")).toContainText("读取失败，保留显示", {
    timeout: 8000,
  });
  await expect(page.locator("#notice")).not.toContainText("undefined");
  await expect(page.locator("#chainBody tr").first()).toHaveText(previousRow);
  await expect(page.locator("[data-quote-price]").first()).toHaveText(
    "222.00",
    {
      timeout: 8000,
    },
  );
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

test("bootstrap in flight survives rapid visibility changes without a duplicate chain", async ({
  page,
}) => {
  await installVisibilityControl(page);
  let moduleCalls = 0;
  let releaseModules;
  const moduleGate = new Promise((resolve) => (releaseModules = resolve));
  await page.route("**/api/v1/modules", async (route) => {
    moduleCalls += 1;
    await moduleGate;
    await route.fulfill({
      json: [
        {
          id: "bitcoin",
          provider_id: "binance",
          provider: "Binance Options EAPI",
          default_instrument: "BTCUSDT",
        },
      ],
    });
  });
  let snapshotCalls = 0;
  await page.route("**/api/v1/bitcoin/snapshot", (route) => {
    snapshotCalls += 1;
    return route.fulfill({ json: btc });
  });
  await page.goto("/bitcoin/desktop/");
  await expect.poll(() => moduleCalls).toBe(1);
  await setPageHidden(page, true);
  await setPageHidden(page, false);
  await setPageHidden(page, true);
  releaseModules();
  await page.waitForTimeout(100);
  expect(moduleCalls).toBe(1);
  expect(snapshotCalls).toBe(0);
  await setPageHidden(page, false);
  await expect.poll(() => snapshotCalls).toBe(1);
  await expect(page.locator("#chainBody .sticky-strike").first()).toBeVisible();
});

test("failed bootstrap pauses retries while hidden and resumes once when visible", async ({
  page,
}) => {
  await installVisibilityControl(page);
  let moduleCalls = 0;
  await page.route("**/api/v1/modules", (route) => {
    moduleCalls += 1;
    if (moduleCalls === 1)
      return route.fulfill({ status: 503, json: { error: "temporary" } });
    return route.fulfill({
      json: [
        {
          id: "bitcoin",
          provider_id: "binance",
          provider: "Binance Options EAPI",
          default_instrument: "BTCUSDT",
        },
      ],
    });
  });
  let snapshotCalls = 0;
  await page.route("**/api/v1/bitcoin/snapshot", (route) => {
    snapshotCalls += 1;
    return route.fulfill({ json: btc });
  });
  await page.goto("/bitcoin/desktop/");
  await expect(page.locator("#notice")).toContainText("初始化失败");
  await setPageHidden(page, true);
  await page.waitForTimeout(5200);
  expect(moduleCalls).toBe(1);
  expect(snapshotCalls).toBe(0);
  await setPageHidden(page, false);
  await expect.poll(() => moduleCalls).toBe(2);
  await expect.poll(() => snapshotCalls).toBe(1);
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

test("fixture market boots through its real URL, API, main module and navigation", async ({
  page,
}) => {
  const registryPath = path.join(process.cwd(), "web/app/markets/registry.js");
  const registrySource = fs.readFileSync(registryPath, "utf8");
  await page.route("**/markets/registry.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: `${registrySource}
registerMarketAdapter(
  "fixture-market",
  (context) => {
    const base = createBitcoinAdapter(context);
    return {
      ...base,
      id: "fixture-market",
      title: "Fixture 期权",
      symbol: "FIX",
      currency: "USD",
      priceDigits: 3,
      provider: "fixture-provider",
      defaultProvider: "fixture-provider",
      async request(signal) {
        const response = await fetch(
          context.basePath + "/api/v1/fixture-market/snapshot?instrument=FIX",
          { cache: "no-store", signal },
        );
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      },
      merge(envelope) {
        return base.merge(envelope.payload);
      },
    };
  },
  { label: "Fixture期权" },
);`,
    }),
  );
  const apiResponse = page.waitForResponse((response) =>
    response.url().includes("/api/v1/fixture-market/snapshot"),
  );
  await page.goto("/fixture-market/desktop/");
  const response = await apiResponse;
  expect(response.status()).toBe(200);
  const envelope = await response.json();
  expect([envelope.market, envelope.provider, envelope.instrument]).toEqual([
    "fixture-market",
    "fixture-provider",
    "FIX",
  ]);
  await expect(page.locator("#title")).toHaveText("Fixture 期权");
  await expect(page.locator("#chainBody .sticky-strike.above")).toContainText(
    "1.234",
  );
  await expect(page.locator(".market-tabs [data-market]")).toHaveCount(3);
  await expect(
    page.locator('.market-tabs [data-market="fixture-market"]'),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.locator('.market-tabs [data-market="bitcoin"]'),
  ).toHaveAttribute("href", "/bitcoin/desktop/");
  const health = await page.request.get("/api/v1/fixture-market/health");
  expect(health.status()).toBe(200);
  expect(await health.json()).toMatchObject({
    status: "healthy",
    provider: "fixture-provider",
  });
  await page.locator('.market-tabs [data-market="bitcoin"]').click();
  await expect(page).toHaveURL(/\/bitcoin\/desktop\/$/);
  await expect(
    page.locator('.market-tabs [data-market="fixture-market"]'),
  ).toBeVisible();
  await page.locator('.market-tabs [data-market="fixture-market"]').click();
  await expect(page).toHaveURL(/\/fixture-market\/desktop\/$/);
  await page.goto("/fixture-market/mobile/");
  await expect(page.locator("#app")).toHaveClass(/mode-mobile/);
  await expect(page.locator("#title")).toHaveText("Fixture 期权");
});
