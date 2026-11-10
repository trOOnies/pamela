// Pamela frontend - vanilla JS, no build step.
// Views are routed by URL hash: #/ (today), #/day/YYYY-MM-DD, #/foods, #/meals, #/history,
// #/settings, #/help

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const MACROS = [
  { key: "protein_g", label: "Protein", short: "P", color: "var(--c-protein)" },
  { key: "carbs_g", label: "Carbs", short: "C", color: "var(--c-carbs)" },
  { key: "fat_g", label: "Fat", short: "F", color: "var(--c-fat)" },
  { key: "fiber_g", label: "Fiber", short: "Fib", color: "var(--c-fiber)" },
];
const MOOD_EMOJI = { 1: "😣", 2: "🙁", 3: "😐", 4: "🙂", 5: "😄" };

const state = {
  config: null,
  vocab: null,          // diet tags, moods and feelings (labels come from the backend)
  activityTypes: [],
  savedMeals: [],
  view: "day",
  day: todayISO(),
  dayData: null,
  foods: [],            // full catalog (Foods view)
  foodTagFilter: new Set(),
  editingFoodId: null,
  selectedFood: null,   // food chosen in the entry form
  draft: null,          // saved meal being prepared for logging: { name, items }
  smItems: [],          // items of the saved meal in the editor
  editingSavedMealId: null,
  editingTypeId: null,
  historyRange: 30,
};

// --- helpers -----------------------------------------------------------------

function todayISO() {
  return toISO(new Date());
}
function toISO(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function parseISO(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}
function addDays(iso, n) {
  const d = parseISO(iso);
  d.setDate(d.getDate() + n);
  return toISO(d);
}
const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short" });
function fmtDay(iso) {
  return dayFmt.format(parseISO(iso));
}
function fmt(n, digits = 0) {
  if (n == null || Number.isNaN(n)) return "–";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
function fmtQty(n) {
  return fmt(n, n < 10 ? 2 : 1);
}
/** Minutes as "7:30". */
function fmtSleep(min) {
  if (min == null) return "–";
  const m = Math.round(min);
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
}
/** "7:30", "7h30", "7h", "7.5" or "7,5" -> minutes; "" -> null; anything else -> NaN. */
function parseSleep(s) {
  s = s.trim().toLowerCase();
  if (!s) return null;
  const hm = s.match(/^(\d{1,2})\s*(?::|h)\s*(\d{1,2})?\s*m?$/);
  if (hm) {
    const min = Number(hm[1]) * 60 + Number(hm[2] || 0);
    return Number(hm[2] || 0) < 60 && min <= 1440 ? min : NaN;
  }
  const h = Number(s.replace(",", "."));
  return Number.isFinite(h) && h >= 0 && h <= 24 ? Math.round(h * 60) : NaN;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function num(v) {
  if (v === "" || v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}
/** Looks like an EAN-8, UPC-A, EAN-13 or GTIN-14 barcode. */
function isBarcode(q) {
  return /^(\d{8}|\d{12,14})$/.test(q.replace(/[\s-]/g, ""));
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, opts);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    if (data && typeof data.detail === "string") msg = data.detail;
    else if (data && Array.isArray(data.detail)) {
      msg = data.detail
        .map((e) => `${(e.loc || []).filter((l) => l !== "body").join(".")}: ${e.msg.replace(/^Value error, /, "")}`)
        .join("\n");
    }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}

let toastTimer;
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), isError ? 5000 : 1800);
}
function showError(err) {
  console.error(err);
  toast(err.message || String(err), true);
}
function banner(msg) {
  const el = $("#banner");
  el.textContent = msg || "";
  el.hidden = !msg;
}

function formValues(form) {
  return Object.fromEntries(new FormData(form).entries());
}

/** Colored diet tag pills for a food (booleans) or a list of tag keys. */
function tagPills(src, cls = "") {
  const keys = Array.isArray(src) ? src : state.vocab.diet_tags.map((t) => t.key).filter((k) => src[k]);
  if (!keys.length) return "";
  const label = (k) => state.vocab.diet_tags.find((t) => t.key === k)?.label ?? k;
  return `<span class="tags ${cls}">${keys.map((k) => `<span class="tag tag-${k}">${esc(label(k))}</span>`).join("")}</span>`;
}

// --- config & shared data ------------------------------------------------------

async function loadConfig() {
  try {
    state.config = await api("GET", "/config");
    banner("");
  } catch (err) {
    // Typically a typo in info/config.toml - show it until it's fixed.
    banner(`Config problem: ${err.message}`);
    if (!state.config) throw err;
  }
}

async function loadActivityTypes() {
  state.activityTypes = await api("GET", "/activity-types");
  fillActivitySelect();
}

async function loadSavedMeals() {
  state.savedMeals = await api("GET", "/saved-meals");
  fillSavedPick();
}

function fillConfigControls() {
  const cfg = state.config;
  const mealSel = $("#entry-meal");
  const prevMeal = mealSel.value;
  mealSel.innerHTML = cfg.meals.names.map((m) => `<option>${esc(m)}</option>`).join("");
  if (cfg.meals.names.includes(prevMeal)) mealSel.value = prevMeal;
  else mealSel.value = defaultMeal();

  const smSel = $("#sm-default-meal");
  const prevSm = smSel.value;
  smSel.innerHTML = `<option value="">Any meal</option>` + cfg.meals.names.map((m) => `<option>${esc(m)}</option>`).join("");
  smSel.value = cfg.meals.names.includes(prevSm) ? prevSm : "";
  updateActivityForm();
  updateDraftCommit();
}

/** Guess the meal from the time of day, spreading configured meals over 06:00-22:00. */
function defaultMeal() {
  const names = state.config.meals.names;
  if (state.day !== todayISO()) return names[0];
  const h = new Date().getHours() + new Date().getMinutes() / 60;
  const frac = Math.min(Math.max((h - 6) / 16, 0), 0.999);
  return names[Math.floor(frac * names.length)];
}

/** Static controls built from the vocabulary: diet tag checkboxes and filters. */
function buildVocabControls() {
  const tags = state.vocab.diet_tags;
  $("#tag-picks").insertAdjacentHTML(
    "beforeend",
    tags.map((t) => `<label class="tag-pick tag-${t.key}"><input type="checkbox" name="${t.key}"><span>${esc(t.label)}</span></label>`).join("")
  );
  $("#tag-filter").innerHTML = tags
    .map((t) => `<button type="button" class="chip tag-chip tag-${t.key}" data-tag="${t.key}" aria-pressed="false">${esc(t.label)}</button>`)
    .join("");
}

// --- routing -----------------------------------------------------------------

const VIEWS = ["day", "foods", "meals", "history", "settings", "help"];

