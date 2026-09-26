export function bindMenu({ trigger, menu, onSelect }) {
  const options = () => [
    ...menu.querySelectorAll('[role="option"]:not([disabled])'),
  ];
  const close = (focus = false) => {
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    if (focus) trigger.focus();
  };
  const open = () => {
    if (!options().length) return;
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    const rect = trigger.getBoundingClientRect(),
      height = Math.min(menu.scrollHeight || 270, 270);
    menu.classList.toggle(
      "open-up",
      innerHeight - rect.bottom < height && rect.top > height,
    );
    (
      options().find((x) => x.getAttribute("aria-selected") === "true") ||
      options()[0]
    )?.focus();
  };
  trigger.addEventListener("click", () => (menu.hidden ? open() : close()));
  trigger.addEventListener("keydown", (event) => {
    if (["ArrowDown", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      open();
    }
  });
  menu.addEventListener("click", (event) => {
    const option = event.target.closest('[role="option"]');
    if (option) {
      onSelect(option.dataset.value);
      close(true);
    }
  });
  menu.addEventListener("keydown", (event) => {
    const list = options(),
      at = list.indexOf(document.activeElement);
    if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      list[
        (at + (event.key === "ArrowDown" ? 1 : -1) + list.length) % list.length
      ]?.focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      list[event.key === "Home" ? 0 : list.length - 1]?.focus();
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      document.activeElement?.click();
    }
  });
  document.addEventListener("click", (event) => {
    if (
      !menu.hidden &&
      !menu.contains(event.target) &&
      event.target !== trigger
    )
      close();
  });
  return { open, close };
}

export function menuOptions(items, selected, label = (value) => String(value)) {
  return items
    .map(
      (value) =>
        `<button type="button" role="option" data-value="${escapeHtml(value)}" aria-selected="${value === selected}">${escapeHtml(label(value))}</button>`,
    )
    .join("");
}
import { escapeHtml } from "../core/formats.js";

/** Render untrusted menu content without inserting HTML. */
export function renderMenuOptions(menu, items, selected, describe) {
  menu.replaceChildren();
  for (const value of items) {
    const description = describe(value);
    const button = document.createElement("button");
    button.type = "button";
    button.role = "option";
    button.dataset.value = String(value);
    button.setAttribute("aria-selected", String(value === selected));
    if (typeof description === "string") {
      button.textContent = description;
    } else {
      const primary = document.createElement("span");
      primary.className = "menu-primary";
      primary.textContent = description.primary ?? "";
      button.append(primary);
      if (description.secondary) {
        const secondary = document.createElement("span");
        secondary.className = `menu-secondary ${description.tone || ""}`.trim();
        secondary.textContent = description.secondary;
        button.append(secondary);
      }
    }
    menu.append(button);
  }
}
