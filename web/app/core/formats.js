/** Display-only formatters. They never calculate financial values. */
export const finite = (value) =>
  typeof value === "number" && Number.isFinite(value);
export const number = (value, digits = 2) =>
  finite(value)
    ? value.toLocaleString("zh-CN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })
    : "—";
export const percent = (value, digits = 2) =>
  finite(value) ? `${number(value, digits)}%` : "—";
export const remaining = (seconds) => {
  if (!finite(seconds) || seconds < 0) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return days
    ? `${days}天 ${hours}小时`
    : hours
      ? `${hours}小时 ${minutes}分`
      : `${minutes}分`;
};
export const date = (value) => {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value))
    return value;
  const time = Number(value);
  if (!finite(time)) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
    .format(new Date(time))
    .replaceAll("/", "-");
};
export const dateTime = (value) => {
  const time = typeof value === "number" ? value : Date.parse(value);
  if (!finite(time)) return "—";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(new Date(time));
  const get = (type) => parts.find((part) => part.type === type)?.value || "";
  return `${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")}`;
};
export const chinaDateTimeMinute = (value) => {
  const time =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim()
        ? Date.parse(value)
        : NaN;
  if (!finite(time)) return "—";
  const instant = new Date(time);
  if (!Number.isFinite(instant.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(instant);
  const get = (type) => parts.find((part) => part.type === type)?.value || "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
};
export const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>'"]/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        c
      ],
  );
export const compactDateHtml = (value) => {
  const text = date(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return escapeHtml(text);
  return `<span class="date-year">${text.slice(0, 4)}</span><span class="date-rest">-${text.slice(5)}</span>`;
};