function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  let view = parts[0] || "day";
  if (!VIEWS.includes(view)) view = "day";
  state.view = view;
  if (view === "day") {
    const d = parts[1];
    state.day = d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : todayISO();
  }
  for (const v of VIEWS) $(`#view-${v}`).hidden = v !== view;
  for (const a of $$("[data-nav]")) {
    if (a.dataset.nav === view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  $("#daynav").style.visibility = view === "day" ? "visible" : "hidden";
  render();
}

function render() {
  if (!state.config) return;
  if (state.view === "day") return loadDay();
  if (state.view === "foods") return loadFoods();
  if (state.view === "meals") return loadMealsView();
  if (state.view === "history") return loadHistory();
  if (state.view === "settings") return loadSettings();
  if (state.view === "help") return renderHelp();
}

function goDay(iso) {
  location.hash = iso === todayISO() ? "#/" : `#/day/${iso}`;
}

// --- food search combobox (shared) ------------------------------------------------

/**
 * Wires a search input + listbox to the food catalog.
 * onPick(food) is called on a choice; onCreate(query), if given, adds a last
 * "create / look up" option. Enter never submits a form unless canSubmit() says so.
 */
function foodCombo({ input, list, onPick, onCreate, onInput, canSubmit = () => false }) {
  // pending: a search is waiting (debounce or request). Enter meanwhile is held
  // and picks the first fresh result, so fast typing and barcode scanners
  // (digits + Enter in a few ms) never pick a stale suggestion.
  const c = { results: [], active: -1, seq: 0, pending: false, pickOnArrive: false };
  const idp = list.id;

  function close() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    c.active = -1;
  }

  function render() {
    const q = input.value.trim();
    let html = c.results
      .map(
        (f, i) => `<li role="option" id="${idp}-${i}" data-i="${i}" aria-selected="${i === c.active}">
          <span class="s-name">${esc(f.name)} ${f.brand ? `<span class="brand-tag">${esc(f.brand)}</span>` : ""}${tagPills(f, "mini")}</span>
          <span class="meta">${fmt(f.kcal)} kcal / ${fmtQty(f.basis_qty)} ${esc(f.unit)}</span></li>`
      )
      .join("");
    if (q && onCreate) {
      const label = isBarcode(q) ? `+ Look up barcode ${esc(q)} in Foods` : `+ Create “${esc(q)}” in Foods`;
      html += `<li role="option" class="create" data-create="1" id="${idp}-create" aria-selected="${c.active === c.results.length}"><span>${label}</span></li>`;
    }
    if (q && !onCreate && !c.results.length) html = `<li class="none" aria-disabled="true"><span>No foods match</span></li>`;
    list.innerHTML = html;
    list.hidden = !html;
    input.setAttribute("aria-expanded", String(!!html));
    const active = c.active >= 0 ? $(`[aria-selected="true"]`, list) : null;
    if (active) {
      input.setAttribute("aria-activedescendant", active.id);
      active.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  const search = debounce(async () => {
    const q = input.value.trim();
    const seq = ++c.seq;
    try {
      const foods = await api("GET", `/foods?limit=12&q=${encodeURIComponent(q)}`);
      if (seq !== c.seq) return;
      c.pending = false;
      c.results = foods;
      c.active = foods.length ? 0 : -1;
      if (c.pickOnArrive) {
        c.pickOnArrive = false;
        if (foods.length) return pick(0);
      }
      if (document.activeElement === input) render();
    } catch (err) {
      c.pending = c.pickOnArrive = false;
      showError(err);
    }
  }, 120);

  function pick(i) {
    if (i < 0) return;
    if (i >= c.results.length) {
      if (!onCreate) return;
      const q = input.value.trim();
      close();
      onCreate(q);
      return;
    }
    const food = c.results[i];
    close();
    onPick(food);
  }

  const startSearch = () => {
    c.pending = true;
    c.pickOnArrive = false;
    search();
  };
  input.addEventListener("input", () => {
    onInput?.();
    startSearch();
  });
  input.addEventListener("focus", startSearch);
  input.addEventListener("blur", () => setTimeout(close, 150));
  input.addEventListener("keydown", (e) => {
    const n = c.results.length + (input.value.trim() && onCreate ? 1 : 0);
    if (e.key === "ArrowDown" && n) {
      e.preventDefault();
      c.active = (c.active + 1) % n;
      render();
    } else if (e.key === "ArrowUp" && n) {
      e.preventDefault();
      c.active = (c.active - 1 + n) % n;
      render();
    } else if (e.key === "Enter") {
      if (c.pending && input.value.trim()) {
        e.preventDefault();
        c.pickOnArrive = true;
      } else if (!list.hidden && c.active >= 0) {
        e.preventDefault();
        pick(c.active);
      } else if (!canSubmit()) {
        e.preventDefault();
      }
    } else if (e.key === "Escape") {
      close();
    }
  });
  // mousedown (not click) so it fires before the input's blur closes the list
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[role=option]");
    e.preventDefault();
    if (li) pick(li.dataset.create ? c.results.length : Number(li.dataset.i));
  });
  return { close };
}

// --- editable item tables (saved meal draft and editor) ---------------------------

/** A food as an item: macros are kept per 1 unit so any amount can be recomputed. */
function itemFromFood(f, quantity) {
  const per = { kcal: f.kcal / f.basis_qty };
  for (const m of MACROS) per[m.key] = f[m.key] / f.basis_qty;
  return { food_id: f.id, name: f.name, brand: f.brand, unit: f.unit, per, quantity: quantity ?? f.serving_qty ?? f.basis_qty };
}
/** A saved meal item (macros already scaled to its quantity) as an item. */
function itemFromSaved(it) {
  const per = { kcal: it.kcal / it.quantity };
  for (const m of MACROS) per[m.key] = it[m.key] / it.quantity;
  return { food_id: it.food_id, name: it.name, brand: it.brand, unit: it.unit, per, quantity: it.quantity };
}
function itemMacros(it) {
  const q = it.quantity > 0 ? it.quantity : 0;
  const o = { kcal: it.per.kcal * q };
  for (const m of MACROS) o[m.key] = it.per[m.key] * q;
  return o;
}
function itemsTotals(items) {
  const t = { kcal: 0 };
  for (const m of MACROS) t[m.key] = 0;
  for (const it of items) {
    const o = itemMacros(it);
    for (const k in t) t[k] += o[k];
  }
  return t;
}

function itemsTable({ tbody, tfoot, getItems, fiber, empty, onChange }) {
  const keys = ["kcal", ...MACROS.filter((m) => fiber || m.key !== "fiber_g").map((m) => m.key)];
  const cells = (o) => keys.map((k) => `<td class="n" data-k="${k}">${fmt(o[k], k === "kcal" ? 0 : 1)}</td>`).join("");
  const cols = keys.length + 3;

  function foot() {
    const items = getItems();
    tfoot.innerHTML = items.length ? `<tr><td>Total</td><td></td>${cells(itemsTotals(items))}<td></td></tr>` : "";
  }
  function render() {
    const items = getItems();
    tbody.innerHTML = items.length
      ? items
          .map(
            (it, i) => `<tr data-i="${i}">
          <td>${esc(it.name)}${it.brand ? ` <span class="brand-tag">${esc(it.brand)}</span>` : ""}</td>
          <td class="n"><span class="with-unit qty-cell"><input class="qty-input" type="number" min="0" step="any" value="${it.quantity}" data-qty-i="${i}" aria-label="Amount of ${esc(it.name)}"><span class="unit">${esc(it.unit)}</span></span></td>
          ${cells(itemMacros(it))}
          <td class="act"><button type="button" class="row-btn del" data-del-i="${i}" title="Remove" aria-label="Remove ${esc(it.name)}">✕</button></td>
        </tr>`
          )
          .join("")
      : `<tr class="empty"><td colspan="${cols}">${empty}</td></tr>`;
    foot();
  }
  tbody.addEventListener("input", (e) => {
    const input = e.target.closest("[data-qty-i]");
    if (!input) return;
    const i = Number(input.dataset.qtyI);
    const it = getItems()[i];
    it.quantity = num(input.value) ?? 0;
    const o = itemMacros(it);
    for (const td of $$(`tr[data-i="${i}"] td[data-k]`, tbody)) td.textContent = fmt(o[td.dataset.k], td.dataset.k === "kcal" ? 0 : 1);
    foot();
    onChange?.();
  });
  tbody.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.closest("[data-qty-i]")) e.preventDefault();
  });
  tbody.addEventListener("click", (e) => {
    const del = e.target.closest("[data-del-i]");
    if (!del) return;
    getItems().splice(Number(del.dataset.delI), 1);
    render();
    onChange?.();
  });
  return { render };
}

// --- day view ----------------------------------------------------------------

async function loadDay() {
  $("#day-input").value = state.day;
  document.title = `${fmtDay(state.day)} · Pamela`;
  const day = state.day;
  try {
    const data = await api("GET", `/days/${day}`);
    if (day !== state.day) return; // user navigated meanwhile
    state.dayData = data;
    renderSummary();
    renderLog();
    renderCheckin();
    renderActivities();
    renderDraft();
  } catch (err) {
    showError(err);
  }
}

function meterPct(value, target) {
  if (!target) return 0;
  return Math.min(100, (value / target) * 100);
}

function renderSummary() {
  const { totals, burned_kcal, active_min } = state.dayData;
  const t = state.config.targets;
  const left = t.kcal - totals.kcal;
  const sub = t.kcal
    ? left >= 0
      ? `${fmt(left)} kcal left of ${fmt(t.kcal)}`
      : `<span class="over">${fmt(-left)} kcal over</span> target of ${fmt(t.kcal)}`
    : "no kcal target set";

  const macroRows = MACROS.map((m) => {
    const v = totals[m.key];
    const target = t[m.key];
    const over = target && v > target;
    return `
      <div class="macro-row" style="--c:${m.color}">
        <div class="lbl"><b>${m.label}</b>
          <span class="val">${fmt(v)}${target ? ` / ${fmt(target)} g` : " g"}${over ? ` <span class="over">+${fmt(v - target)}</span>` : ""}</span></div>
        <div class="meter" role="meter" aria-label="${m.label}" aria-valuemin="0" aria-valuemax="${target}" aria-valuenow="${Math.round(v)}"><span style="width:${meterPct(v, target)}%"></span></div>
      </div>`;
  }).join("");

  $("#summary").innerHTML = `
    <div class="sum-kcal" style="--c:var(--c-kcal)">
      <div class="big">${fmt(totals.kcal)} <small>kcal eaten</small></div>
      <div class="sub">${sub}</div>
      <div class="meter" role="meter" aria-label="Calories" aria-valuemin="0" aria-valuemax="${t.kcal}" aria-valuenow="${Math.round(totals.kcal)}"><span style="width:${meterPct(totals.kcal, t.kcal)}%"></span></div>
    </div>
    <div class="sum-macros">${macroRows}</div>
    <div class="sum-act">
      <div class="stat"><div class="k">Burned</div><div class="v">${fmt(burned_kcal)}</div></div>
      <div class="stat"><div class="k">Net kcal</div><div class="v">${fmt(totals.kcal - burned_kcal)}</div></div>
      <div class="stat"><div class="k">Active</div><div class="v">${fmt(active_min)}<small> min</small></div></div>
    </div>`;
}

