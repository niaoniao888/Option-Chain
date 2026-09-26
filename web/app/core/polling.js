/** A single-flight poller with abort, ordering, visibility and bounded timers. */
export class PollingController {
  constructor({
    request,
    commit,
    fail,
    interval = 5000,
    timeout = 4500,
    documentRef = document,
    timers = globalThis,
  }) {
    Object.assign(this, {
      request,
      commit,
      fail,
      interval,
      timeout,
      documentRef,
      timers,
    });
    this.sequence = 0;
    this.committed = 0;
    this.timer = null;
    this.controller = null;
    this.running = false;
    this.stopped = true;
    this.resumeRequested = false;
  }
  schedule(delay = this.interval) {
    if (this.stopped || this.timer !== null || this.documentRef?.hidden) return;
    this.timer = this.timers.setTimeout(
      () => {
        this.timer = null;
        this.tick();
      },
      Math.max(0, delay),
    );
  }
  async tick() {
    if (this.running || this.stopped || this.documentRef?.hidden) return;
    this.running = true;
    const sequence = ++this.sequence;
    const controller = new AbortController();
    this.controller = controller;
    const timeoutId = this.timers.setTimeout(
      () => controller.abort("timeout"),
      this.timeout,
    );
    let nextDelay = this.interval;
    try {
      const payload = await this.request(controller.signal, sequence);
      if (
        !this.stopped &&
        !this.documentRef?.hidden &&
        sequence > this.committed
      ) {
        this.committed = sequence;
        await this.commit(payload, sequence);
      }
    } catch (error) {
      const aborted = controller.signal.aborted;
      if (!aborted && !this.stopped && sequence >= this.committed) {
        const requested = this.fail?.(error, sequence);
        if (Number.isFinite(requested) && requested > 0) nextDelay = requested;
      } else if (
        aborted &&
        controller.signal.reason === "timeout" &&
        !this.stopped &&
        sequence >= this.committed
      ) {
        const requested = this.fail?.(new Error("请求超时"), sequence);
        if (Number.isFinite(requested) && requested > 0) nextDelay = requested;
      }
    } finally {
      this.timers.clearTimeout(timeoutId);
      if (this.controller === controller) this.controller = null;
      this.running = false;
      if (this.resumeRequested && !this.stopped && !this.documentRef?.hidden) {
        this.resumeRequested = false;
        queueMicrotask(() => this.tick());
      } else this.schedule(nextDelay);
    }
  }
  start() {
    if (!this.stopped) return;
    this.stopped = false;
    this.tick();
  }
  stop() {
    this.stopped = true;
    this.resumeRequested = false;
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = null;
    this.controller?.abort();
  }
  hidden() {
    this.resumeRequested = false;
    this.controller?.abort();
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = null;
  }
  visible() {
    if (this.stopped) return;
    if (this.running) this.resumeRequested = true;
    else this.tick();
  }
  get pendingTimers() {
    return Number(this.timer !== null) + Number(this.controller !== null);
  }
}

export async function fetchJson(
  url,
  { signal, timeoutLabel = "请求超时" } = {},
) {
  try {
    const response = await fetch(url, { cache: "no-store", signal });
    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      if (signal?.aborted) throw error;
      if (response.ok) throw new Error("响应数据无效");
      payload = { error: `HTTP ${response.status}` };
    }
    if (!response.ok) {
      const error = new Error(payload.error || `HTTP ${response.status}`);
      error.status = response.status;
      error.retryAfter = Number(response.headers.get("Retry-After"));
      throw error;
    }
    return payload;
  } catch (error) {
    if (signal?.aborted && signal.reason === "timeout")
      throw new Error(timeoutLabel);
    throw error;
  }
}

export async function withTimeout(
  request,
  timeout = 4500,
  timers = globalThis,
) {
  const controller = new AbortController(),
    timer = timers.setTimeout(() => controller.abort("timeout"), timeout);
  try {
    return await request(controller.signal);
  } catch (error) {
    if (controller.signal.aborted && controller.signal.reason === "timeout")
      throw new Error("请求超时");
    throw error;
  } finally {
    timers.clearTimeout(timer);
  }
}

export function errorMessage(error, fallback = "未知错误") {
  let message = typeof error === "string" ? error : "";
  try {
    if (!message && typeof error?.message === "string") message = error.message;
  } catch {
    message = "";
  }
  return message.trim() || fallback;
}

export function retryDelay(error, fallback = 5000) {
  const seconds = Number(error?.retryAfter);
  return Number.isFinite(seconds) && seconds > 0
    ? Math.min(300, seconds) * 1000
    : fallback;
}
