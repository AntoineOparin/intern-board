"use strict";
// Custom dropdowns that look the same in Safari, Chrome and Firefox.
//
// Each <select> stays in the page (hidden) and remains the source of truth: code keeps reading
// and setting select.value, and picking an option fires the usual "input" and "change" events.
// Options added later (innerHTML), programmatic value changes and the disabled state are all
// mirrored. On touch screens the native picker is kept, since it works better there.
(() => {
  if (!matchMedia("(pointer: fine)").matches) return;

  const nativeValue = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  const nativeIndex = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "selectedIndex");
  let openOne = null;
  let uid = 0;

  function enhance(select) {
    if (select.dataset.ui || select.multiple || select.size > 1) return;
    select.dataset.ui = "1";
    const id = `ui-select-${++uid}`;
    const wrap = document.createElement("span");
    wrap.className = "ui-select";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ui-select-button";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", id);
    const label = select.getAttribute("aria-label") || select.closest("label")?.querySelector("span")?.textContent;
    if (label) button.setAttribute("aria-label", label.trim());
    button.innerHTML = '<span class="ui-select-value"></span><svg class="ui-select-caret" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>';
    const list = document.createElement("ul");
    list.className = "ui-select-list";
    list.id = id;
    list.setAttribute("role", "listbox");
    list.hidden = true;

    select.parentNode.insertBefore(wrap, select);
    wrap.append(select, button, list);
    select.classList.add("ui-select-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    let active = -1;

    const sync = () => {
      const opt = select.options[nativeIndex.get.call(select)];
      button.querySelector(".ui-select-value").textContent = opt ? opt.textContent : "";
      button.disabled = select.disabled;
      // Mirror state classes the app puts on the select (e.g. "set" for an active filter).
      wrap.className = ["ui-select", ...[...select.classList].filter(c => c !== "ui-select-native")].join(" ");
      if (!list.hidden) render();
    };

    const render = () => {
      const current = nativeIndex.get.call(select);
      list.innerHTML = "";
      [...select.options].forEach((opt, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.id = `${id}-${i}`;
        li.textContent = opt.textContent;
        li.setAttribute("aria-selected", String(i === current));
        if (opt.disabled) li.setAttribute("aria-disabled", "true");
        if (i === active) li.classList.add("active");
        li.addEventListener("mousedown", e => e.preventDefault()); // keep focus on the button
        li.addEventListener("click", () => { if (!opt.disabled) choose(i); });
        li.addEventListener("mousemove", () => setActive(i, false));
        list.append(li);
      });
      button.setAttribute("aria-activedescendant", active >= 0 ? `${id}-${active}` : "");
    };

    const setActive = (i, scroll = true) => {
      active = i;
      list.querySelectorAll(".active").forEach(el => el.classList.remove("active"));
      const el = list.children[i];
      if (el) {
        el.classList.add("active");
        if (scroll) el.scrollIntoView({ block: "nearest" });
      }
      button.setAttribute("aria-activedescendant", el ? el.id : "");
    };

    const open = () => {
      if (select.disabled) return;
      openOne?.close();
      openOne = api;
      active = nativeIndex.get.call(select);
      list.hidden = false;
      wrap.classList.add("open");
      // Open upwards when there's no room below.
      const rect = button.getBoundingClientRect();
      wrap.classList.toggle("up", innerHeight - rect.bottom < 260 && rect.top > innerHeight - rect.bottom);
      button.setAttribute("aria-expanded", "true");
      render();
      list.children[active]?.scrollIntoView({ block: "nearest" });
    };

    const close = () => {
      if (list.hidden) return;
      list.hidden = true;
      wrap.classList.remove("open");
      button.setAttribute("aria-expanded", "false");
      if (openOne === api) openOne = null;
    };

    const choose = i => {
      const changed = i !== nativeIndex.get.call(select);
      nativeIndex.set.call(select, i);
      sync();
      close();
      button.focus();
      if (changed) {
        select.dispatchEvent(new Event("input", { bubbles: true }));
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
    };

    const step = (from, dir) => {
      for (let i = from + dir; i >= 0 && i < select.options.length; i += dir) {
        if (!select.options[i].disabled) return i;
      }
      return from;
    };

    let typed = "", typedAt = 0;
    button.addEventListener("click", () => (list.hidden ? open() : close()));
    button.addEventListener("keydown", e => {
      const isOpen = !list.hidden;
      if (["ArrowDown", "ArrowUp"].includes(e.key)) {
        e.preventDefault();
        if (!isOpen) return open();
        setActive(step(active, e.key === "ArrowDown" ? 1 : -1));
      } else if (e.key === "Home" || e.key === "End") {
        if (!isOpen) return;
        e.preventDefault();
        setActive(e.key === "Home" ? step(-1, 1) : step(select.options.length, -1));
      } else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (isOpen && active >= 0) choose(active); else open();
      } else if (e.key === "Escape" && isOpen) {
        e.preventDefault();
        e.stopPropagation(); // don't also close a surrounding dialog
        close();
      } else if (e.key === "Tab") {
        close();
      } else if (e.key.length === 1 && /\S/.test(e.key)) {
        // Type to jump to an option.
        typed = Date.now() - typedAt > 700 ? e.key.toLowerCase() : typed + e.key.toLowerCase();
        typedAt = Date.now();
        const i = [...select.options].findIndex(o => o.textContent.trim().toLowerCase().startsWith(typed));
        if (i >= 0) { if (isOpen) setActive(i); else { nativeIndex.set.call(select, i); sync(); select.dispatchEvent(new Event("input", { bubbles: true })); select.dispatchEvent(new Event("change", { bubbles: true })); } }
      }
    });
    button.addEventListener("blur", () => setTimeout(() => { if (!wrap.contains(document.activeElement)) close(); }, 0));

    // Keep the button in step with code that changes the select directly.
    Object.defineProperty(select, "value", {
      configurable: true,
      get() { return nativeValue.get.call(this); },
      set(v) { nativeValue.set.call(this, v); sync(); },
    });
    Object.defineProperty(select, "selectedIndex", {
      configurable: true,
      get() { return nativeIndex.get.call(this); },
      set(v) { nativeIndex.set.call(this, v); sync(); },
    });
    new MutationObserver(sync).observe(select, { childList: true, subtree: true, attributes: true,
                                                 attributeFilter: ["disabled", "class", "selected"] });
    select.addEventListener("change", sync);
    select.form?.addEventListener("reset", () => setTimeout(sync, 0));

    const api = { close };
    sync();
  }

  document.addEventListener("mousedown", e => {
    if (openOne && !e.target.closest(".ui-select.open")) openOne.close();
  });
  addEventListener("resize", () => openOne?.close());

  const scan = root => root.querySelectorAll?.("select:not([data-ui])").forEach(enhance);
  scan(document);
  new MutationObserver(records => {
    for (const r of records) for (const n of r.addedNodes) {
      if (n.nodeType !== 1) continue;
      if (n.tagName === "SELECT") enhance(n); else scan(n);
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