function macroCells(o) {
  return `<td class="n">${fmt(o.kcal)}</td>` + MACROS.map((m) => `<td class="n">${fmt(o[m.key], 1)}</td>`).join("");
}

function renderLog() {
  const { entries, totals } = state.dayData;
  const meals = [...state.config.meals.names];
  // Entries logged under a meal that was since removed from the config still show up.
  for (const e of entries) if (!meals.includes(e.meal)) meals.push(e.meal);

  let html = "";
  for (const meal of meals) {
    const rows = entries.filter((e) => e.meal === meal);
    const sub = { kcal: 0 };
    for (const m of MACROS) sub[m.key] = 0;
    for (const e of rows) {
      sub.kcal += e.kcal;
      for (const m of MACROS) sub[m.key] += e[m.key];
    }
    const canAdd = state.config.meals.names.includes(meal);
    const canSave = rows.some((e) => e.food_id != null);
    const btns =
      (canAdd ? `<button type="button" class="row-btn add-to" data-add-meal="${esc(meal)}">+ add</button>` : "") +
      (canSave ? `<button type="button" class="row-btn add-to" data-save-meal="${esc(meal)}" title="Keep these foods as a saved meal">☆ save</button>` : "");
    html += `<tr class="meal-head"><td>${esc(meal)}</td><td class="n head-btns">${btns}</td>${
      rows.length ? macroCells(sub) : '<td colspan="5"></td>'
    }<td></td></tr>`;
    if (!rows.length) {
      html += `<tr class="empty"><td colspan="8">Nothing logged</td></tr>`;
      continue;
    }
    for (const e of rows) {
      const amount = e.quantity != null ? `${fmtQty(e.quantity)} ${esc(e.unit)}` : "";
      const qtyAttrs = e.food_id != null ? ` class="n qty" data-edit-qty="${e.id}" title="Click to change amount"` : ' class="n"';
      html += `<tr data-entry="${e.id}">
        <td>${esc(e.name)}${e.food_id == null ? '<span class="quick-tag">quick</span>' : ""}</td>
        <td${qtyAttrs}>${amount}</td>
        ${macroCells(e)}
        <td class="act"><button type="button" class="row-btn del" data-del-entry="${e.id}" title="Delete" aria-label="Delete ${esc(e.name)}">✕</button></td>
      </tr>`;
    }
  }
  $("#log-body").innerHTML = html;

  let foot = $("#log-table tfoot");
  if (!foot) {
    foot = document.createElement("tfoot");
    $("#log-table").append(foot);
  }
  foot.innerHTML = `<tr><td>Total</td><td></td>${macroCells(totals)}<td></td></tr>`;
}

async function saveMealAsSaved(meal) {
  const rows = state.dayData.entries.filter((e) => e.meal === meal && e.food_id != null);
  const skipped = state.dayData.entries.filter((e) => e.meal === meal && e.food_id == null).length;
  const note = skipped ? ` (${skipped} quick-add ${skipped === 1 ? "entry is" : "entries are"} left out)` : "";
  const name = prompt(`Name for a saved meal with these ${rows.length} foods${note}:`, meal);
  if (!name || !name.trim()) return;
  try {
    await api("POST", "/saved-meals", {
      name: name.trim(),
      default_meal: meal,
      items: rows.map((e) => ({ food_id: e.food_id, quantity: e.quantity })),
    });
    await loadSavedMeals();
    toast(`Saved “${name.trim()}”`);
  } catch (err) {
    showError(err);
  }
}

function renderActivities() {
  const { activities } = state.dayData;
  if (!activities.length) {
    $("#act-list").innerHTML = '<li class="empty">No activity logged</li>';
    return;
  }
  $("#act-list").innerHTML = activities
    .map((a) => {
      const bits = [`${fmt(a.duration_min)} min`];
      if (a.distance_km != null) bits.push(`${fmt(a.distance_km, 2)} km`);
      if (a.distance_km && a.duration_min) {
        const pace = a.duration_min / a.distance_km;
        bits.push(`${Math.floor(pace)}:${String(Math.round((pace % 1) * 60)).padStart(2, "0")} /km`);
      }
      return `<li>
        <div><span class="t">${esc(a.type)}</span> <span class="d">${bits.join(" · ")}</span></div>
        <span class="kc">${fmt(a.kcal)} <small>kcal${a.kcal_estimated ? " (est.)" : ""}</small></span>
        <button type="button" class="row-btn del" data-del-activity="${a.id}" title="Delete" aria-label="Delete ${esc(a.type)}">✕</button>
        ${a.notes ? `<div class="notes">${esc(a.notes)}</div>` : ""}
      </li>`;
    })
    .join("");
}

// check-in: steps, sleep, mood ---------------------------------------------------------

function renderCheckin() {
  const m = state.dayData.metrics;
  const t = state.config.targets;
  const steps = $("#steps-input"), sleep = $("#sleep-input");
  // don't clobber what the user is typing
  if (document.activeElement !== steps) steps.value = m.steps ?? "";
  if (document.activeElement !== sleep) sleep.value = m.sleep_min != null ? fmtSleep(m.sleep_min) : "";
  sleep.classList.remove("invalid");

  $("#steps-bar").style.width = `${meterPct(m.steps ?? 0, t.steps)}%`;
  $("#steps-sub").textContent = t.steps ? `${fmt(m.steps ?? 0)} of ${fmt(t.steps)}` : "";
  const sleepTarget = t.sleep_h * 60;
  $("#sleep-bar").style.width = `${meterPct(m.sleep_min ?? 0, sleepTarget)}%`;
  $("#sleep-sub").textContent = sleepTarget ? `${fmtSleep(m.sleep_min ?? 0)} of ${fmtSleep(sleepTarget)} h` : "";

  $("#mood-scale").innerHTML = state.vocab.moods
    .map((md) => {
      const on = m.mood === Number(md.key);
      return `<button type="button" class="mood mood-${md.key}" role="radio" aria-checked="${on}" data-mood="${md.key}" title="${esc(md.label)}">
        <span class="emoji" aria-hidden="true">${MOOD_EMOJI[md.key] ?? ""}</span><span class="lbl">${esc(md.label)}</span></button>`;
    })
    .join("");
  $("#feelings").innerHTML = state.vocab.feelings
    .map((f) => `<button type="button" class="chip" data-feeling="${f.key}" aria-pressed="${m.feelings.includes(f.key)}">${esc(f.label)}</button>`)
    .join("");
}

let checkinStatusTimer;
async function saveCheckin(patch) {
  const day = state.day;
  const body = { ...state.dayData.metrics, ...patch };
  const status = $("#checkin-status");
  try {
    const saved = await api("PUT", `/days/${day}/metrics`, body);
    if (day !== state.day) return;
    state.dayData.metrics = saved;
    renderCheckin();
    status.textContent = "Saved";
    clearTimeout(checkinStatusTimer);
    checkinStatusTimer = setTimeout(() => (status.textContent = ""), 1500);
  } catch (err) {
    showError(err);
  }
}

function commitSteps() {
  const raw = $("#steps-input").value.trim();
  const steps = raw === "" ? null : Math.round(num(raw) ?? -1);
  if (steps != null && steps < 0) return toast("Steps must be a positive number", true);
  if (steps !== state.dayData.metrics.steps) saveCheckin({ steps });
}

function commitSleep() {
  const input = $("#sleep-input");
  const min = parseSleep(input.value);
  if (Number.isNaN(min)) {
    input.classList.add("invalid");
    return toast("Sleep: type hours like 7:30, 7.5 or 7h30", true);
  }
  input.classList.remove("invalid");
  if (min !== state.dayData.metrics.sleep_min) saveCheckin({ sleep_min: min });
  else if (min != null) input.value = fmtSleep(min);
}

// entry form -------------------------------------------------------------------

function entryMode() {
  return $('input[name="entry-mode"]:checked').value;
}

function setEntryMode(mode) {
  $(`input[name="entry-mode"][value="${mode}"]`).checked = true;
  $("#entry-form").dataset.mode = mode;
  if (mode === "saved") fillSavedPick();
}

function portionOptions(f) {
  const o = [];
  if (f.serving_qty) o.push(["1 serving", f.serving_qty], ["2 servings", f.serving_qty * 2]);
  if (f.package_qty) o.push(["¼ pack", f.package_qty / 4], ["½ pack", f.package_qty / 2], ["Whole pack", f.package_qty]);
  return o;
}

function updatePreview() {
  const f = state.selectedFood;
  const qty = num($("#entry-qty").value);
  $("#entry-unit").textContent = f ? f.unit : "g";
  const chips = $("#portion-chips");
  if (!f) {
    $("#entry-preview").textContent = "";
    chips.innerHTML = "";
    return;
  }
  chips.innerHTML = portionOptions(f)
    .map(([label, q]) => `<button type="button" class="chip" data-portion="${q}" aria-pressed="${qty != null && Math.abs(qty - q) < 1e-6}">${label} <small>${fmtQty(q)} ${esc(f.unit)}</small></button>`)
    .join("");
  if (!qty) {
    $("#entry-preview").textContent = `${f.name}: ${fmt(f.kcal)} kcal per ${fmtQty(f.basis_qty)} ${f.unit}`;
    return;
  }
  const k = qty / f.basis_qty;
  $("#entry-preview").textContent =
    `≈ ${fmt(f.kcal * k)} kcal · ` + MACROS.map((m) => `${m.short} ${fmt(f[m.key] * k, 1)}`).join(" · ");
}

function selectFood(food) {
  state.selectedFood = food;
  $("#food-search").value = food.brand ? `${food.name} (${food.brand})` : food.name;
  $("#entry-qty").value = food.serving_qty ?? food.basis_qty;
  updatePreview();
  $("#entry-qty").focus();
  $("#entry-qty").select();
}

/** From the Day search: open Foods with the name or barcode filled in. */
function createFoodFrom(q) {
  location.hash = "#/foods";
  resetFoodForm();
  const el = $("#food-form").elements;
  if (isBarcode(q)) {
    el.ean.value = q.replace(/[\s-]/g, "");
    lookupBarcode();
  } else {
    el.name.value = q;
    el.basis_qty.focus();
  }
}

async function submitEntry(ev) {
  ev.preventDefault();
  const form = ev.currentTarget;
  const v = formValues(form);
  let body = { day: state.day, meal: v.meal };
  const mode = entryMode();
  if (mode === "saved") return commitDraft();
  if (mode === "catalog") {
    if (!state.selectedFood) {
      toast("Pick a food from the list first", true);
      $("#food-search").focus();
      return;
    }
    const qty = num(v.quantity);
    if (!qty || qty <= 0) {
      toast("Enter an amount", true);
      $("#entry-qty").focus();
      return;
    }
    body = { ...body, food_id: state.selectedFood.id, quantity: qty };
  } else {
    if (!v.name.trim()) {
      toast("Give the entry a name", true);
      $("#quick-name").focus();
      return;
    }
    body = { ...body, name: v.name.trim(), kcal: num(v.kcal) ?? 0 };
    for (const m of MACROS) body[m.key] = num(v[m.key]) ?? 0;
  }
  try {
    await api("POST", "/entries", body);
    if (mode === "catalog") {
      state.selectedFood = null;
      $("#food-search").value = "";
      $("#entry-qty").value = "";
      updatePreview();
      $("#food-search").focus();
    } else {
      for (const k of ["name", "kcal", ...MACROS.map((m) => m.key)]) form.elements[k].value = "";
      $("#quick-name").focus();
    }
    await loadDay();
  } catch (err) {
    showError(err);
  }
}

function startQtyEdit(td) {
  if (td.querySelector("input")) return;
  const id = Number(td.dataset.editQty);
  const entry = state.dayData.entries.find((e) => e.id === id);
  if (!entry) return;
  td.innerHTML = `<input class="qty-input" type="number" min="0" step="any" value="${entry.quantity}" aria-label="Amount"> ${esc(entry.unit)}`;
  const input = td.querySelector("input");
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const qty = num(input.value);
    if (save && qty && qty > 0 && qty !== entry.quantity) {
      try {
        await api("PUT", `/entries/${id}`, { day: entry.day, meal: entry.meal, food_id: entry.food_id, quantity: qty, name: entry.name });
      } catch (err) {
        showError(err);
      }
    }
    loadDay();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

// saved meal draft -------------------------------------------------------------------

let draftTable;

function fillSavedPick() {
  const sel = $("#saved-pick");
  const prev = sel.value;
  sel.innerHTML =
    `<option value="">${state.savedMeals.length ? "Choose a saved meal…" : "No saved meals yet"}</option>` +
    state.savedMeals
      .map((sm) => `<option value="${sm.id}">${esc(sm.name)} · ${fmt(sm.totals.kcal)} kcal${sm.default_meal ? ` · ${esc(sm.default_meal)}` : ""}</option>`)
      .join("");
  sel.value = state.savedMeals.some((sm) => String(sm.id) === prev) ? prev : "";
  $("#saved-hint").innerHTML = state.savedMeals.length
    ? "Picking one fills in a draft below. Nothing is logged until you press <b>Log</b>."
    : 'Create one in <a href="#/meals">Saved meals</a>, or press <b>☆ save</b> on a meal in the log below.';
}

function startDraft(sm) {
  state.draft = { name: sm.name, items: sm.items.map(itemFromSaved) };
  if (sm.default_meal && state.config.meals.names.includes(sm.default_meal)) $("#entry-meal").value = sm.default_meal;
  renderDraft();
  $("#draft-commit").focus();
}

function renderDraft() {
  const d = state.draft;
  $("#draft").hidden = !d;
  if (!d) return;
  $("#draft-h").textContent = `Draft: ${d.name}`;
  draftTable.render();
  updateDraftCommit();
}

function updateDraftCommit() {
  if (!state.draft) return;
  const n = state.draft.items.length;
  const btn = $("#draft-commit");
  btn.textContent = `Log ${n} ${n === 1 ? "food" : "foods"} to ${$("#entry-meal").value} · ${fmtDay(state.day)}`;
  btn.disabled = !n;
}

function discardDraft() {
  state.draft = null;
  $("#saved-pick").value = "";
  renderDraft();
}

async function commitDraft() {
  const d = state.draft;
  if (!d) {
    toast("Pick a saved meal first", true);
    $("#saved-pick").focus();
    return;
  }
  const bad = d.items.findIndex((it) => !(it.quantity > 0));
  if (bad >= 0) {
    toast(`Enter an amount for ${d.items[bad].name}`, true);
    $(`#draft-body [data-qty-i="${bad}"]`)?.focus();
    return;
  }
  const meal = $("#entry-meal").value;
  try {
    await api("POST", "/entries/batch", {
      day: state.day,
      meal,
      items: d.items.map((it) => ({ food_id: it.food_id, quantity: it.quantity })),
    });
    toast(`Logged “${d.name}” to ${meal}`);
    discardDraft();
    await loadDay();
  } catch (err) {
    showError(err);
  }
}

// activity form ---------------------------------------------------------------

function fillActivitySelect() {
  const sel = $("#act-type");
  const prev = sel.value;
  const types = state.activityTypes;
  const recent = types.filter((t) => t.uses > 0).sort((a, b) => b.uses - a.uses).slice(0, 5);
  const opt = (t) => `<option value="${esc(t.name)}">${esc(t.name)}</option>`;
  const groups = new Map();
  for (const t of types) {
    if (!groups.has(t.category)) groups.set(t.category, []);
    groups.get(t.category).push(t);
  }
  let html = recent.length ? `<optgroup label="Recently used">${recent.map(opt).join("")}</optgroup>` : "";
  for (const [cat, list] of groups) html += `<optgroup label="${esc(cat)}">${list.map(opt).join("")}</optgroup>`;
  sel.innerHTML = html;
  if (types.some((t) => t.name === prev)) sel.value = prev;
  updateActivityForm();
}

function currentActivityType() {
  const name = $("#act-type").value;
  return state.activityTypes.find((t) => t.name === name);
}

function updateActivityForm() {
  if (!state.config) return;
  const t = currentActivityType();
  $("#act-distance").hidden = !(t && t.distance);
  const mins = num($("#activity-form").elements.duration_min.value);
  const kcal = $("#act-kcal");
  if (t && mins) kcal.placeholder = `≈ ${fmt((t.met * state.config.profile.weight_kg * mins) / 60)}`;
  else kcal.placeholder = "auto";
}

async function submitActivity(ev) {
  ev.preventDefault();
  const form = ev.currentTarget;
  const v = formValues(form);
  const t = currentActivityType();
  const body = {
    day: state.day,
    type: v.type,
    duration_min: num(v.duration_min),
    distance_km: t && t.distance ? num(v.distance_km) : null,
    kcal: num(v.kcal),
    notes: (v.notes || "").trim(),
  };
  try {
    await api("POST", "/activities", body);
    for (const k of ["duration_min", "distance_km", "kcal", "notes"]) form.elements[k].value = "";
    updateActivityForm();
    await loadDay();
    loadActivityTypes().catch(showError); // refresh "Recently used"
  } catch (err) {
    showError(err);
  }
}

// --- foods view --------------------------------------------------------------

const FOOD_FIELDS = ["name", "brand", "ean", "basis_qty", "unit", "kcal", ...MACROS.map((m) => m.key), "serving_qty", "package_qty"];

async function loadFoods() {
  document.title = "Foods · Pamela";
  try {
    state.foods = await api("GET", "/foods?limit=1000");
    renderFoods();
  } catch (err) {
    showError(err);
  }
}

function renderFoods() {
  const words = $("#foods-filter").value.toLowerCase().split(/\s+/).filter(Boolean);
  const tags = [...state.foodTagFilter];
  const rows = state.foods.filter((f) => {
    const hay = `${f.name} ${f.brand} ${f.ean ?? ""}`.toLowerCase();
    return words.every((w) => hay.includes(w)) && tags.every((t) => f[t]);
  });
  $("#foods-count").textContent = rows.length === state.foods.length ? `(${rows.length})` : `(${rows.length} of ${state.foods.length})`;
  $("#foods-body").innerHTML = rows.length
    ? rows
        .map(
          (f) => `<tr class="${f.id === state.editingFoodId ? "editing" : ""}">
      <td>${esc(f.name)}${tagPills(f)}</td>
      <td>${esc(f.brand)}${f.ean ? `<span class="ean" title="Barcode">${esc(f.ean)}</span>` : ""}</td>
      <td class="n">${fmtQty(f.basis_qty)} ${esc(f.unit)}</td>
      ${macroCells(f)}
      <td class="n">${f.uses}</td>
      <td class="act"><button type="button" class="row-btn" data-edit-food="${f.id}">Edit</button><button type="button" class="row-btn del" data-del-food="${f.id}" aria-label="Delete ${esc(f.name)}">✕</button></td>
    </tr>`
        )
        .join("")
    : `<tr class="empty"><td colspan="10">${state.foods.length ? "No matches" : "No foods yet - add your first one with the form."}</td></tr>`;
}

function setEanStatus(html, kind = "") {
  const el = $("#ean-status");
  el.innerHTML = html;
  el.className = `hint span2 ean-status ${kind}`;
}

function updateFormUnit() {
  const unit = $("#food-form").elements.unit.value.trim() || "g";
  for (const el of $$(".form-unit")) el.textContent = unit;
}

function resetFoodForm() {
  const form = $("#food-form");
  form.reset();
  state.editingFoodId = null;
  $("#food-form-h").textContent = "New food";
  $("#food-submit").textContent = "Save food";
  $("#food-cancel").hidden = true;
  setEanStatus("");
  updateKcalHint();
  updateFormUnit();
  renderFoods();
}

/** Puts a food (or a barcode lookup draft) into the form. */
function fillFoodForm(f) {
  const el = $("#food-form").elements;
  for (const k of FOOD_FIELDS) el[k].value = f[k] ?? "";
  for (const t of state.vocab.diet_tags) el[t.key].checked = !!f[t.key];
  updateKcalHint();
  updateFormUnit();
}

function editFood(id) {
  const f = state.foods.find((x) => x.id === id);
  if (!f) return;
  state.editingFoodId = id;
  fillFoodForm(f);
  $("#food-form-h").textContent = "Edit food";
  $("#food-submit").textContent = "Update food";
  $("#food-cancel").hidden = false;
  setEanStatus("");
  renderFoods();
  $("#food-form").elements.name.focus();
}

/** Compares entered kcal with 4/4/9 kcal per gram of protein/carbs/fat. */
function updateKcalHint() {
  const el = $("#food-form").elements;
  const p = num(el.protein_g.value) ?? 0, c = num(el.carbs_g.value) ?? 0, f = num(el.fat_g.value) ?? 0;
  const est = p * 4 + c * 4 + f * 9;
  $("#food-kcal-hint").textContent = est ? `Macros add up to ≈ ${fmt(est)} kcal` : "";
}

async function lookupBarcode() {
  const input = $("#food-form").elements.ean;
  const raw = input.value.trim();
  if (!raw) {
    setEanStatus("Type or scan a barcode first.", "error");
    input.focus();
    return;
  }
  setEanStatus("Looking up…");
  try {
    const r = await api("GET", `/barcode/${encodeURIComponent(raw)}`);
    input.value = r.ean;
    if (r.source === "catalog") {
      if (state.editingFoodId === r.food.id) return setEanStatus("That's the food you're editing.");
      if (!state.foods.some((f) => f.id === r.food.id)) state.foods.push(r.food);
      editFood(r.food.id);
      setEanStatus(`Already in your catalog: <b>${esc(r.food.name)}</b>. Opened it for editing.`, "ok");
    } else if (r.source === "openfoodfacts") {
      if (state.editingFoodId && !confirm("Replace the values in the form with the ones from Open Food Facts?")) {
        return setEanStatus("Kept your values.");
      }
      const keepName = $("#food-form").elements.name.value.trim();
      fillFoodForm({ ...r.draft, name: r.draft.name || keepName });
      const link = `https://world.openfoodfacts.org/product/${encodeURIComponent(r.ean)}`;
      setEanStatus(
        `Found on <a href="${link}" target="_blank" rel="noopener">Open Food Facts</a>. Check the values against the label (they can be incomplete), then save.`,
        "ok"
      );
      $("#food-form").elements.name.focus();
    } else {
      setEanStatus("Not on Open Food Facts. Enter the values from the label: the food is saved with this barcode, so typing or scanning it later finds it.");
      $("#food-form").elements.name.focus();
    }
  } catch (err) {
    if (err.status === 502) setEanStatus(`${esc(err.message)}. You can still enter the values by hand.`, "error");
    else setEanStatus(esc(err.message), "error");
  }
}

async function submitFood(ev) {
  ev.preventDefault();
  const form = ev.currentTarget;
  const v = formValues(form);
  const body = {
    name: v.name.trim(),
    brand: v.brand.trim(),
    ean: v.ean.trim() || null,
    basis_qty: num(v.basis_qty),
    unit: v.unit.trim(),
    kcal: num(v.kcal) ?? 0,
    serving_qty: num(v.serving_qty) || null,
    package_qty: num(v.package_qty) || null,
  };
  for (const m of MACROS) body[m.key] = num(v[m.key]) ?? 0;
  for (const t of state.vocab.diet_tags) body[t.key] = form.elements[t.key].checked;
  try {
    if (state.editingFoodId) {
      await api("PUT", `/foods/${state.editingFoodId}`, body);
      toast("Food updated");
    } else {
      await api("POST", "/foods", body);
      toast("Food added");
    }
    resetFoodForm();
    await loadFoods();
    form.elements.ean.focus();
  } catch (err) {
    showError(err);
  }
}

async function deleteFood(id) {
  const f = state.foods.find((x) => x.id === id);
  if (!f || !confirm(`Delete “${f.name}”? Past log entries keep their values. It's also removed from saved meals.`)) return;
  try {
    await api("DELETE", `/foods/${id}`);
    if (state.editingFoodId === id) resetFoodForm();
    await loadFoods();
    loadSavedMeals().catch(showError);
  } catch (err) {
    showError(err);
  }
}

// --- saved meals view ------------------------------------------------------------

let smTable;

async function loadMealsView() {
  document.title = "Saved meals · Pamela";
  try {
    await loadSavedMeals();
    renderSavedMeals();
    smTable.render();
  } catch (err) {
    showError(err);
  }
}

function renderSavedMeals() {
  const list = state.savedMeals;
  $("#sm-count").textContent = `(${list.length})`;
  if (!list.length) {
    $("#sm-list").innerHTML = `<p class="empty-note">No saved meals yet. Add foods with the form, or press <b>☆ save</b> on a meal in the Day tab.</p>`;
    return;
  }
  $("#sm-list").innerHTML = list
    .map((sm) => {
      const t = sm.totals;
      return `<article class="sm-card${sm.id === state.editingSavedMealId ? " editing" : ""}">
        <div class="sm-top">
          <h3>${esc(sm.name)}</h3>
          ${sm.default_meal ? `<span class="sm-for">${esc(sm.default_meal)}</span>` : ""}
        </div>
        ${tagPills(sm.tags)}
        <ul class="sm-foods">${sm.items.map((it) => `<li><span>${esc(it.name)}</span><span class="n">${fmtQty(it.quantity)} ${esc(it.unit)}</span></li>`).join("")}</ul>
        <div class="sm-tot"><b>${fmt(t.kcal)}</b> kcal · ${MACROS.map((m) => `${m.short} ${fmt(t[m.key])}`).join(" · ")}</div>
        <div class="sm-actions">
          <button type="button" class="btn" data-use-sm="${sm.id}" title="Open today with this meal as a draft">Use today</button>
          <button type="button" class="row-btn" data-edit-sm="${sm.id}">Edit</button>
          <button type="button" class="row-btn del" data-del-sm="${sm.id}" aria-label="Delete ${esc(sm.name)}">✕</button>
        </div>
      </article>`;
    })
    .join("");
}

function resetSmForm() {
  $("#sm-form").reset();
  state.smItems = [];
  state.editingSavedMealId = null;
  $("#sm-form-h").textContent = "New saved meal";
  $("#sm-submit").textContent = "Save meal";
  $("#sm-cancel").hidden = true;
  smTable.render();
  renderSavedMeals();
}

function editSavedMeal(id) {
  const sm = state.savedMeals.find((x) => x.id === id);
  if (!sm) return;
  state.editingSavedMealId = id;
  state.smItems = sm.items.map(itemFromSaved);
  const el = $("#sm-form").elements;
  el.name.value = sm.name;
  el.default_meal.value = state.config.meals.names.includes(sm.default_meal) ? sm.default_meal : "";
  $("#sm-form-h").textContent = "Edit saved meal";
  $("#sm-submit").textContent = "Update meal";
  $("#sm-cancel").hidden = false;
  smTable.render();
  renderSavedMeals();
  el.name.focus();
}

async function submitSavedMeal(ev) {
  ev.preventDefault();
  const v = formValues(ev.currentTarget);
  if (!state.smItems.length) {
    toast("Add at least one food", true);
    $("#sm-search").focus();
    return;
  }
  const bad = state.smItems.findIndex((it) => !(it.quantity > 0));
  if (bad >= 0) {
    toast(`Enter an amount for ${state.smItems[bad].name}`, true);
    return;
  }
  const body = {
    name: v.name.trim(),
    default_meal: v.default_meal,
    items: state.smItems.map((it) => ({ food_id: it.food_id, quantity: it.quantity })),
  };
  try {
    if (state.editingSavedMealId) {
      await api("PUT", `/saved-meals/${state.editingSavedMealId}`, body);
      toast("Saved meal updated");
    } else {
      await api("POST", "/saved-meals", body);
      toast("Saved meal added");
    }
    await loadSavedMeals();
    resetSmForm();
  } catch (err) {
    showError(err);
  }
}

async function deleteSavedMeal(id) {
  const sm = state.savedMeals.find((x) => x.id === id);
  if (!sm || !confirm(`Delete the saved meal “${sm.name}”? Days you already logged with it don't change.`)) return;
  try {
    await api("DELETE", `/saved-meals/${id}`);
    if (state.editingSavedMealId === id) resetSmForm();
    await loadSavedMeals();
    renderSavedMeals();
  } catch (err) {
    showError(err);
  }
}

function useSavedMealToday(id) {
  const sm = state.savedMeals.find((x) => x.id === id);
  if (!sm) return;
  setEntryMode("saved");
  $("#saved-pick").value = String(id);
  goDay(todayISO());
  startDraft(sm);
}

// --- settings view (exercise types) ------------------------------------------------

async function loadSettings() {
  document.title = "Settings · Pamela";
  try {
    await loadActivityTypes();
    renderTypes();
  } catch (err) {
    showError(err);
  }
}

function renderTypes() {
  const words = $("#at-filter").value.toLowerCase().split(/\s+/).filter(Boolean);
  const all = state.activityTypes;
  const rows = all.filter((t) => words.every((w) => `${t.name} ${t.category}`.toLowerCase().includes(w)));
  $("#at-count").textContent = rows.length === all.length ? `(${all.length})` : `(${rows.length} of ${all.length})`;
  $("#at-categories").innerHTML = [...new Set(all.map((t) => t.category))].map((c) => `<option value="${esc(c)}">`).join("");
  const w = state.config.profile.weight_kg;
  let html = "", cat = null;
  for (const t of rows) {
    if (t.category !== cat) {
      cat = t.category;
      html += `<tr class="group-head"><td colspan="6">${esc(cat)}</td></tr>`;
    }
    html += `<tr class="${t.id === state.editingTypeId ? "editing" : ""}">
      <td>${esc(t.name)}</td><td class="n">${fmtQty(t.met)}</td><td class="n">${fmt(t.met * w)}</td>
      <td>${t.distance ? "yes" : ""}</td><td class="n">${t.uses || ""}</td>
      <td class="act"><button type="button" class="row-btn" data-edit-type="${t.id}">Edit</button><button type="button" class="row-btn del" data-del-type="${t.id}" aria-label="Delete ${esc(t.name)}">✕</button></td>
    </tr>`;
  }
  $("#at-body").innerHTML = html || `<tr class="empty"><td colspan="6">No matches</td></tr>`;
}

function updateTypeHint() {
  const met = num($("#at-form").elements.met.value);
  $("#at-hint").textContent = met ? `≈ ${fmt(met * state.config.profile.weight_kg)} kcal per hour at your weight (${fmtQty(state.config.profile.weight_kg)} kg)` : "";
}

function resetTypeForm() {
  $("#at-form").reset();
  state.editingTypeId = null;
  $("#at-form-h").textContent = "New exercise type";
  $("#at-submit").textContent = "Add type";
  $("#at-cancel").hidden = true;
  updateTypeHint();
  renderTypes();
}

function editType(id) {
  const t = state.activityTypes.find((x) => x.id === id);
  if (!t) return;
  state.editingTypeId = id;
  const el = $("#at-form").elements;
  el.name.value = t.name;
  el.category.value = t.category;
  el.met.value = t.met;
  el.distance.checked = t.distance;
  $("#at-form-h").textContent = "Edit exercise type";
  $("#at-submit").textContent = "Update type";
  $("#at-cancel").hidden = false;
  updateTypeHint();
  renderTypes();
  el.name.focus();
}

async function submitType(ev) {
  ev.preventDefault();
  const form = ev.currentTarget;
  const v = formValues(form);
  const body = { name: v.name.trim(), category: v.category.trim(), met: num(v.met), distance: form.elements.distance.checked };
  try {
    if (state.editingTypeId) {
      await api("PUT", `/activity-types/${state.editingTypeId}`, body);
      toast("Type updated");
    } else {
      await api("POST", "/activity-types", body);
      toast("Type added");
    }
    await loadActivityTypes();
    resetTypeForm();
  } catch (err) {
    showError(err);
  }
}

async function deleteType(id) {
  const t = state.activityTypes.find((x) => x.id === id);
  if (!t || !confirm(`Delete “${t.name}”? Activities already logged with it keep their name and kcal.`)) return;
  try {
    await api("DELETE", `/activity-types/${id}`);
    if (state.editingTypeId === id) resetTypeForm();
    await loadActivityTypes();
    renderTypes();
  } catch (err) {
    showError(err);
  }
}

// --- history view ------------------------------------------------------------

async function loadHistory() {
  document.title = "History · Pamela";
  const end = todayISO();
  const start = addDays(end, -(state.historyRange - 1));
  try {
    const days = await api("GET", `/history?start=${start}&end=${end}`);
    for (const d of days) d.sleep_h = d.sleep_min != null ? d.sleep_min / 60 : null;
    renderHistory(days);
  } catch (err) {
    showError(err);
  }
}

function moodLabel(mood) {
  return state.vocab.moods.find((m) => Number(m.key) === mood)?.label ?? "";
}

function renderHistory(days) {
  const logged = days.filter((d) => d.entry_count > 0);
  const avg = (key, list = logged) => (list.length ? list.reduce((s, d) => s + d[key], 0) / list.length : null);
  const withKey = (key) => days.filter((d) => d[key] != null);
  const t = state.config.targets;
  const activeDays = days.filter((d) => d.active_min > 0).length;
  const sleepAvg = avg("sleep_min", withKey("sleep_min"));
  const moodAvg = avg("mood", withKey("mood"));
  $("#history-tiles").innerHTML = [
    ["Avg kcal / logged day", fmt(avg("kcal")), t.kcal ? `target ${fmt(t.kcal)}` : ""],
    ["Avg protein", `${fmt(avg("protein_g"))} g`, t.protein_g ? `target ${fmt(t.protein_g)} g` : ""],
    ["Days logged", `${logged.length}`, `of ${days.length}`],
    ["Active days", `${activeDays}`, `of ${days.length}`],
    ["Avg burned / day", fmt(avg("burned_kcal", days)), "kcal"],
    ["Avg steps", fmt(avg("steps", withKey("steps"))), t.steps ? `target ${fmt(t.steps)}` : ""],
    ["Avg sleep", sleepAvg != null ? fmtSleep(sleepAvg) : "–", t.sleep_h ? `target ${fmtSleep(t.sleep_h * 60)} h` : "h"],
    ["Avg mood", moodAvg != null ? `${MOOD_EMOJI[Math.round(moodAvg)]}` : "–", moodAvg != null ? `${moodLabel(Math.round(moodAvg))} · ${fmt(moodAvg, 1)} / 5` : ""],
  ]
    .map(([k, v, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v} <small>${s}</small></div></div>`)
    .join("");

  barChart($("#chart-kcal"), days, "kcal", t.kcal, "kcal");
  barChart($("#chart-protein"), days, "protein_g", t.protein_g, "g");
  barChart($("#chart-steps"), days, "steps", t.steps, "steps");
  barChart($("#chart-sleep"), days, "sleep_h", t.sleep_h, "h", 1);

  $("#history-body").innerHTML = [...days]
    .reverse()
    .map(
      (d) => `<tr class="${d.entry_count || d.active_min || d.steps != null || d.sleep_min != null || d.mood != null ? "" : "nodata"}">
      <td><a href="#/day/${d.day}">${fmtDay(d.day)}</a></td>
      <td class="n">${fmt(d.kcal)}</td>
      ${MACROS.map((m) => `<td class="n">${fmt(d[m.key])}</td>`).join("")}
      <td class="n">${fmt(d.burned_kcal)}</td><td class="n">${fmt(d.active_min)}</td>
      <td class="n">${fmt(d.steps)}</td><td class="n">${fmtSleep(d.sleep_min)}</td>
      <td>${d.mood != null ? `<span title="${esc(moodLabel(d.mood))}">${MOOD_EMOJI[d.mood]} ${esc(moodLabel(d.mood))}</span>` : ""}</td>
    </tr>`
    )
    .join("");
}

const SVG_NS = "http://www.w3.org/2000/svg";
const chartData = new WeakMap();

/** Single-series bar chart with a dashed target line and per-bar hover tooltip. */
function barChart(el, days, key, target, unit, digits = 0) {
  chartData.set(el, { days, key, target, unit, digits });
  drawChart(el);
}

function niceMax(v) {
  if (v <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * pow >= v) return m * pow;
  return 10 * pow;
}

function drawChart(el) {
  const spec = chartData.get(el);
  if (!spec) return;
  const { days, key, target, unit, digits } = spec;
  const W = el.clientWidth, H = el.clientHeight;
  if (!W || !H) return;
  const m = { top: 14, right: 8, bottom: 22, left: 44 };
  const iw = W - m.left - m.right, ih = H - m.top - m.bottom;
  const maxV = niceMax(Math.max(target || 0, ...days.map((d) => d[key] ?? 0)) * 1.05);
  const y = (v) => m.top + ih - (v / maxV) * ih;
  const band = iw / days.length;
  const gap = Math.min(2, band * 0.25);
  const bw = Math.max(1, band - gap);

  let s = `<g class="grid axis">`;
  for (let i = 0; i <= 4; i++) {
    const v = (maxV / 4) * i;
    s += `<line x1="${m.left}" x2="${W - m.right}" y1="${y(v)}" y2="${y(v)}"/>`;
    s += `<text x="${m.left - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v, digits)}</text>`;
  }
  s += `</g><g class="axis">`;
  const every = Math.ceil(days.length / Math.max(1, Math.floor(iw / 64)));
  days.forEach((d, i) => {
    if ((days.length - 1 - i) % every) return;
    const dd = parseISO(d.day);
    s += `<text x="${m.left + i * band + band / 2}" y="${H - 6}" text-anchor="middle">${dd.getDate()}/${dd.getMonth() + 1}</text>`;
  });
  s += `</g><g>`;
  days.forEach((d, i) => {
    const v = d[key];
    if (!v) return;
    const x = m.left + i * band + gap / 2, top = y(v), h = m.top + ih - top;
    const r = Math.min(4, bw / 2, h);
    // rounded data-end, square baseline
    s += `<path class="bar" data-i="${i}" d="M${x},${m.top + ih}V${top + r}Q${x},${top} ${x + r},${top}H${x + bw - r}Q${x + bw},${top} ${x + bw},${top + r}V${m.top + ih}Z"/>`;
  });
  s += `</g>`;
  if (target) {
    s += `<line class="target" x1="${m.left}" x2="${W - m.right}" y1="${y(target)}" y2="${y(target)}"/>`;
    s += `<text class="target-lbl" x="${W - m.right}" y="${y(target) - 5}" text-anchor="end">target ${fmt(target, digits)}</text>`;
  }
  if (!days.some((d) => d[key])) {
    s += `<text class="empty-msg" x="${m.left + iw / 2}" y="${m.top + ih / 2}" text-anchor="middle">No data in this range</text>`;
  }
  // full-height hit targets, wider than the bars
  days.forEach((d, i) => {
    s += `<rect class="hit" data-i="${i}" x="${m.left + i * band}" y="${m.top}" width="${band}" height="${ih}"/>`;
  });

  el.innerHTML = `<svg xmlns="${SVG_NS}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(key)} per day">${s}</svg>`;

  const svg = el.firstChild;
  const tip = $("#tooltip");
  svg.addEventListener("mousemove", (e) => {
    const hit = e.target.closest(".hit");
    $$(".bar.hot", svg).forEach((b) => b.classList.remove("hot"));
    if (!hit) return (tip.hidden = true);
    const i = Number(hit.dataset.i);
    const d = days[i];
    $(`.bar[data-i="${i}"]`, svg)?.classList.add("hot");
    const v = d[key];
    tip.innerHTML = `<b>${fmtDay(d.day)}</b>${fmt(v, digits)} ${unit}${target && v != null ? ` · ${fmt((v / target) * 100)}% of target` : ""}`;
    tip.hidden = false;
    const tw = tip.offsetWidth;
    tip.style.left = `${Math.min(e.clientX + 12, window.innerWidth - tw - 8)}px`;
    tip.style.top = `${e.clientY + 14}px`;
  });
  svg.addEventListener("mouseleave", () => {
    tip.hidden = true;
    $$(".bar.hot", svg).forEach((b) => b.classList.remove("hot"));
  });
  svg.addEventListener("click", (e) => {
    const hit = e.target.closest(".hit");
    if (hit) {
      tip.hidden = true;
      goDay(days[Number(hit.dataset.i)].day);
    }
  });
}

// --- help view ---------------------------------------------------------------

function renderHelp() {
  document.title = "Help · Pamela";
  const { profile, targets, meals } = state.config;
  const rows = [
    ["kcal", "kcal", (v) => fmt(v)],
    ...MACROS.map((m) => [m.key, m.label, (v) => `${fmt(v)} g`]),
    ["steps", "Steps", (v) => fmt(v)],
    ["sleep_h", "Sleep", (v) => `${fmtSleep(v * 60)} h`],
  ];
  const tgt = rows.map(([k, label, f]) => `<tr><td>${label}</td><td class="n">${targets[k] ? f(targets[k]) : "—"}</td></tr>`).join("");
  $("#help-settings").innerHTML = `
    <dl class="help-dl">
      <dt>Body weight</dt><dd>${fmtQty(profile.weight_kg)} kg</dd>
      <dt>Meals</dt><dd>${meals.names.map(esc).join(", ")}</dd>
      <dt>Exercise types</dt><dd>${state.activityTypes.length}, in <a href="#/settings">Settings</a></dd>
    </dl>
    <h3>Daily targets</h3>
    <table class="help-table"><tbody>${tgt}</tbody></table>`;
}

// --- wiring ------------------------------------------------------------------

function wire() {
  window.addEventListener("hashchange", route);

  // top bar
  $("#prev-day").addEventListener("click", () => goDay(addDays(state.day, -1)));
  $("#next-day").addEventListener("click", () => goDay(addDays(state.day, 1)));
  $("#today-btn").addEventListener("click", () => goDay(todayISO()));
  $("#day-input").addEventListener("change", (e) => e.target.value && goDay(e.target.value));
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target.closest("input, select, textarea")) return;
    if (e.key === "?") location.hash = "#/help";
    if (state.view !== "day") return;
    if (e.key === "[") goDay(addDays(state.day, -1));
    if (e.key === "]") goDay(addDays(state.day, 1));
  });

  // entry form
  for (const r of $$('input[name="entry-mode"]')) r.addEventListener("change", () => setEntryMode(entryMode()));
  $("#entry-form").addEventListener("submit", submitEntry);
  $("#entry-qty").addEventListener("input", updatePreview);
  $("#entry-meal").addEventListener("change", updateDraftCommit);
  foodCombo({
    input: $("#food-search"),
    list: $("#food-suggest"),
    onPick: selectFood,
    onCreate: createFoodFrom,
    onInput: () => {
      state.selectedFood = null;
      updatePreview();
    },
    canSubmit: () => !!state.selectedFood,
  });
  $("#portion-chips").addEventListener("click", (e) => {
    const chip = e.target.closest("[data-portion]");
    if (!chip) return;
    $("#entry-qty").value = Math.round(Number(chip.dataset.portion) * 100) / 100;
    updatePreview();
    $("#entry-qty").focus();
  });

  // saved meal draft
  draftTable = itemsTable({
    tbody: $("#draft-body"),
    tfoot: $("#draft-foot"),
    getItems: () => state.draft?.items ?? [],
    fiber: true,
    empty: "No foods left in this draft. Add one below, or discard it.",
    onChange: updateDraftCommit,
  });
  $("#saved-pick").addEventListener("change", (e) => {
    const sm = state.savedMeals.find((x) => String(x.id) === e.target.value);
    if (sm) startDraft(sm);
  });
  foodCombo({
    input: $("#draft-search"),
    list: $("#draft-suggest"),
    onPick: (f) => {
      state.draft.items.push(itemFromFood(f));
      $("#draft-search").value = "";
      draftTable.render();
      updateDraftCommit();
      $(`#draft-body [data-qty-i="${state.draft.items.length - 1}"]`)?.select();
    },
  });
  $("#draft-discard").addEventListener("click", discardDraft);
  $("#draft-commit").addEventListener("click", commitDraft);

  // check-in
  $("#steps-input").addEventListener("change", commitSteps);
  $("#sleep-input").addEventListener("change", commitSleep);
  for (const id of ["#steps-input", "#sleep-input"]) {
    $(id).addEventListener("keydown", (e) => e.key === "Enter" && e.target.blur());
  }
  $("#mood-scale").addEventListener("click", (e) => {
    const b = e.target.closest("[data-mood]");
    if (!b) return;
    const mood = Number(b.dataset.mood);
    saveCheckin({ mood: state.dayData.metrics.mood === mood ? null : mood }); // click again to clear
  });
  $("#feelings").addEventListener("click", (e) => {
    const b = e.target.closest("[data-feeling]");
    if (!b) return;
    const cur = new Set(state.dayData.metrics.feelings);
    if (cur.has(b.dataset.feeling)) cur.delete(b.dataset.feeling);
    else cur.add(b.dataset.feeling);
    saveCheckin({ feelings: [...cur] });
  });

  // log table
  $("#log-body").addEventListener("click", async (e) => {
    const add = e.target.closest("[data-add-meal]");
    if (add) {
      $("#entry-meal").value = add.dataset.addMeal;
      updateDraftCommit();
      const mode = entryMode();
      (mode === "catalog" ? $("#food-search") : mode === "quick" ? $("#quick-name") : $("#saved-pick")).focus();
      return;
    }
    const save = e.target.closest("[data-save-meal]");
    if (save) return saveMealAsSaved(save.dataset.saveMeal);
    const del = e.target.closest("[data-del-entry]");
    if (del) {
      try {
        await api("DELETE", `/entries/${del.dataset.delEntry}`);
        await loadDay();
      } catch (err) {
        showError(err);
      }
      return;
    }
    const qty = e.target.closest("[data-edit-qty]");
    if (qty) startQtyEdit(qty);
  });

  // activity
  $("#activity-form").addEventListener("submit", submitActivity);
  $("#act-type").addEventListener("change", updateActivityForm);
  $("#activity-form").elements.duration_min.addEventListener("input", updateActivityForm);
  $("#act-list").addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del-activity]");
    if (!del) return;
    try {
      await api("DELETE", `/activities/${del.dataset.delActivity}`);
      await loadDay();
    } catch (err) {
      showError(err);
    }
  });

  // foods
  const foodForm = $("#food-form");
  foodForm.addEventListener("submit", submitFood);
  foodForm.addEventListener("input", (e) => {
    updateKcalHint();
    if (e.target.name === "unit") updateFormUnit();
  });
  foodForm.addEventListener("change", (e) => {
    // vegan implies vegetarian
    if (e.target.name === "vegan" && e.target.checked) foodForm.elements.vegetarian.checked = true;
  });
  $("#ean-lookup").addEventListener("click", lookupBarcode);
  foodForm.elements.ean.addEventListener("keydown", (e) => {
    // barcode scanners type the digits and press Enter
    if (e.key === "Enter") {
      e.preventDefault();
      lookupBarcode();
    }
  });
  $("#food-cancel").addEventListener("click", resetFoodForm);
  $("#foods-filter").addEventListener("input", renderFoods);
  $("#tag-filter").addEventListener("click", (e) => {
    const chip = e.target.closest("[data-tag]");
    if (!chip) return;
    const on = !state.foodTagFilter.has(chip.dataset.tag);
    if (on) state.foodTagFilter.add(chip.dataset.tag);
    else state.foodTagFilter.delete(chip.dataset.tag);
    chip.setAttribute("aria-pressed", String(on));
    renderFoods();
  });
  $("#foods-body").addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit-food]");
    if (edit) return editFood(Number(edit.dataset.editFood));
    const del = e.target.closest("[data-del-food]");
    if (del) deleteFood(Number(del.dataset.delFood));
  });

  // saved meals
  smTable = itemsTable({
    tbody: $("#sm-body"),
    tfoot: $("#sm-foot"),
    getItems: () => state.smItems,
    fiber: false,
    empty: "Add foods from your catalog with the search below.",
  });
  foodCombo({
    input: $("#sm-search"),
    list: $("#sm-suggest"),
    onPick: (f) => {
      state.smItems.push(itemFromFood(f));
      $("#sm-search").value = "";
      smTable.render();
      $(`#sm-body [data-qty-i="${state.smItems.length - 1}"]`)?.select();
    },
  });
  $("#sm-form").addEventListener("submit", submitSavedMeal);
  $("#sm-cancel").addEventListener("click", resetSmForm);
  $("#sm-list").addEventListener("click", (e) => {
    const use = e.target.closest("[data-use-sm]");
    if (use) return useSavedMealToday(Number(use.dataset.useSm));
    const edit = e.target.closest("[data-edit-sm]");
    if (edit) return editSavedMeal(Number(edit.dataset.editSm));
    const del = e.target.closest("[data-del-sm]");
    if (del) deleteSavedMeal(Number(del.dataset.delSm));
  });

  // settings
  $("#at-form").addEventListener("submit", submitType);
  $("#at-form").elements.met.addEventListener("input", updateTypeHint);
  $("#at-cancel").addEventListener("click", resetTypeForm);
  $("#at-filter").addEventListener("input", renderTypes);
  $("#at-body").addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit-type]");
    if (edit) return editType(Number(edit.dataset.editType));
    const del = e.target.closest("[data-del-type]");
    if (del) deleteType(Number(del.dataset.delType));
  });

  // history
  for (const r of $$('input[name="range"]')) {
    r.addEventListener("change", () => {
      state.historyRange = Number(r.value);
      loadHistory();
    });
  }
  const ro = new ResizeObserver((entries) => entries.forEach((en) => drawChart(en.target)));
  for (const id of ["#chart-kcal", "#chart-protein", "#chart-steps", "#chart-sleep"]) ro.observe($(id));

  // Pick up hand edits to info/config.toml when coming back to the tab.
  window.addEventListener("focus", async () => {
    const before = JSON.stringify(state.config);
    await loadConfig().catch(() => {});
    if (JSON.stringify(state.config) !== before) {
      fillConfigControls();
      render();
    }
  });
}

async function init() {
  wire();
  setEntryMode("catalog");
  try {
    await loadConfig();
  } catch {
    return; // banner already explains the problem
  }
  try {
    [state.vocab] = await Promise.all([api("GET", "/vocab"), loadActivityTypes(), loadSavedMeals()]);
  } catch (err) {
    return showError(err);
  }
  buildVocabControls();
  fillConfigControls();
  updateFormUnit();
  route();
}

init();
