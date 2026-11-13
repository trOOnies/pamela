// Pamela frontend - vanilla JS, no build step.
// Views are routed by URL hash: #/ (today), #/day/YYYY-MM-DD, #/foods, #/groceries, #/meals, #/history,
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
const FEELING_GROUP_EMOJI = { Content: "😊", Driven: "⚡", Tense: "😬", Down: "🌧️", Drained: "🪫" };
const TARGET_EMOJI = { kcal: "🔥", protein_g: "💪", carbs_g: "🍞", fat_g: "🥑", fiber_g: "🌾", steps: "👟", sleep_h: "😴" };
const PENCIL = `<svg class="ico" viewBox="0 0 20 20" width="15" height="15" aria-hidden="true"><path d="M13.3 3.3a1.9 1.9 0 0 1 2.7 0l.7.7a1.9 1.9 0 0 1 0 2.7L7.4 16 3.5 16.9l.9-3.9z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M11.8 4.8l3.4 3.4" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>`;

const state = {
  config: null,
  vocab: null,          // diet tags, moods and feelings (labels come from the backend)
  activityTypes: [],
  savedMeals: [],
  profile: null,        // { gender, height_cm, last_weight, estimate_weight_kg }
  targets: [],          // per target: { key, label, unit, max, periods: [{ start, value }] }
  targetEdit: null,     // target being edited: { key, mode: "single" | "periods", periods }
  view: "day",
  day: todayISO(),
  dayData: null,
  foods: [],            // full catalog (Foods view)
  foodTagFilter: new Set(),
  foodSort: null, // { key, dir: 1 | -1 }; null = the API's order (most used first)
  hideTags: prefGet("pamela-hide-tags") === "1",
  weightUnit: prefGet("pamela-weight-unit") === "bmi" ? "bmi" : "kg",
  bodyRefs: null, // GET /body-references
  historyDays: null,
  editingFoodId: null,
  editingActivityId: null,
  selectedFood: null,   // food chosen in the entry form
  draft: null,          // saved meal being prepared for logging: { name, items }
  smItems: [],          // items of the saved meal in the editor
  editingSavedMealId: null,
  editingTypeId: null,
  historyRange: 30,
  groceries: null,      // GET /groceries: { items, carts, expired }
  trip: [],             // food items of the cart being entered or edited in Groceries
  tripExtras: [],       // its other items (not food)
  editingCartId: null,
  cartsShown: 8,        // carts listed before "Show more"
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
// Dates are always shown as YYYY-MM-DD; weekday names follow the app's language.
const weekdayShort = new Intl.DateTimeFormat("en", { weekday: "short" });
const weekdayLong = new Intl.DateTimeFormat("en", { weekday: "long" });
function fmtDay(iso) {
  return iso;
}
/** "Tue 2026-11-10" */
function fmtDayWd(iso) {
  return `${weekdayShort.format(parseISO(iso))} ${iso}`;
}
function isISODate(s) {
  return /^\d{4}-\d{2}-\d{2}$/.test(s) && toISO(parseISO(s)) === s;
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
/** Per-browser preferences; storage can be missing or blocked, so never rely on it. */
function prefGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function prefSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // fine: the preference just isn't remembered
  }
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

// Requests still on their way; "Save & close" waits for them before stopping the server.
const inFlight = new Set();

function api(method, path, body) {
  const p = request(method, path, body);
  inFlight.add(p);
  const done = () => inFlight.delete(p);
  p.then(done, done);
  return p;
}

async function request(method, path, body) {
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

/** Every tag: the ones set by hand, then the derived ones (like Calorie-free). */
function allTags() {
  return [...state.vocab.diet_tags, ...state.vocab.auto_tags];
}

/** Colored diet tag pills for a food (booleans) or a list of tag keys. */
function tagPills(src, cls = "") {
  const keys = Array.isArray(src) ? src : allTags().map((t) => t.key).filter((k) => src[k]);
  if (!keys.length) return "";
  const label = (k) => allTags().find((t) => t.key === k)?.label ?? k;
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

async function loadTargets() {
  state.targets = await api("GET", "/targets");
}

/** The value in force on ``iso``; periods are sorted with the open-ended one first. */
function targetOn(periods, iso) {
  let v = null;
  for (const p of periods) {
    if (p.start == null || p.start <= iso) v = p.value;
    else break;
  }
  return v;
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
  const groups = state.vocab.food_groups.map((g) => `<option value="${g.key}">${g.emoji} ${esc(g.label)}</option>`).join("");
  $("#food-group").insertAdjacentHTML("beforeend", groups);
  $("#group-filter").insertAdjacentHTML("beforeend", groups);
  buildWipeList();
  $("#unit-options").innerHTML = state.vocab.units.map((u) => `<option value="${esc(u)}">`).join("");
  $("#tag-filter").innerHTML = allTags()
    .map((t) => `<button type="button" class="chip tag-chip tag-${t.key}" data-tag="${t.key}" aria-pressed="false">${esc(t.label)}</button>`)
    .join("");
}

// --- routing -----------------------------------------------------------------

const VIEWS = ["day", "foods", "groceries", "meals", "history", "settings", "help"];

function route() {
  flushNote(); // the textarea still holds the previous day's note
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  let view = parts[0] || "day";
  if (!VIEWS.includes(view)) view = "day";
  state.view = view;
  if (view === "day") {
    const d = parts[1];
    if (d && isISODate(d) && d > todayISO()) {
      toast("Days in the future can't be opened yet", true);
      return location.replace("#/");
    }
    state.day = d && isISODate(d) ? d : todayISO();
  }
  for (const v of VIEWS) $(`#view-${v}`).hidden = v !== view;
  for (const a of $$("[data-nav]")) {
    if (a.dataset.nav === view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  document.body.dataset.view = view; // the CSS hides the day navigation off the Day tab
  render();
}

function render() {
  if (!state.config) return;
  if (state.view === "day") return loadDay();
  if (state.view === "foods") return loadFoods();
  if (state.view === "groceries") return loadGroceries();
  if (state.view === "meals") return loadMealsView();
  if (state.view === "history") return loadHistory();
  if (state.view === "settings") return loadSettings();
  if (state.view === "help") {
    markHelpIndex();
    return Promise.all([loadTargets(), loadProfile()]).then(renderHelp, showError);
  }
}

function goDay(iso) {
  if (iso > todayISO()) return; // the future can't be logged yet
  location.hash = iso === todayISO() ? "#/" : `#/day/${iso}`;
}

/** Top bar: weekday + date, and Today / next disabled when on today. */
function renderDayNav() {
  const today = todayISO();
  const isToday = state.day === today;
  $("#day-input").value = state.day;
  $("#day-input").max = today;
  $("#day-weekday").textContent = weekdayLong.format(parseISO(state.day));
  $("#day-label").textContent = state.day;
  $("#daypick").classList.toggle("is-today", isToday);
  $("#next-day").disabled = isToday;
  $("#today-btn").disabled = isToday;
  $("#today-btn").title = isToday ? "You're on today" : "Go to today";
  $("#day-today").textContent = isToday ? "This is today" : "";
}

function openDayPicker() {
  const input = $("#day-input");
  try {
    input.showPicker();
  } catch {
    input.focus(); // older browsers: no showPicker()
  }
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
          <span class="meta">${f.kcal == null ? `<span class="warn-kcal">⚠ no kcal</span>` : `${fmt(f.kcal)} kcal`} / ${fmtQty(f.basis_qty)} ${esc(f.unit)}${stockMeta(f)}</span></li>`
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

/** "· 🛒 350 g" in a search suggestion, for foods bought in Groceries. */
function stockMeta(f) {
  if (f.in_stock == null) return "";
  return f.in_stock > 1e-6
    ? `<span class="stock-meta" title="Left in Groceries"> · 🛒 ${fmtQty(f.in_stock)} ${esc(f.unit)}</span>`
    : `<span class="stock-meta none" title="None left in Groceries"> · 🛒 none</span>`;
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
  renderDayNav();
  document.title = `${fmtDayWd(state.day)} · Pamela`;
  const day = state.day;
  try {
    const data = await api("GET", `/days/${day}`);
    if (day !== state.day) return; // user navigated meanwhile
    state.dayData = data;
    // an activity being edited on another day: drop the edit
    if (state.editingActivityId && !data.activities.some((a) => a.id === state.editingActivityId)) resetActivityForm();
    renderSummary();
    renderLog();
    renderCheckin();
    renderNote();
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
  const t = state.dayData.targets;
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

function macroCells(o, kcalCell = `<td class="n">${fmt(o.kcal)}</td>`) {
  return kcalCell + MACROS.map((m) => `<td class="n">${fmt(o[m.key], 1)}</td>`).join("");
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
      let amount = e.quantity != null ? `${fmtQty(e.quantity)} ${esc(e.unit)}` : "";
      if (e.from_stock > 1e-6) {
        const all = e.from_stock >= e.quantity - 1e-6;
        const t = all ? "Taken from Groceries" : `${fmtQty(e.from_stock)} ${e.unit} of it taken from Groceries`;
        amount = `<span class="from-stock${all ? "" : " part"}" title="${esc(t)}" aria-label="${esc(t)}">🛒</span> ${amount}`;
      }
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

/** The emoji of a logged activity's type, if that type still exists. */
function activityIcon(name) {
  const t = state.activityTypes.find((x) => x.name.toLowerCase() === name.toLowerCase());
  return t ? `<span class="act-emoji" aria-hidden="true">${t.icon}</span>` : "";
}

/** "🌡️ 18 °C · 💧 60 % · 💨 12 km/h · ★★★★☆", or "" when none are set. */
function activityConditions(a) {
  const bits = [];
  if (a.temp_c != null) bits.push(`<span title="Temperature">🌡️ ${fmt(a.temp_c, 1)} °C</span>`);
  if (a.humidity_pct != null) bits.push(`<span title="Humidity">💧 ${fmt(a.humidity_pct)} %</span>`);
  if (a.wind_kmh != null) bits.push(`<span title="Wind">💨 ${fmt(a.wind_kmh, 1)} km/h</span>`);
  if (a.comfort != null) {
    bits.push(`<span class="stars-ro" title="Felt ${a.comfort} of 5" aria-label="Felt ${a.comfort} of 5 stars">${"★".repeat(a.comfort)}<span class="off">${"★".repeat(5 - a.comfort)}</span></span>`);
  }
  return bits.join(" · ");
}

const ACT_EXTRA = ["start_time", "temp_c", "humidity_pct", "wind_kmh", "comfort"];

/** The 1-5 comfort stars in the form; picking the current value again clears it. */
function renderComfortStars() {
  const v = num($("#activity-form").elements.comfort.value);
  $("#comfort-stars").innerHTML = [1, 2, 3, 4, 5]
    .map(
      (n) => `<button type="button" class="star${v != null && n <= v ? " on" : ""}" role="radio" aria-checked="${v === n}" data-star="${n}" title="${n} of 5" aria-label="${n} star${n > 1 ? "s" : ""}">★</button>`
    )
    .join("");
}

function resetActivityForm() {
  const form = $("#activity-form");
  for (const k of ["duration_min", "distance_km", "kcal", "notes", ...ACT_EXTRA]) form.elements[k].value = "";
  state.editingActivityId = null;
  $("#act-submit").textContent = "Add";
  $("#act-cancel").hidden = true;
  $("#act-more").open = false;
  renderComfortStars();
  updateActivityForm();
  if (state.dayData) renderActivities();
}

function editActivity(id) {
  const a = state.dayData.activities.find((x) => x.id === id);
  if (!a) return;
  const form = $("#activity-form");
  const sel = $("#act-type");
  // a type deleted since: keep it selectable for this activity
  if (![...sel.options].some((o) => o.value === a.type)) sel.insertAdjacentHTML("beforeend", `<option>${esc(a.type)}</option>`);
  sel.value = a.type;
  form.elements.duration_min.value = a.duration_min;
  form.elements.distance_km.value = a.distance_km ?? "";
  form.elements.kcal.value = a.kcal_estimated ? "" : a.kcal; // empty: estimate again
  form.elements.notes.value = a.notes;
  for (const k of ACT_EXTRA) form.elements[k].value = a[k] ?? "";
  $("#act-more").open = ACT_EXTRA.some((k) => a[k] != null);
  state.editingActivityId = id;
  $("#act-submit").textContent = "Update";
  $("#act-cancel").hidden = false;
  renderComfortStars();
  updateActivityForm();
  renderActivities();
  form.elements.duration_min.focus();
}

/** From 9 PM to midnight on today: a nudge to log the day's steps. */
function updateStepsReminder() {
  const el = $("#steps-reminder");
  if (!el || !state.dayData) return;
  const late = new Date().getHours() >= 21;
  el.hidden = !(late && state.day === todayISO());
  if (el.hidden) return;
  el.textContent = state.dayData.metrics.steps
    ? "🌙 Day's almost done: update your steps with the final count before bed."
    : "🌙 Day's almost done: don't forget to log today's steps!";
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
      const cond = activityConditions(a);
      return `<li class="${a.id === state.editingActivityId ? "editing" : ""}">
        <div>${a.start_time ? `<span class="tm">${esc(a.start_time)}</span> ` : ""}<span class="t">${activityIcon(a.type)}${esc(a.type)}</span> <span class="d">${bits.join(" · ")}</span></div>
        <span class="kc">${fmt(a.kcal)} <small>kcal${a.kcal_estimated ? " (est.)" : ""}</small></span>
        <span class="act-btns"><button type="button" class="row-btn icon" data-edit-activity="${a.id}" title="Edit" aria-label="Edit ${esc(a.type)}">${PENCIL}</button><button type="button" class="row-btn del" data-del-activity="${a.id}" title="Delete" aria-label="Delete ${esc(a.type)}">✕</button></span>
        ${cond ? `<div class="cond">${cond}</div>` : ""}
        ${a.notes ? `<div class="notes">${esc(a.notes)}</div>` : ""}
      </li>`;
    })
    .join("");
}

// check-in: steps, sleep, mood ---------------------------------------------------------

function renderCheckin() {
  const m = state.dayData.metrics;
  const t = state.dayData.targets;
  const steps = $("#steps-input"), sleep = $("#sleep-input");
  const weight = $("#weight-input"), fat = $("#bodyfat-input");
  // don't clobber what the user is typing
  if (document.activeElement !== steps) steps.value = m.steps ?? "";
  if (document.activeElement !== sleep) sleep.value = m.sleep_min != null ? fmtSleep(m.sleep_min) : "";
  if (document.activeElement !== weight) weight.value = m.weight_kg ?? "";
  if (document.activeElement !== fat) fat.value = m.body_fat_pct ?? "";
  for (const el of [sleep, weight, fat]) el.classList.remove("invalid");
  updateStepsReminder();
  renderBodySub();

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
  const groups = new Map();
  for (const f of state.vocab.feelings) {
    if (!groups.has(f.group)) groups.set(f.group, []);
    groups.get(f.group).push(f);
  }
  $("#feelings").innerHTML = [...groups]
    .map(
      ([group, list]) => `<div class="feel-row" role="group" aria-label="${esc(group)}">
        <span class="feel-group"><span aria-hidden="true">${FEELING_GROUP_EMOJI[group] ?? ""}</span> ${esc(group)}</span>
        <div class="chips">${list
          .map((f) => `<button type="button" class="chip" data-feeling="${f.key}" aria-pressed="${m.feelings.includes(f.key)}">${esc(f.label)}</button>`)
          .join("")}</div>
      </div>`
    )
    .join("");
}

/** Under weight / body fat: change since the previous weigh-in, or the last one; and BMI. */
function renderBodySub() {
  const { metrics: m, previous_weight: prev } = state.dayData;
  const bits = [];
  if (m.weight_kg != null && prev) {
    const d = m.weight_kg - prev.weight_kg;
    const sign = d > 0 ? "+" : d < 0 ? "−" : "±";
    bits.push(`${sign}${fmt(Math.abs(d), 1)} kg since ${fmtDay(prev.day)}`);
  } else if (m.weight_kg == null && prev) {
    bits.push(`Last: ${fmt(prev.weight_kg, 1)} kg on ${fmtDay(prev.day)}`);
  }
  const w = m.weight_kg ?? prev?.weight_kg;
  const h = state.profile?.height_cm;
  if (w && h) bits.push(`BMI ${fmt(w / (h / 100) ** 2, 1)}`);
  $("#body-sub").textContent = bits.join(" · ");
}

/** A decimal input within (lo, hi]; "" -> null; anything else -> NaN. */
function parseDecimal(raw, lo, hi) {
  raw = raw.trim().replace(",", ".");
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) && n > lo && n <= hi ? Math.round(n * 10) / 10 : NaN;
}

function commitBody(input, key, lo, hi, msg) {
  const v = parseDecimal(input.value, lo, hi);
  if (Number.isNaN(v)) {
    input.classList.add("invalid");
    return toast(msg, true);
  }
  input.classList.remove("invalid");
  if (v !== state.dayData.metrics[key]) saveCheckin({ [key]: v });
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
    if ("weight_kg" in patch) {
      // the weight used for calorie estimates may have changed
      const day = await api("GET", `/days/${state.day}`);
      state.dayData.estimate_weight_kg = day.estimate_weight_kg;
      updateActivityForm();
    }
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

/** "+" next to steps / sleep: add what's typed to the day's total instead of replacing it. */
function addToMetric(which) {
  const m = state.dayData.metrics;
  const input = $(`#${which}-input`);
  const steps = which === "steps";
  const saved = steps ? m.steps : m.sleep_min;
  const shown = saved == null ? "" : steps ? String(saved) : fmtSleep(saved);
  if (input.value.trim() === shown) {
    input.focus();
    input.select();
    return toast(steps ? "Type the steps to add, then press +" : "Type the time to add (like 0:45), then press +");
  }
  const amount = steps ? (input.value.trim() === "" ? NaN : Number(input.value)) : parseSleep(input.value);
  if (!Number.isFinite(amount) || amount <= 0 || (steps && !Number.isInteger(amount))) {
    input.classList.add("invalid");
    return toast(steps ? "Steps to add must be a whole number above 0" : "Sleep to add: type hours like 0:45, 1.5 or 1h30", true);
  }
  const total = (saved ?? 0) + amount;
  if (steps ? total > 200000 : total > 1440) {
    input.classList.add("invalid");
    return toast(steps ? "That would make more than 200,000 steps in a day" : "That would make more than 24 h of sleep in a day", true);
  }
  input.classList.remove("invalid");
  // Show the new total right away: leaving the field later then saves that same value.
  input.value = steps ? String(total) : fmtSleep(total);
  saveCheckin(steps ? { steps: total } : { sleep_min: total });
  toast(steps ? `Added ${fmt(amount)} steps: ${fmt(total)} in total` : `Added ${fmtSleep(amount)} h: ${fmtSleep(total)} h in total`);
}

/** Leaving the field saves what's typed as the new total, unless focus went to its "+". */
function commitUnlessAdding(which, commit) {
  setTimeout(() => {
    if (document.activeElement?.dataset?.add !== which) commit();
  });
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

// notes ----------------------------------------------------------------------------

let noteShownDay = null; // the day whose note is in the textarea

function renderNote() {
  const input = $("#notes-input");
  // keep what's being typed, unless the textarea still shows another day's note
  if (document.activeElement !== input || noteShownDay !== state.day) input.value = state.dayData.note;
  noteShownDay = state.day;
  updateNoteCount();
}

function updateNoteCount() {
  const n = $("#notes-input").value.length;
  $("#notes-count").textContent = n ? `${n} / 2000` : "";
}

let notesStatusTimer, noteTimer;
let notePending = null; // day with unsaved typing in the textarea

function noteTyped() {
  notePending = noteShownDay;
  updateNoteCount();
  clearTimeout(noteTimer);
  noteTimer = setTimeout(flushNote, 1500);
}

/** Saves unsaved typing now; called on blur and before showing another day. */
function flushNote() {
  clearTimeout(noteTimer);
  if (!notePending) return;
  const day = notePending;
  notePending = null;
  saveNote(day, $("#notes-input").value.trim());
}

async function saveNote(day, text) {
  if (state.dayData?.day === day && text === state.dayData.note) return;
  const status = $("#notes-status");
  try {
    const saved = await api("PUT", `/days/${day}/note`, { text });
    if (day !== state.day) return;
    state.dayData.note = saved.text;
    status.textContent = "Saved";
    clearTimeout(notesStatusTimer);
    notesStatusTimer = setTimeout(() => (status.textContent = ""), 1500);
  } catch (err) {
    showError(err);
  }
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
  if (f.package_qty) {
    for (const [label, d] of [["⅙ pack", 6], ["¼ pack", 4], ["⅓ pack", 3], ["½ pack", 2], ["Whole pack", 1]]) {
      o.push([label, f.package_qty / d]);
    }
  }
  // rounded like a picked amount, so the chip stays highlighted for ⅙ and ⅓ too
  return o.map(([label, q]) => [label, Math.round(q * 100) / 100]);
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
  // what's left in Groceries (only for foods bought there, and only today's stock)
  let stock = "";
  if (f.in_stock != null) {
    const left = Math.max(f.in_stock, 0);
    if (left <= 1e-6) stock = " · 🛒 none left in Groceries";
    else if (qty && qty > left + 1e-6) stock = ` · 🛒 only ${fmtQty(left)} ${f.unit} in Groceries`;
    else stock = ` · 🛒 ${fmtQty(left)} ${f.unit} in Groceries`;
  }
  if (!qty) {
    $("#entry-preview").textContent =
      (f.kcal == null
        ? `${f.name}: no kcal entered yet (counted as 0), per ${fmtQty(f.basis_qty)} ${f.unit}`
        : `${f.name}: ${fmt(f.kcal)} kcal per ${fmtQty(f.basis_qty)} ${f.unit}`) + stock;
    return;
  }
  const k = qty / f.basis_qty;
  $("#entry-preview").textContent =
    (f.kcal == null ? "kcal unknown (counted as 0) · " : `≈ ${fmt(f.kcal * k)} kcal · `) + MACROS.map((m) => `${m.short} ${fmt(f[m.key] * k, 1)}`).join(" · ") + stock;
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
  const opt = (t) => `<option value="${esc(t.name)}">${t.icon} ${esc(t.name)}</option>`;
  const groups = new Map();
  for (const t of types) {
    if (!groups.has(t.category)) groups.set(t.category, []);
    groups.get(t.category).push(t);
  }
  let html = recent.length ? `<optgroup label="Recently used">${recent.map(opt).join("")}</optgroup>` : "";
  for (const [cat, list] of groups) html += `<optgroup label="${list[0].category_icon} ${esc(cat)}">${list.map(opt).join("")}</optgroup>`;
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
  const w = state.dayData?.estimate_weight_kg ?? estimateWeight();
  if (t && mins) kcal.placeholder = `≈ ${fmt((t.met * w * mins) / 60)}`;
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
    start_time: v.start_time || null,
    temp_c: num(v.temp_c),
    humidity_pct: num(v.humidity_pct),
    wind_kmh: num(v.wind_kmh),
    comfort: num(v.comfort),
  };
  try {
    const editing = state.editingActivityId;
    if (editing) {
      // keep the day it was logged on
      body.day = state.dayData.activities.find((a) => a.id === editing)?.day ?? state.day;
      await api("PUT", `/activities/${editing}`, body);
      toast("Activity updated");
    } else {
      await api("POST", "/activities", body);
    }
    resetActivityForm();
    await loadDay();
    loadActivityTypes().catch(showError); // refresh "Recently used"
  } catch (err) {
    showError(err);
  }
}

// --- foods view --------------------------------------------------------------

const FOOD_FIELDS = ["name", "brand", "ean", "basis_qty", "unit", "kcal", ...MACROS.map((m) => m.key), "serving_qty", "package_qty", "food_group"];

// Shown in place of the kcal of a food that has none entered yet.
const NO_KCAL_CELL = `<td class="n"><span class="warn-kcal" title="No kcal entered yet: counted as 0 until you add it. Enter 0 if it really has none.">⚠ ?<span class="sr"> No kcal entered yet, counted as 0</span></span></td>`;

async function loadFoods() {
  document.title = "Foods · Pamela";
  try {
    const [foods, brands] = await Promise.all([api("GET", "/foods?limit=1000"), api("GET", "/brands")]);
    state.foods = foods;
    $("#brand-options").innerHTML = brands.map((b) => `<option value="${esc(b)}">`).join("");
    renderFoods();
  } catch (err) {
    showError(err);
  }
}

/** A food as the catalog shows it: values per 100 g / 100 ml whatever basis it was
 * saved with. Foods in any other unit (u, whole, ...) keep their own basis. */
function per100(f) {
  if (!["g", "ml"].includes(f.unit.toLowerCase()) || !(f.basis_qty > 0) || f.basis_qty === 100) return f;
  const k = 100 / f.basis_qty;
  const out = { ...f, basis_qty: 100, kcal: f.kcal == null ? null : f.kcal * k };
  for (const m of MACROS) out[m.key] = f[m.key] == null ? null : f[m.key] * k;
  return out;
}

function renderFoods() {
  const words = $("#foods-filter").value.toLowerCase().split(/\s+/).filter(Boolean);
  const tags = [...state.foodTagFilter];
  const group = $("#group-filter").value;
  const rows = state.foods.filter((f) => {
    const hay = `${f.name} ${f.brand} ${f.ean ?? ""}`.toLowerCase();
    return words.every((w) => hay.includes(w)) && tags.every((t) => f[t]) && (!group || f.food_group === group);
  }).map(per100);
  const missing = state.foods.filter((f) => f.kcal == null).length;
  $("#foods-count").textContent =
    (rows.length === state.foods.length ? `(${rows.length})` : `(${rows.length} of ${state.foods.length})`) +
    (missing ? ` · ⚠ ${missing} without kcal` : "");
  const row = (f) => `<tr id="food-row-${f.id}" class="${f.id === state.editingFoodId ? "editing" : ""}">
      <td>${esc(f.name)}${tagPills(f)}</td>
      <td>${esc(f.brand)}${f.ean ? `<span class="ean" title="Barcode">${esc(f.ean)}</span>` : ""}</td>
      <td class="n">${fmtQty(f.basis_qty)} ${esc(f.unit)}</td>
      ${f.kcal == null ? macroCells(f, NO_KCAL_CELL) : macroCells(f)}
      <td class="n">${f.uses}</td>
      <td class="act"><button type="button" class="row-btn icon" data-edit-food="${f.id}" title="Edit" aria-label="Edit ${esc(f.name)}">${PENCIL}</button><button type="button" class="row-btn del" data-del-food="${f.id}" aria-label="Delete ${esc(f.name)}">✕</button></td>
    </tr>`;
  const box = $("#foods-groups");
  if (!rows.length) {
    box.innerHTML = `<p class="empty-note">${state.foods.length ? "No matches" : "No foods yet - add your first one with the form."}</p>`;
    return;
  }
  if (state.foodSort) {
    const { key, dir } = state.foodSort;
    const col = FOOD_SORT[key];
    rows.sort((a, b) => {
      const va = col.get(a), vb = col.get(b);
      if (va == null || vb == null) return (va == null) - (vb == null); // empty last, either way
      return dir * (col.text ? collator.compare(va, vb) : va - vb) || collator.compare(a.name, b.name);
    });
  }
  box.classList.toggle("hide-tags", state.hideTags);
  const th = (key, label, cls = "", title = "") => {
    const sorted = state.foodSort?.key === key ? state.foodSort.dir : 0;
    const aria = sorted ? ` aria-sort="${sorted > 0 ? "ascending" : "descending"}"` : "";
    const arrow = sorted ? (sorted > 0 ? " ▲" : " ▼") : "";
    return `<th class="${cls}"${aria}${title ? ` title="${title}"` : ""}><button type="button" class="sort-btn" data-sort="${key}">${label}<span class="sort-arrow" aria-hidden="true">${arrow}</span></button></th>`;
  };
  const head = `<tr>${th("name", "Name")}${th("brand", "Brand")}${th("per", "Per", "n")}${th("kcal", "kcal", "n")}${th("protein_g", "P", "n")}${th("carbs_g", "C", "n")}${th("fat_g", "F", "n")}${th("fiber_g", "Fib", "n")}${th("uses", "Uses", "n", "Times logged in the last 90 days")}<th class="act"><span class="sr">Actions</span></th></tr>`;
  // One table per group, in the vocabulary's order; foods without a group last.
  box.innerHTML = byFoodGroup(rows)
    .map(
      ([g, list]) => `<section class="food-group" aria-labelledby="fg-${g.key || "none"}">
      ${groupHeading(g, list.length, `fg-${g.key || "none"}`)}
      <div class="table-wrap">
        <table class="foods-table">
          <colgroup><col class="c-name"><col class="c-brand"><col class="c-per"><col class="c-n"><col class="c-n"><col class="c-n"><col class="c-n"><col class="c-n"><col class="c-n"><col class="c-act"></colgroup>
          <thead>${head}</thead>
          <tbody>${list.map(row).join("")}</tbody>
        </table>
      </div>
    </section>`
    )
    .join("");
}

const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

/** ``rows`` split by food group, in the vocabulary's order, foods without a group last;
 * empty groups are left out. Each row needs a ``food_group``. */
function byFoodGroup(rows) {
  return [...state.vocab.food_groups, { key: "", label: "No group", emoji: "📦" }]
    .map((g) => [g, rows.filter((r) => (r.food_group || "") === g.key)])
    .filter(([, list]) => list.length);
}
/** A group's heading, as in the Foods tab. */
function groupHeading(g, n, id) {
  return `<h3${id ? ` id="${id}"` : ""}><span aria-hidden="true">${g.emoji}</span> ${esc(g.label)} <span class="count">(${n})</span></h3>`;
}
// Sortable catalog columns: the value to sort by, and whether it's text. The first
// click sorts text A→Z and numbers high→low.
const FOOD_SORT = {
  name: { get: (f) => f.name, text: true },
  brand: { get: (f) => f.brand || null, text: true },
  per: { get: (f) => `${f.unit} ${String(f.basis_qty).padStart(10, "0")}`, text: true },
  kcal: { get: (f) => f.kcal },
  protein_g: { get: (f) => f.protein_g },
  carbs_g: { get: (f) => f.carbs_g },
  fat_g: { get: (f) => f.fat_g },
  fiber_g: { get: (f) => f.fiber_g },
  uses: { get: (f) => f.uses },
};

/** First click: natural order; second: reversed; third: back to most used first. */
function sortFoodsBy(key) {
  const first = FOOD_SORT[key].text ? 1 : -1;
  const cur = state.foodSort;
  if (cur?.key !== key) state.foodSort = { key, dir: first };
  else if (cur.dir === first) state.foodSort = { key, dir: -first };
  else state.foodSort = null;
  renderFoods();
  // keep focus on the header that was clicked (the tables were redrawn)
  $(`#foods-groups [data-sort="${key}"]`)?.focus();
}

/** Scrolls to a food's catalog row and flashes it, clearing filters that hide it. */
function goToFood(id) {
  if (!document.getElementById(`food-row-${id}`)) {
    $("#foods-filter").value = "";
    $("#group-filter").value = "";
    state.foodTagFilter.clear();
    for (const chip of $$("#tag-filter [data-tag]")) chip.setAttribute("aria-pressed", "false");
    renderFoods();
  }
  const tr = document.getElementById(`food-row-${id}`);
  if (!tr) return;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  tr.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
  tr.classList.remove("flash");
  void tr.offsetWidth; // restart the animation
  tr.classList.add("flash");
}

/** "✓ Added <name>" next to the form title, linking to the food's row. */
function setFoodSaved(food, verb) {
  $("#food-saved").innerHTML = food
    ? `✓ ${verb} <button type="button" class="link-btn" data-goto-food="${food.id}">${esc(food.name)}</button>`
    : "";
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
  setFoodSaved(null);
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
  const kcal = num(el.kcal.value);
  const parts = [];
  if (est) parts.push(`Macros add up to ≈ ${fmt(est)} kcal.`);
  if (kcal == null) parts.push("No kcal: it counts as 0 until you fill it in (enter 0 if it really has none).");
  else if (kcal === 0) parts.push("0 kcal: tagged Calorie-free.");
  $("#food-kcal-hint").textContent = parts.join(" ");
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
      // Don't open it: when loading many products, the next scan should just work.
      const brand = r.food.brand ? ` (${esc(r.food.brand)})` : "";
      setEanStatus(
        `Already in your catalog: <b>${esc(r.food.name)}</b>${brand}. <button type="button" class="link-btn" data-edit-food="${r.food.id}">Edit</button>`,
        "ok"
      );
      input.select(); // the next barcode replaces this one
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
    kcal: num(v.kcal), // empty = not known yet, unlike 0
    serving_qty: num(v.serving_qty) || null,
    package_qty: num(v.package_qty) || null,
    food_group: v.food_group,
  };
  for (const m of MACROS) body[m.key] = num(v[m.key]) ?? 0;
  for (const t of state.vocab.diet_tags) body[t.key] = form.elements[t.key].checked;
  try {
    const editing = state.editingFoodId;
    const saved = editing ? await api("PUT", `/foods/${editing}`, body) : await api("POST", "/foods", body);
    toast(editing ? "Food updated" : "Food added");
    resetFoodForm();
    setFoodSaved(saved, editing ? "Updated" : "Added");
    await loadFoods();
    form.elements.ean.focus();
  } catch (err) {
    showError(err);
  }
}

async function deleteFood(id) {
  const f = state.foods.find((x) => x.id === id);
  if (!f || !confirm(`Delete “${f.name}”? Past log entries keep their values. It's also removed from saved meals and groceries.`)) return;
  try {
    await api("DELETE", `/foods/${id}`);
    if (state.editingFoodId === id) resetFoodForm();
    await loadFoods();
    loadSavedMeals().catch(showError);
  } catch (err) {
    showError(err);
  }
}

// --- groceries view ----------------------------------------------------------------

const SOON_DAYS = 3; // expiry dates turn amber this many days before

function daysBetween(a, b) {
  return Math.round((parseISO(b) - parseISO(a)) / 86_400_000);
}
function fmtMoney(n) {
  if (n == null) return "–";
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
/** "500 g", plus "· 2 packs" when the food has a package size. */
function fmtStock(qty, f) {
  let s = `${fmtQty(qty)} ${esc(f.unit)}`;
  if (f.package_qty && qty > 0) {
    const p = qty / f.package_qty;
    s += ` <small>· ${fmt(p, 1)} pack${Math.abs(p - 1) < 0.05 ? "" : "s"}</small>`;
  }
  return s;
}
/** "past", "soon" or "" for an expiry date. */
function expiryClass(iso) {
  if (!iso) return "";
  const d = daysBetween(todayISO(), iso);
  return d < 0 ? "past" : d <= SOON_DAYS ? "soon" : "";
}
function expiryBadge(iso) {
  if (!iso) return `<span class="muted">–</span>`;
  const d = daysBetween(todayISO(), iso);
  const rel = d < 0 ? `${-d} d ago` : d === 0 ? "today" : d === 1 ? "tomorrow" : `in ${d} d`;
  return `<span class="exp ${expiryClass(iso)}" title="${d < 0 ? "Expired" : "Expires"} ${iso}">${iso} <small>${rel}</small></span>`;
}
function foodLabel(f) {
  return `${esc(f.name)}${f.brand ? ` <span class="brand-tag">${esc(f.brand)}</span>` : ""}`;
}

async function loadGroceries() {
  document.title = "Groceries · Pamela";
  const day = $("#trip-day");
  day.max = todayISO();
  if (!day.value || (!state.editingCartId && day.value > todayISO())) day.value = todayISO();
  renderTrip();
  try {
    state.groceries = await api("GET", "/groceries");
    // the cart being edited was deleted meanwhile (e.g. its foods were)
    if (state.editingCartId && !state.groceries.carts.some((c) => c.id === state.editingCartId)) resetCartForm();
    renderGroceries();
  } catch (err) {
    showError(err);
  }
}

function renderGroceries() {
  const g = state.groceries;
  if (!g) return;
  const inStock = g.items.filter((it) => it.lots.length);
  const ranOut = g.items.filter((it) => !it.lots.length).sort((a, b) => b.last_bought.localeCompare(a.last_bought));
  const lots = inStock.flatMap((it) => it.lots);
  const soon = lots.filter((l) => expiryClass(l.expires_on) === "soon").length;
  const past = lots.filter((l) => expiryClass(l.expires_on) === "past").length;
  const since = addDays(todayISO(), -29);
  const recent = g.carts.filter((c) => c.bought_on >= since && c.total_price != null);
  const tile = (k, v, cls = "", title = "") => `<div class="tile ${cls}"${title ? ` title="${title}"` : ""}><div class="k">${k}</div><div class="v">${v}</div></div>`;
  $("#groc-tiles").innerHTML =
    tile("Foods in stock", fmt(inStock.length)) +
    tile(`Expiring within ${SOON_DAYS} days`, fmt(soon), soon ? "warn" : "", "Items whose expiry date is today or in the next days") +
    tile("Past their date", fmt(past), past ? "bad" : "", "Items still in stock whose expiry date has passed") +
    tile("Spent, 30 days", recent.length ? fmtMoney(recent.reduce((a, c) => a + c.total_price, 0)) : "–", "", "What carts of the last 30 days cost (items with a price)") +
    tile("Thrown out, 30 days", fmt(g.expired.length), "", "Times something expired in the last 30 days");

  const stores = new Set(g.carts.map((c) => c.store).filter(Boolean));
  $("#store-options").innerHTML = [...stores].map((s) => `<option value="${esc(s)}">`).join("");

  renderStock(inStock);
  renderCarts();

  $("#ranout-count").textContent = ranOut.length ? `(${ranOut.length})` : "";
  $("#ranout-list").innerHTML = ranOut.length
    ? groupedList(
        ranOut,
        (it) => `<li><span>${foodLabel(it)} <small>last bought ${fmtDay(it.last_bought)}</small></span>
          <button type="button" class="row-btn add-to" data-buy-again="${it.food_id}">+ Buy again</button></li>`
      )
    : `<li class="empty">Nothing yet. Foods you finish show up here.</li>`;

  $("#groc-expired").innerHTML = g.expired.length
    ? groupedList(
        g.expired,
        (h) => `<li><span class="hday">${fmtDay(h.day)}</span><span><b>${fmtQty(h.quantity)} ${esc(h.unit)}</b> ${foodLabel(h)}</span>
            <button type="button" class="row-btn" data-undo-expired="${h.id}" title="Put it back in stock">Undo</button></li>`
      )
    : `<li class="empty">Nothing expired in the last 30 days.</li>`;
}

/** List items under a heading per food group (rows keep their order within a group). */
function groupedList(rows, li) {
  return byFoodGroup(rows)
    .map(([grp, list]) => `<li class="group-head">${groupHeading(grp, list.length)}</li>${list.map(li).join("")}`)
    .join("");
}

/** "Thu 2026-11-12 · Corner shop" */
function cartName(c) {
  return `${fmtDayWd(c.bought_on)}${c.store ? ` · ${c.store}` : ""}`;
}

function renderStock(items) {
  const words = $("#stock-filter").value.toLowerCase().split(/\s+/).filter(Boolean);
  const rows = items.filter((it) => words.every((w) => `${it.name} ${it.brand}`.toLowerCase().includes(w)));
  const byExpiry = $('input[name="stock-sort"]:checked').value === "expiry";
  rows.sort(
    (a, b) =>
      (byExpiry ? (a.next_expiry == null) - (b.next_expiry == null) || (a.next_expiry ?? "").localeCompare(b.next_expiry ?? "") : 0) ||
      collator.compare(a.name, b.name) ||
      collator.compare(a.brand, b.brand)
  );
  $("#stock-count").textContent = rows.length === items.length ? `(${items.length})` : `(${rows.length} of ${items.length})`;
  const box = $("#stock-groups");
  if (!rows.length) {
    box.innerHTML = `<p class="empty-note">${items.length ? "No matches" : "Nothing in stock yet. Add a cart with what you bought."}</p>`;
    return;
  }
  const row = (it) => {
      const head = `<tr class="stock-food">
        <td>${foodLabel(it)}</td>
        <td class="n">${fmtStock(it.in_stock, it)}</td>
        <td>${expiryBadge(it.next_expiry)}</td>
        <td></td>
        <td class="act"><button type="button" class="row-btn add-to" data-buy-again="${it.food_id}" title="Add it to the cart on the left">+ Buy</button></td>
      </tr>`;
      const lots = it.lots
        .map(
          (l) => `<tr class="stock-lot">
        <td><button type="button" class="link-btn lot-cart" data-edit-cart="${l.cart_id}" title="Open this cart">🛒 ${esc(cartName(l))}</button></td>
        <td class="n">${l.remaining < l.quantity ? `${fmtQty(l.remaining)} <small>of ${fmtQty(l.quantity)}</small>` : fmtQty(l.quantity)} <small>${esc(it.unit)}</small></td>
        <td>${expiryBadge(l.expires_on)}</td>
        <td class="n">${fmtMoney(l.price)}</td>
        <td class="act"><button type="button" class="row-btn expire-btn" data-expire-lot="${l.id}" title="It expired or went off">🗑️ Expired</button></td>
      </tr>`
        )
        .join("");
      return head + lots;
  };
  // One table per food group, as in Foods; fixed columns keep them lined up.
  box.innerHTML = byFoodGroup(rows)
    .map(
      ([g, list]) => `<section class="food-group" aria-labelledby="sg-${g.key || "none"}">
      ${groupHeading(g, list.length, `sg-${g.key || "none"}`)}
      <div class="table-wrap">
        <table class="stock-table">
          <colgroup><col><col class="c-left"><col class="c-exp"><col class="c-price"><col class="c-act"></colgroup>
          <thead><tr><th>Food <small>/ cart</small></th><th class="n">Left</th><th>Expires</th><th class="n">Price</th><th class="act"><span class="sr">Actions</span></th></tr></thead>
          <tbody>${list.map(row).join("")}</tbody>
        </table>
      </div>
    </section>`
    )
    .join("");
}

const CARTS_PAGE = 8;

function renderCarts() {
  const carts = state.groceries.carts;
  $("#carts-count").textContent = carts.length ? `(${carts.length})` : "";
  if (!carts.length) {
    $("#cart-list").innerHTML = `<p class="empty-note">No carts yet. Back from the shops? Add one with the form.</p>`;
    return;
  }
  const shown = carts.slice(0, state.cartsShown);
  const more = carts.length - shown.length;
  $("#cart-list").innerHTML =
    shown
      .map((c) => {
        const items =
          c.items
            .map((it) => {
              const left = it.remaining <= 1e-6 ? `<small class="muted">used up</small>` : it.remaining < it.quantity - 1e-6 ? `<small>${fmtQty(it.remaining)} left</small>` : "";
              return `<li><span>${foodLabel(it)}</span><span class="n">${fmtQty(it.quantity)} ${esc(it.unit)} ${left}</span></li>`;
            })
            .join("") +
          c.extras
            .map((x) => `<li class="extra" title="Not food: only counts towards the total"><span>${esc(x.name)}</span><span class="n">${fmtQty(x.quantity)} ${esc(x.unit)}</span></li>`)
            .join("");
        return `<article class="cart${c.id === state.editingCartId ? " editing" : ""}" id="cart-${c.id}">
          <div class="cart-top">
            <div class="cart-title"><b>${esc(fmtDayWd(c.bought_on))}</b>${c.store ? ` <span class="cart-store">${esc(c.store)}</span>` : ""}</div>
            <span class="cart-btns"><button type="button" class="row-btn icon" data-edit-cart="${c.id}" title="Edit cart" aria-label="Edit the cart of ${esc(cartName(c))}">${PENCIL}</button><button type="button" class="row-btn del" data-del-cart="${c.id}" title="Delete cart" aria-label="Delete the cart of ${esc(cartName(c))}">✕</button></span>
          </div>
          <ul class="cart-items">${items}</ul>
          <div class="cart-sum">${cartCounts(c.items.length, c.extras.length)}${cartMoney(c)}</div>
        </article>`;
      })
      .join("") +
    (more > 0 ? `<button type="button" class="btn ghost carts-more" data-more-carts>Show ${Math.min(more, CARTS_PAGE)} more (${more} older)</button>` : "");
}

/** "3 foods · 2 other items" */
function cartCounts(foods, extras) {
  const bits = [];
  if (foods) bits.push(`${foods} ${foods === 1 ? "food" : "foods"}`);
  if (extras) bits.push(`${extras} other ${extras === 1 ? "item" : "items"}`);
  return bits.join(" · ");
}
/** " · 17.63 (−1.96 discount, +2.00 delivery)" for a saved cart. */
function cartMoney(c) {
  if (c.total_price == null) return "";
  const bits = [];
  if (c.discount_amount) bits.push(`−${fmtMoney(c.discount_amount)}${c.discount_pct != null ? `, ${fmt(c.discount_pct, 2)}%` : ""} discount`);
  if (c.delivery_fee != null) bits.push(`+${fmtMoney(c.delivery_fee)} delivery`);
  const title = c.subtotal != null ? ` title="Subtotal ${fmtMoney(c.subtotal)}"` : "";
  return ` · <b>${fmtMoney(c.total_price)}</b>${bits.length ? ` <small${title}>(${bits.join(", ")})</small>` : ""}`;
}

/** The lot with this id, and the stock item it belongs to. */
function findLot(id) {
  for (const it of state.groceries?.items ?? []) {
    const lot = it.lots.find((l) => l.id === id);
    if (lot) return { it, lot };
  }
  return {};
}

// the cart being entered or edited ---------------------------------------------------------

/** Cart item: { id (null if new), food: { id, name, brand, unit, package_qty }, quantity,
 * used (already eaten or thrown out), expires_on, price }. */
function addTripItem(food, quantity) {
  const q = quantity ?? food.package_qty ?? (["g", "ml"].includes(food.unit) ? food.basis_qty : 1) ?? 1;
  state.trip.push({ id: null, food, quantity: Math.round(q * 100) / 100, used: 0, expires_on: "", price: "" });
  renderTrip();
  const i = state.trip.length - 1;
  const first = $(`#trip-body tr[data-i="${i}"] input`);
  first?.focus();
  first?.select();
}

function renderTrip() {
  const items = state.trip;
  const min = $("#trip-day").value;
  $("#trip-body").innerHTML = items.length
    ? items
        .map((it, i) => {
          const f = it.food;
          const packs = f.package_qty
            ? `<input class="qty-input packs" type="number" min="0" step="any" value="${Math.round((it.quantity / f.package_qty) * 100) / 100}" data-trip-packs="${i}" aria-label="Packs of ${esc(f.name)}" title="Packs of ${fmtQty(f.package_qty)} ${esc(f.unit)}"><span class="unit">pack</span>`
            : "";
          const used = it.used > 1e-6 ? `<small class="trip-used" title="Already eaten or thrown out: the amount can't be less">${fmtQty(it.used)} ${esc(f.unit)} used</small>` : "";
          return `<tr data-i="${i}">
          <td>${foodLabel(f)}${used}</td>
          <td class="n"><span class="with-unit qty-cell">${packs}<input class="qty-input" type="number" min="${it.used || 0}" step="any" value="${it.quantity}" data-trip-qty="${i}" aria-label="Amount of ${esc(f.name)}"><span class="unit">${esc(f.unit)}</span></span></td>
          <td><input type="date" value="${it.expires_on}" min="${min}" data-trip-exp="${i}" aria-label="Expiry date of ${esc(f.name)}"></td>
          <td class="n"><input class="price-input" type="number" min="0" step="any" value="${it.price}" data-trip-price="${i}" aria-label="Price of ${esc(f.name)}" placeholder="–"></td>
          <td class="act"><button type="button" class="row-btn del" data-trip-del="${i}" title="Remove from the cart" aria-label="Remove ${esc(f.name)}">✕</button></td>
        </tr>`;
        })
        .join("")
    : `<tr class="empty"><td colspan="5">Add the foods you bought with the search below.</td></tr>`;
  const what = cartCounts(items.length, state.tripExtras.length);
  $("#trip-submit").textContent = state.editingCartId ? "Save cart" : what ? `Add cart (${what})` : "Add cart";
  renderExtras();
  renderTripTotal();
}

/** The cart's other items (not food): { name, quantity, unit, price }. */
function renderExtras() {
  const xs = state.tripExtras;
  $("#extras-wrap").hidden = !xs.length;
  $("#extra-body").innerHTML = xs
    .map(
      (x, i) => `<tr data-i="${i}">
        <td><input type="text" class="extra-name" maxlength="200" value="${esc(x.name)}" data-extra-name="${i}" placeholder="e.g. Dish soap" aria-label="Item name"></td>
        <td class="n"><span class="with-unit qty-cell"><input class="qty-input" type="number" min="0" step="any" value="${x.quantity}" data-extra-qty="${i}" aria-label="Amount of ${esc(x.name || "item")}"><input class="unit-input" type="text" maxlength="20" value="${esc(x.unit)}" list="unit-options" data-extra-unit="${i}" aria-label="Unit"></span></td>
        <td class="n"><input class="price-input" type="number" min="0" step="any" value="${x.price}" data-extra-price="${i}" placeholder="–" aria-label="Price of ${esc(x.name || "item")}"></td>
        <td class="act"><button type="button" class="row-btn del" data-extra-del="${i}" title="Remove" aria-label="Remove ${esc(x.name || "item")}">✕</button></td>
      </tr>`
    )
    .join("");
}

function addExtra() {
  state.tripExtras.push({ name: "", quantity: 1, unit: "u", price: "" });
  renderTrip();
  $(`#extra-body [data-extra-name="${state.tripExtras.length - 1}"]`)?.focus();
}

function extraInput(e) {
  const t = e.target;
  const d = t.dataset;
  const x = state.tripExtras[Number(d.extraName ?? d.extraQty ?? d.extraUnit ?? d.extraPrice)];
  if (!x) return;
  if ("extraName" in d) x.name = t.value;
  else if ("extraQty" in d) x.quantity = num(t.value) ?? 0;
  else if ("extraUnit" in d) x.unit = t.value;
  else x.price = t.value;
  renderTripTotal();
  $("#trip-submit").textContent = state.editingCartId ? "Save cart" : `Add cart (${cartCounts(state.trip.length, state.tripExtras.length)})`;
}

/** "2.50" -> { discount: 2.5 }, "10%" -> { discount_pct: 10 }, "" -> {}; NaN fields if invalid. */
function parseDiscount(raw) {
  raw = raw.trim().replace(",", ".").replace(/\s+/g, "");
  if (!raw) return {};
  const pct = raw.endsWith("%");
  const n = Number(pct ? raw.slice(0, -1) : raw);
  if (!Number.isFinite(n) || n <= 0 || (pct && n > 100)) return { invalid: true };
  return pct ? { discount_pct: n } : { discount: Math.round(n * 100) / 100 };
}

function tripInput(e) {
  const t = e.target;
  const i = Number(t.dataset.tripQty ?? t.dataset.tripPacks ?? t.dataset.tripExp ?? t.dataset.tripPrice);
  const it = state.trip[i];
  if (!it) return;
  const row = t.closest("tr");
  if ("tripQty" in t.dataset) {
    it.quantity = num(t.value) ?? 0;
    const packs = $("[data-trip-packs]", row);
    if (packs) packs.value = it.quantity ? Math.round((it.quantity / it.food.package_qty) * 100) / 100 : "";
  } else if ("tripPacks" in t.dataset) {
    it.quantity = Math.round((num(t.value) ?? 0) * it.food.package_qty * 100) / 100;
    $("[data-trip-qty]", row).value = it.quantity || "";
  } else if ("tripExp" in t.dataset) {
    it.expires_on = t.value;
  } else {
    it.price = t.value;
    renderTripTotal();
  }
}
/** Subtotal, discount and total of the cart in the form. */
function tripMoney() {
  const prices = [...state.trip, ...state.tripExtras].map((it) => num(it.price)).filter((p) => p != null);
  const subtotal = prices.reduce((a, p) => a + p, 0);
  const d = parseDiscount($("#trip-discount").value);
  const off = d.discount ?? (d.discount_pct != null ? Math.round(subtotal * d.discount_pct) / 100 : 0);
  const fee = num($("#trip-fee").value);
  return { priced: prices.length > 0, subtotal, d, off, fee, total: subtotal - off + (fee ?? 0) };
}

function renderTripTotal() {
  $("#trip-total").textContent = cartCounts(state.trip.length, state.tripExtras.length);
  const m = tripMoney();
  const input = $("#trip-discount");
  input.classList.toggle("invalid", !!m.d.invalid || m.off > m.subtotal + 1e-9);
  $("#trip-fee").classList.toggle("invalid", m.fee != null && m.fee < 0);
  if (!m.priced && !m.off && m.fee == null) {
    $("#trip-sum").innerHTML = "";
    return;
  }
  let html = `<dt>Subtotal</dt><dd>${fmtMoney(m.subtotal)}</dd>`;
  if (m.d.invalid) html += `<dt>Discount</dt><dd class="bad">type an amount (2.50) or a % (10%)</dd>`;
  else if (m.off) {
    const pct = m.d.discount_pct != null ? ` <small>(${fmt(m.d.discount_pct, 2)}%)</small>` : "";
    html += `<dt>Discount${pct}</dt><dd class="${m.off > m.subtotal + 1e-9 ? "bad" : ""}">−${fmtMoney(m.off)}</dd>`;
  }
  if (m.fee != null) html += `<dt>Delivery fee</dt><dd>+${fmtMoney(m.fee)}</dd>`;
  html += `<dt class="tot">Total</dt><dd class="tot">${fmtMoney(Math.max(m.total, 0))}</dd>`;
  $("#trip-sum").innerHTML = html;
}

async function submitTrip(ev) {
  ev.preventDefault();
  const form = ev.currentTarget; // null once an await has run
  const v = formValues(form);
  if (!v.bought_on || v.bought_on > todayISO()) {
    toast("Pick the day you bought them (today or before)", true);
    return $("#trip-day").focus();
  }
  if (!state.trip.length && !state.tripExtras.length) {
    toast(state.editingCartId ? "A cart needs at least one item. To remove it all, delete the cart" : "Add what you bought first", true);
    return $("#trip-search").focus();
  }
  const noName = state.tripExtras.findIndex((x) => !x.name.trim());
  if (noName >= 0) {
    toast("Give each other item a name (or remove it)", true);
    return $(`#extra-body [data-extra-name="${noName}"]`)?.focus();
  }
  const noQty = state.tripExtras.findIndex((x) => !(x.quantity > 0) || !x.unit.trim());
  if (noQty >= 0) {
    toast(`${state.tripExtras[noQty].name}: enter an amount and a unit`, true);
    return $(`#extra-body [data-extra-qty="${noQty}"]`)?.focus();
  }
  const money = tripMoney();
  if (money.d.invalid) {
    toast("Discount: type an amount (2.50) or a percentage (10%)", true);
    return $("#trip-discount").focus();
  }
  if (money.fee != null && money.fee < 0) {
    toast("The delivery fee can't be negative", true);
    return $("#trip-fee").focus();
  }
  if (money.off > money.subtotal + 1e-9) {
    toast(`The discount (${fmtMoney(money.off)}) is more than the subtotal (${fmtMoney(money.subtotal)})`, true);
    return $("#trip-discount").focus();
  }
  const bad = state.trip.findIndex((it) => !(it.quantity > 0));
  if (bad >= 0) {
    toast(`Enter how much ${state.trip[bad].food.name} you bought`, true);
    return $(`#trip-body [data-trip-qty="${bad}"]`)?.focus();
  }
  const low = state.trip.findIndex((it) => it.quantity < it.used - 1e-6);
  if (low >= 0) {
    const it = state.trip[low];
    toast(`${it.food.name}: ${fmtQty(it.used)} ${it.food.unit} of it is already used, so you bought at least that`, true);
    return $(`#trip-body [data-trip-qty="${low}"]`)?.focus();
  }
  const early = state.trip.findIndex((it) => it.expires_on && it.expires_on < v.bought_on);
  if (early >= 0) {
    toast(`${state.trip[early].food.name}: the expiry date is before the day you bought it`, true);
    return $(`#trip-body [data-trip-exp="${early}"]`)?.focus();
  }
  const body = {
    bought_on: v.bought_on,
    store: v.store.trim(),
    items: state.trip.map((it) => ({ id: it.id, food_id: it.food.id, quantity: it.quantity, expires_on: it.expires_on || null, price: num(it.price) })),
    extras: state.tripExtras.map((x) => ({ name: x.name.trim(), quantity: x.quantity, unit: x.unit.trim(), price: num(x.price) })),
    discount: money.d.discount ?? null,
    discount_pct: money.d.discount_pct ?? null,
    delivery_fee: money.fee,
  };
  const editing = state.editingCartId;
  try {
    const cart = editing ? await api("PUT", `/groceries/carts/${editing}`, body) : await api("POST", "/groceries/carts", body);
    toast(editing ? "Cart updated" : `Added the cart of ${cartName(cart)}`);
    resetCartForm();
    await loadGroceries();
    flashCart(cart.id);
    if (!editing) $("#trip-search").focus();
  } catch (err) {
    showError(err);
  }
}

/** Back to an empty "New cart" form. */
function resetCartForm() {
  state.editingCartId = null;
  state.trip = [];
  state.tripExtras = [];
  const form = $("#trip-form");
  form.elements.store.value = "";
  $("#trip-discount").value = "";
  $("#trip-fee").value = "";
  $("#trip-day").value = todayISO();
  $("#trip-h").textContent = "🛒 New cart";
  $("#cart-cancel").hidden = true;
  $("#cart-delete").hidden = true;
  renderTrip();
  if (state.groceries) renderCarts();
}

function editCart(id) {
  const c = state.groceries?.carts.find((x) => x.id === id);
  if (!c) return;
  const filling = state.trip.length || state.tripExtras.length;
  if (filling && !state.editingCartId && !confirm("Drop the new cart you were filling in, to edit this one?")) return;
  state.editingCartId = id;
  state.trip = c.items.map((it) => ({
    id: it.id,
    food: { id: it.food_id, name: it.name, brand: it.brand, unit: it.unit, package_qty: it.package_qty },
    quantity: it.quantity,
    used: it.eaten + it.expired,
    expires_on: it.expires_on ?? "",
    price: it.price ?? "",
  }));
  state.tripExtras = c.extras.map((x) => ({ name: x.name, quantity: x.quantity, unit: x.unit, price: x.price ?? "" }));
  const form = $("#trip-form");
  form.elements.store.value = c.store;
  $("#trip-discount").value = c.discount_pct != null ? `${c.discount_pct}%` : c.discount ?? "";
  $("#trip-fee").value = c.delivery_fee ?? "";
  $("#trip-day").value = c.bought_on;
  $("#trip-h").textContent = `✏️ Edit cart · ${fmtDayWd(c.bought_on)}`;
  $("#cart-cancel").hidden = false;
  $("#cart-delete").hidden = false;
  renderTrip();
  renderCarts();
  $(".trip-card").scrollIntoView({ block: "nearest" });
  $("#trip-day").focus();
}

async function deleteCart(id) {
  const c = state.groceries?.carts.find((x) => x.id === id);
  if (!c) return;
  const msg = `Delete the cart of ${cartName(c)} (${cartCounts(c.items.length, c.extras.length)})?\n\nWhat's left of it leaves your stock. Logged days stay as they are. It can't be undone.`;
  if (!confirm(msg)) return;
  try {
    await api("DELETE", `/groceries/carts/${id}`);
    if (state.editingCartId === id) resetCartForm();
    toast("Cart deleted");
    await loadGroceries();
  } catch (err) {
    showError(err);
  }
}

/** Scrolls to a cart in the list and flashes it. */
function flashCart(id) {
  const idx = state.groceries.carts.findIndex((c) => c.id === id);
  if (idx >= state.cartsShown) {
    state.cartsShown = idx + 1;
    renderCarts();
  }
  const el = document.getElementById(`cart-${id}`);
  if (!el) return;
  el.classList.remove("flash");
  void el.offsetWidth; // restart the animation
  el.classList.add("flash");
}

function buyAgain(foodId) {
  const it = state.groceries.items.find((x) => x.food_id === foodId);
  if (!it) return;
  addTripItem({ id: it.food_id, name: it.name, brand: it.brand, unit: it.unit, package_qty: it.package_qty }, it.last_quantity);
  $(".trip-card").scrollIntoView({ block: "nearest" });
}

// expiring ----------------------------------------------------------------------------------

let dialogLot = null;

function openExpire(id) {
  const { it, lot } = findLot(id);
  if (!lot) return;
  dialogLot = lot;
  const el = $("#expire-form").elements;
  $("#expire-what").innerHTML = `${foodLabel(it)}, from the cart of ${esc(cartName(lot))}: ${fmtQty(lot.remaining)} ${esc(it.unit)} left.`;
  $("#expire-unit").textContent = it.unit;
  el.quantity.value = Math.round(lot.remaining * 100) / 100;
  el.quantity.max = lot.remaining;
  el.day.value = todayISO();
  el.day.min = lot.bought_on;
  el.day.max = todayISO();
  $("#expire-dialog").showModal();
  el.quantity.select();
}

async function submitExpire(ev) {
  ev.preventDefault();
  const lot = dialogLot;
  const el = ev.currentTarget.elements;
  const qty = num(el.quantity.value);
  if (!qty || qty <= 0) return toast("Enter how much expired", true);
  if (!el.day.value || el.day.value > todayISO()) return toast("Pick when it expired (today or before)", true);
  // all that's left: let the server take the exact amount (no rounding leftovers)
  const all = qty >= lot.remaining - 0.005;
  try {
    await api("POST", `/groceries/lots/${lot.id}/expired`, { day: el.day.value, quantity: all ? null : qty });
    $("#expire-dialog").close();
    toast("Taken out of your stock");
    await loadGroceries();
  } catch (err) {
    showError(err);
  }
}

async function undoExpired(id) {
  try {
    await api("DELETE", `/groceries/expired/${id}`);
    toast("Back in your stock");
    await loadGroceries();
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
        <ul class="sm-foods">${sm.items.map((it) => `<li><span>${esc(it.name)}${it.kcal_missing ? ` <span class="warn-kcal" title="No kcal entered yet for this food: counted as 0">⚠</span>` : ""}</span><span class="n">${fmtQty(it.quantity)} ${esc(it.unit)}</span></li>`).join("")}</ul>
        <div class="sm-tot"><b>${fmt(t.kcal)}</b> kcal · ${MACROS.map((m) => `${m.short} ${fmt(t[m.key])}`).join(" · ")}</div>
        <div class="sm-actions">
          <button type="button" class="btn" data-use-sm="${sm.id}" title="Open today with this meal as a draft">Use today</button>
          <button type="button" class="row-btn icon" data-edit-sm="${sm.id}" title="Edit" aria-label="Edit ${esc(sm.name)}">${PENCIL}</button>
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

async function loadProfile() {
  state.profile = await api("GET", "/profile");
}

/** Weight for calorie estimates today: the latest logged one, else info/config.toml's. */
function estimateWeight() {
  return state.profile?.estimate_weight_kg ?? state.config.profile.weight_kg;
}

function renderProfile() {
  const p = state.profile;
  const form = $("#profile-form");
  form.elements.gender.value = p.gender;
  form.elements.height_cm.value = p.height_cm ?? "";
  const lw = p.last_weight;
  const rows = [
    ["Latest weight", lw ? `${fmt(lw.weight_kg, 1)} kg <small>on ${fmtDay(lw.day)}</small>` : `<span class="muted">none logged yet</span>`],
    ["Used for estimates", `${fmt(p.estimate_weight_kg, 1)} kg${lw ? "" : " <small>(from info/config.toml)</small>"}`],
  ];
  if (lw && p.height_cm) rows.push(["BMI", fmt(lw.weight_kg / (p.height_cm / 100) ** 2, 1)]);
  $("#profile-stats").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

/** The references editor: one BMI input per bracket boundary, kg next to it. */
function renderRefsForm(values) {
  const refs = state.bodyRefs;
  if (!refs) return;
  const cut = values ?? refs.cutoffs;
  const groupLabel = { male: "men", female: "women", other: "everyone else" }[refs.gender_group];
  $("#refs-status").textContent = refs.custom
    ? "Using your own values."
    : `Using the defaults for ${groupLabel} (from your gender).`;
  $("#refs-inputs").innerHTML = refs.brackets
    .slice(1)
    .map(
      (b, i) => `<label class="field"><span>${esc(b.label)} from</span>
        <input type="number" name="cut${i}" min="0" step="0.1" inputmode="decimal" value="${cut[i]}" data-cut="${i}">
        <small class="refs-kg" data-kg="${i}"></small></label>`
    )
    .join("");
  checkRefs();
}

/** Validates the inputs (above 0, strictly increasing), shows kg, toggles Save. */
function checkRefs() {
  const inputs = $$("#refs-inputs [data-cut]");
  const vals = inputs.map((el) => num(el.value));
  const h = heightM();
  inputs.forEach((el, i) => {
    $(`[data-kg="${i}"]`).textContent = h && vals[i] > 0 ? `≈ ${fmt(vals[i] * h ** 2, 1)} kg` : "";
  });
  let error = "";
  const bad = new Set();
  vals.forEach((v, i) => {
    const problem =
      v == null || v <= 0
        ? "Every value must be a number above 0."
        : i && vals[i - 1] != null && v <= vals[i - 1]
          ? "Each value must be higher than the one before."
          : "";
    if (problem) {
      bad.add(i);
      error ||= problem;
    }
  });
  inputs.forEach((el, i) => el.setAttribute("aria-invalid", String(bad.has(i))));
  $("#refs-error").textContent = error;
  $("#refs-save").disabled = !!error;
  return error ? null : vals;
}

async function saveRefs(cutoffs) {
  try {
    state.bodyRefs = await api("PUT", "/body-references", { cutoffs });
    renderRefsForm();
    toast(cutoffs ? "References saved" : "Back to your gender's defaults");
  } catch (err) {
    showError(err);
  }
}

async function submitProfile(ev) {
  ev.preventDefault();
  const v = formValues(ev.currentTarget);
  try {
    state.profile = await api("PUT", "/profile", { gender: v.gender, height_cm: num(v.height_cm) });
    state.bodyRefs = await api("GET", "/body-references"); // the defaults follow the gender
    renderProfile();
    renderRefsForm();
    toast("Profile saved");
  } catch (err) {
    showError(err);
  }
}

async function loadSettings() {
  document.title = "Settings · Pamela";
  try {
    await Promise.all([
      loadActivityTypes(),
      loadTargets(),
      loadProfile(),
      api("GET", "/body-references").then((r) => (state.bodyRefs = r)),
    ]);
    renderProfile();
    renderRefsForm();
    renderTargets();
    renderTypes();
    updateTypeEmojiPlaceholder();
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
  const w = estimateWeight();
  let html = "", cat = null;
  for (const t of rows) {
    if (t.category !== cat) {
      cat = t.category;
      html += `<tr class="group-head"><td colspan="6"><span class="at-emoji" aria-hidden="true">${t.category_icon}</span>${esc(cat)}</td></tr>`;
    }
    html += `<tr class="${t.id === state.editingTypeId ? "editing" : ""}">
      <td><span class="at-emoji${t.emoji ? "" : " inherited"}" aria-hidden="true" title="${t.emoji ? "" : "Group default"}">${t.icon}</span>${esc(t.name)}</td><td class="n">${fmtQty(t.met)}</td><td class="n">${fmt(t.met * w)}</td>
      <td>${t.distance ? "yes" : ""}</td><td class="n">${t.uses || ""}</td>
      <td class="act"><button type="button" class="row-btn icon" data-edit-type="${t.id}" title="Edit" aria-label="Edit ${esc(t.name)}">${PENCIL}</button><button type="button" class="row-btn del" data-del-type="${t.id}" aria-label="Delete ${esc(t.name)}">✕</button></td>
    </tr>`;
  }
  $("#at-body").innerHTML = html || `<tr class="empty"><td colspan="6">No matches</td></tr>`;
}

function updateTypeHint() {
  const met = num($("#at-form").elements.met.value);
  const w = estimateWeight();
  $("#at-hint").textContent = met ? `≈ ${fmt(met * w)} kcal per hour at your weight (${fmtQty(w)} kg)` : "";
}

/** The emoji box shows its group's default as a placeholder while it's empty. */
function updateTypeEmojiPlaceholder() {
  const el = $("#at-form").elements;
  const cat = el.category.value.trim();
  const known = state.activityTypes.find((t) => t.category === cat);
  el.emoji.placeholder = known ? known.category_icon : "💪"; // a new group: the server's fallback
}

function resetTypeForm() {
  $("#at-form").reset();
  state.editingTypeId = null;
  $("#at-form-h").textContent = "New exercise type";
  $("#at-submit").textContent = "Add type";
  $("#at-cancel").hidden = true;
  updateTypeHint();
  updateTypeEmojiPlaceholder();
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
  el.emoji.value = t.emoji;
  updateTypeEmojiPlaceholder();
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
  const body = {
    name: v.name.trim(),
    category: v.category.trim(),
    met: num(v.met),
    distance: form.elements.distance.checked,
    emoji: (v.emoji || "").trim(),
  };
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

// --- settings view (targets) ------------------------------------------------------

function fmtTarget(t, v) {
  return t.key === "sleep_h" ? `${v} h` : `${fmt(v)} ${t.unit}`;
}

/** "Until 2 Nov: 2,000 · 3 Nov – 4 Nov: 2,400 · From 5 Nov: 1,800" */
function periodsSummary(t) {
  if (t.periods.length === 1) return `<span class="muted">Same every day</span>`;
  return t.periods
    .map((p, i) => {
      const next = t.periods[i + 1];
      const end = next ? fmtDay(addDays(next.start, -1)) : null;
      const when = p.start == null ? `Until ${end}` : end ? `${fmtDay(p.start)} – ${end}` : `From ${fmtDay(p.start)}`;
      return `<span class="period">${when}: <b>${fmtTarget(t, p.value)}</b></span>`;
    })
    .join("");
}

function renderTargets() {
  const today = todayISO();
  const ed = state.targetEdit;
  $("#targets-body").innerHTML = state.targets
    .map((t) => {
      const v = targetOn(t.periods, today);
      let html = `<tr class="${ed?.key === t.key ? "editing" : ""}">
        <td><span aria-hidden="true">${TARGET_EMOJI[t.key] ?? ""}</span> ${esc(t.label)}</td>
        <td class="n"><b>${v == null ? "—" : fmtTarget(t, v)}</b></td>
        <td class="periods">${periodsSummary(t)}</td>
        <td class="act"><button type="button" class="row-btn icon" data-edit-target="${t.key}" title="Edit" aria-label="Edit the ${esc(t.label)} target">${PENCIL}</button></td>
      </tr>`;
      if (ed?.key === t.key) html += `<tr class="target-editor"><td colspan="4">${targetEditor(t, ed)}</td></tr>`;
      return html;
    })
    .join("");
}

function targetEditor(t, ed) {
  const unit = t.key === "sleep_h" ? "h" : t.unit;
  const valueInput = (i, v) =>
    `<span class="with-unit"><input type="number" min="1" step="1" ${t.max ? `max="${t.max}"` : ""} inputmode="numeric" value="${v ?? ""}" data-tval="${i}" aria-label="${esc(t.label)} target"><span class="unit">${esc(unit)}</span></span>`;
  let body;
  if (ed.mode === "single") {
    body = `<div class="tsingle">${valueInput(0, ed.periods[0].value)}<span class="hint">Used for every day, past and future.</span></div>`;
  } else {
    const rows = ed.periods
      .map((p, i) => {
        const next = ed.periods[i + 1];
        const until = next?.start ? fmtDay(addDays(next.start, -1)) : next ? "…" : "onwards";
        const from = i === 0 ? `<span class="muted">The beginning</span>` : `<input type="text" class="date-text" value="${p.start ?? ""}" data-tstart="${i}" placeholder="YYYY-MM-DD" maxlength="10" inputmode="numeric" aria-label="Period ${i + 1} starts on (YYYY-MM-DD)" required>`;
        const del = i === 0 ? "" : `<button type="button" class="row-btn del" data-tdel="${i}" title="Remove period" aria-label="Remove period ${i + 1}">✕</button>`;
        return `<tr><td>${from}</td><td class="muted">${until}</td><td>${valueInput(i, p.value)}</td><td class="act">${del}</td></tr>`;
      })
      .join("");
    body = `<table class="tperiods"><thead><tr><th>From</th><th>Until</th><th>Target</th><th class="act"><span class="sr">Actions</span></th></tr></thead><tbody>${rows}</tbody></table>
      <button type="button" class="btn ghost" data-tadd>+ Add period</button>`;
  }
  return `<div class="tedit">
    <div class="seg" role="radiogroup" aria-label="How the ${esc(t.label)} target is set">
      <label><input type="radio" name="tmode" value="single" ${ed.mode === "single" ? "checked" : ""}><span>Single value</span></label>
      <label><input type="radio" name="tmode" value="periods" ${ed.mode === "periods" ? "checked" : ""}><span>Custom periods</span></label>
    </div>
    ${body}
    <p class="hint error" id="target-error" aria-live="polite"></p>
    <div class="tactions"><button type="button" class="btn ghost" data-tcancel>Cancel</button><button type="button" class="btn primary" data-tsave>Save</button></div>
  </div>`;
}

function editTarget(key) {
  const t = state.targets.find((x) => x.key === key);
  state.targetEdit = {
    key,
    mode: t.periods.length > 1 ? "periods" : "single",
    periods: t.periods.map((p) => ({ ...p })),
  };
  renderTargets();
  $("#targets-body [data-tval]")?.focus();
}

function setTargetMode(mode) {
  const ed = state.targetEdit;
  const today = todayISO();
  if (mode === "single") {
    // keep the value in force today
    const [first, ...rest] = ed.periods;
    const dated = rest.filter((p) => p.start).sort((a, b) => (a.start < b.start ? -1 : 1));
    ed.periods = [{ start: null, value: targetOn([first, ...dated], today) }];
  } else if (ed.periods.length === 1) {
    // start with "until yesterday" + "from today", both with the current value
    ed.periods.push({ start: today, value: ed.periods[0].value });
  }
  ed.mode = mode;
  renderTargets();
}

function addTargetPeriod() {
  const ed = state.targetEdit;
  const last = ed.periods[ed.periods.length - 1];
  const today = todayISO();
  const start = last.start && last.start >= today ? addDays(last.start, 1) : today;
  ed.periods.push({ start, value: last.value });
  renderTargets();
  $(`#targets-body [data-tstart="${ed.periods.length - 1}"]`)?.focus();
}

/** Checks the edited periods; returns them sorted, or shows why not and returns null. */
function validTargetPeriods(t, ed) {
  const err = (msg) => {
    $("#target-error").textContent = msg;
    return null;
  };
  const [first, ...rest] = ed.periods;
  if (rest.some((p) => !p.start)) return err("Every period after the first needs a start date.");
  if (rest.some((p) => !isISODate(p.start))) return err("Start dates must be real dates written as YYYY-MM-DD.");
  const sorted = [first, ...rest.sort((a, b) => (a.start < b.start ? -1 : 1))];
  const starts = rest.map((p) => p.start);
  if (new Set(starts).size !== starts.length) return err("Two periods start on the same day.");
  for (const p of sorted) {
    if (!Number.isInteger(p.value) || p.value < 1) return err(`${t.label} targets must be whole numbers greater than 0.`);
    if (t.max && p.value > t.max) return err(`${t.label} can't be more than ${t.max} ${t.unit}.`);
  }
  return sorted;
}

async function saveTarget() {
  const ed = state.targetEdit;
  const t = state.targets.find((x) => x.key === ed.key);
  const periods = validTargetPeriods(t, ed);
  if (!periods) return;
  const reset = ed.mode === "single" && t.periods.length > 1;
  if (
    reset &&
    !confirm(
      `Reset the ${t.label} target?\n\nIts ${t.periods.length} custom periods will be deleted, and ` +
        `${fmtTarget(t, periods[0].value)} will be the target for every day, past and future.`
    )
  ) {
    return;
  }
  try {
    await api("PUT", `/targets/${ed.key}`, { periods });
    await loadTargets();
    state.targetEdit = null;
    renderTargets();
    toast(reset ? `${t.label} target reset` : `${t.label} target saved`);
  } catch (err) {
    $("#target-error").textContent = err.message;
  }
}

function wireTargets() {
  const body = $("#targets-body");
  body.addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit-target]");
    if (edit) {
      // the pencil toggles the editor
      if (state.targetEdit?.key === edit.dataset.editTarget) {
        state.targetEdit = null;
        return renderTargets();
      }
      return editTarget(edit.dataset.editTarget);
    }
    if (e.target.closest("[data-tadd]")) return addTargetPeriod();
    if (e.target.closest("[data-tsave]")) return saveTarget();
    if (e.target.closest("[data-tcancel]")) {
      state.targetEdit = null;
      return renderTargets();
    }
    const del = e.target.closest("[data-tdel]");
    if (del) {
      state.targetEdit.periods.splice(Number(del.dataset.tdel), 1);
      if (state.targetEdit.periods.length === 1) state.targetEdit.mode = "single";
      renderTargets();
    }
  });
  body.addEventListener("input", (e) => {
    const ed = state.targetEdit;
    if (!ed) return;
    if (e.target.dataset.tval != null) {
      const raw = e.target.value.trim();
      ed.periods[Number(e.target.dataset.tval)].value = raw === "" ? null : Number(raw);
    }
  });
  body.addEventListener("change", (e) => {
    const ed = state.targetEdit;
    if (!ed) return;
    if (e.target.name === "tmode") return setTargetMode(e.target.value);
    if (e.target.dataset.tstart != null) {
      ed.periods[Number(e.target.dataset.tstart)].start = e.target.value || null;
      const i = Number(e.target.dataset.tstart);
      renderTargets(); // refresh the "Until" column
      $(`#targets-body [data-tstart="${i}"]`)?.focus();
    }
  });
  body.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.closest("input[data-tval]")) saveTarget();
    if (e.key === "Escape" && state.targetEdit) {
      state.targetEdit = null;
      renderTargets();
    }
  });
}

// --- history view ------------------------------------------------------------

async function loadHistory() {
  document.title = "History · Pamela";
  const end = todayISO();
  const start = addDays(end, -(state.historyRange - 1));
  try {
    $("#history-range").textContent = `${fmtDayWd(start)} → ${fmtDayWd(end)}`;
    const [days, baseline] = await Promise.all([
      api("GET", `/history?start=${start}&end=${end}`),
      api("GET", `/history/baseline?before=${start}`),
    ]);
    for (const d of days) d.sleep_h = d.sleep_min != null ? d.sleep_min / 60 : null;
    // the profile (height) and the weight references, for the BMI view
    [state.profile, state.bodyRefs] = await Promise.all([api("GET", "/profile"), api("GET", "/body-references")]);
    state.historyDays = days;
    renderHistory(days, baseline);
  } catch (err) {
    showError(err);
  }
}

function moodLabel(mood) {
  return state.vocab.moods.find((m) => Number(m.key) === mood)?.label ?? "";
}

function renderHistory(days, baseline) {
  const logged = days.filter((d) => d.entry_count > 0);
  const avg = (key, list = logged) => (list.length ? list.reduce((s, d) => s + d[key], 0) / list.length : null);
  const withKey = (key) => days.filter((d) => d[key] != null);
  const t = days[days.length - 1].targets; // in force on the last (latest) day
  const activeDays = days.filter((d) => d.active_min > 0).length;
  const sleepAvg = avg("sleep_min", withKey("sleep_min"));
  const moodAvg = avg("mood", withKey("mood"));
  const lastOf = (key) => withKey(key).at(-1);
  /** ▲ / – / ▼ for the period's latest measurement against the latest one before it. */
  const trend = (key, unit) => {
    const last = lastOf(key), before = baseline[key];
    if (!last) return null;
    const now = last[key];
    if (!before) return { cls: "flat", text: "–", title: `Logged ${fmtDay(last.day)}. Nothing logged before this period to compare with` };
    const d = Math.round((now - before.value) * 10) / 10;
    const change = d === 0 ? "No change" : `${d > 0 ? "+" : "−"}${fmt(Math.abs(d), 1)}${unit}`;
    const title = `${change} since ${fmt(before.value, 1)}${unit} on ${fmtDay(before.day)}, the latest before this period (this one: ${fmtDay(last.day)})`;
    if (d === 0) return { cls: "flat", text: "–", title };
    return { cls: d > 0 ? "up" : "down", text: d > 0 ? "▲" : "▼", title };
  };
  // A gauge fills the tile up to value / target, and turns amber when an
  // overshoot counts (kcal, protein: more than 10% over).
  const gauge = (value, target, overshoot = false) =>
    value != null && target ? { pct: value / target, overshoot: overshoot && value > target * 1.1 } : null;
  const sleepAvgH = sleepAvg != null ? sleepAvg / 60 : null;
  const stepsAvg = avg("steps", withKey("steps"));
  const weight = trend("weight_kg", " kg"), fat = trend("body_fat_pct", " %");
  // { k: label, v: value, s: note, g: gauge, t: trend } (a trend replaces the note)
  const tiles = [
    { k: "Avg kcal / logged day", v: fmt(avg("kcal")), s: t.kcal ? `of ${fmt(t.kcal)}` : "", g: gauge(avg("kcal"), t.kcal, true) },
    { k: "Avg protein", v: `${fmt(avg("protein_g"))} g`, s: t.protein_g ? `of ${fmt(t.protein_g)} g` : "", g: gauge(avg("protein_g"), t.protein_g, true) },
    { k: "Days logged", v: `${logged.length}`, s: `of ${days.length}`, g: gauge(logged.length, days.length) },
    { k: "Active days", v: `${activeDays}`, s: `of ${days.length}`, g: gauge(activeDays, days.length) },
    { k: "Avg burned / day", v: fmt(avg("burned_kcal", days)), s: "kcal" },
    { k: "Avg steps", v: fmt(stepsAvg), s: t.steps ? `of ${fmt(t.steps)}` : "", g: gauge(stepsAvg, t.steps) },
    { k: "Avg sleep", v: sleepAvg != null ? fmtSleep(sleepAvg) : "–", s: t.sleep_h ? `of ${fmtSleep(t.sleep_h * 60)} h` : "h", g: gauge(sleepAvgH, t.sleep_h) },
    { k: "Latest weight", v: lastOf("weight_kg") ? `${fmt(lastOf("weight_kg").weight_kg, 1)} kg` : "–", t: weight },
    { k: "Latest body fat", v: lastOf("body_fat_pct") ? `${fmt(lastOf("body_fat_pct").body_fat_pct, 1)} %` : "–", t: fat },
    // mood runs from 1 (awful) to 5 (great): awful is an empty tile, great a full one
    { k: "Avg mood", v: moodAvg != null ? `${MOOD_EMOJI[Math.round(moodAvg)]}` : "–", s: moodAvg != null ? `${moodLabel(Math.round(moodAvg))} · ${fmt(moodAvg, 1)} / 5` : "", g: gauge(moodAvg != null ? moodAvg - 1 : null, 4) },
  ];
  $("#history-tiles").innerHTML = tiles
    .map(({ k, v, s = "", g, t: tr }) => {
      const note = tr ? `<small class="trend ${tr.cls}" aria-label="${esc(tr.title)}">${tr.text}</small>` : `<small>${s}</small>`;
      const body = `<div class="k" title="${esc(k)}">${k}</div><div class="v">${v} ${note}</div>`;
      if (!g) return `<div class="tile"${tr ? ` title="${esc(tr.title)}"` : ""}>${body}</div>`;
      const pct = Math.round(g.pct * 100);
      const title = k === "Avg mood" ? "" : ` title="${pct}% of ${k.startsWith("Avg") ? "target" : "the period"}${g.overshoot ? ": more than 10% over" : ""}"`;
      return `<div class="tile gauge${g.overshoot ? " overshoot" : ""}" style="--fill:${Math.min(100, Math.max(0, pct))}%"${title}>${body}</div>`;
    })
    .join("");

  barChart($("#chart-kcal"), days, "kcal", "kcal");
  barChart($("#chart-protein"), days, "protein_g", "g");
  barChart($("#chart-steps"), days, "steps", "steps");
  barChart($("#chart-sleep"), days, "sleep_h", "h", 1);
  renderWeight();
  lineChart($("#chart-bodyfat"), days, "body_fat_pct", "%", 1);

  $("#history-body").innerHTML = [...days]
    .reverse()
    .map(
      (d) => `<tr class="${d.entry_count || d.active_min || d.has_note || ["steps", "sleep_min", "mood", "weight_kg", "body_fat_pct"].some((k) => d[k] != null) ? "" : "nodata"}">
      <td class="dow">${weekdayShort.format(parseISO(d.day))}</td>
      <td><a href="#/day/${d.day}">${fmtDay(d.day)}</a>${d.has_note ? `<span class="note-flag" title="Has a note">📝</span>` : ""}</td>
      <td class="n">${fmt(d.kcal)}</td>
      ${MACROS.map((m) => `<td class="n">${fmt(d[m.key])}</td>`).join("")}
      <td class="n">${fmt(d.burned_kcal)}</td><td class="n">${fmt(d.active_min)}</td>
      <td class="n">${fmt(d.steps)}</td><td class="n">${fmtSleep(d.sleep_min)}</td>
      <td class="n">${d.weight_kg != null ? fmt(d.weight_kg, 1) : "–"}</td><td class="n">${d.body_fat_pct != null ? `${fmt(d.body_fat_pct, 1)} %` : "–"}</td>
      <td>${d.mood != null ? `<span title="${esc(moodLabel(d.mood))}">${MOOD_EMOJI[d.mood]} ${esc(moodLabel(d.mood))}</span>` : ""}</td>
    </tr>`
    )
    .join("");
}

/** Height in meters, or null when it isn't set (no BMI then). */
function heightM() {
  const h = state.profile?.height_cm;
  return h ? h / 100 : null;
}

/** The body weight chart in kg or BMI, and the weight references below it. */
function renderWeight() {
  const days = state.historyDays;
  if (!days) return;
  const h = heightM();
  const bmiRadio = $('input[name="weight-unit"][value="bmi"]');
  bmiRadio.disabled = !h;
  bmiRadio.parentElement.title = h ? "" : "Set your height in Settings to see BMI";
  const unit = h && state.weightUnit === "bmi" ? "bmi" : "kg";
  $(`input[name="weight-unit"][value="${unit}"]`).checked = true;
  $("#weight-h").textContent = unit === "bmi" ? "Body mass index (BMI)" : "Body weight (kg)";
  if (unit === "bmi") {
    const withBmi = days.map((d) => ({ ...d, bmi: d.weight_kg != null ? d.weight_kg / h ** 2 : null }));
    lineChart($("#chart-weight"), withBmi, "bmi", "BMI", 1);
  } else {
    lineChart($("#chart-weight"), days, "weight_kg", "kg", 1);
  }
  renderBodyRefs(unit);
}

/** The weight brackets as a list, in kg or BMI, with the latest weight's highlighted. */
function renderBodyRefs(unit) {
  const box = $("#body-refs");
  const refs = state.bodyRefs, h = heightM();
  if (!refs) return (box.innerHTML = "");
  if (!h) {
    box.innerHTML = `<p class="hint">📐 Weight references are based on BMI, so they need your height: add it in <a href="#/settings">Settings</a>.</p>`;
    return;
  }
  const last = [...state.historyDays].reverse().find((d) => d.weight_kg != null);
  const lastBmi = last ? last.weight_kg / h ** 2 : state.profile.last_weight ? state.profile.last_weight.weight_kg / h ** 2 : null;
  const show = (bmi) => (unit === "bmi" ? fmt(bmi, 1) : `${fmt(bmi * h ** 2, 1)} kg`);
  const range = (b) =>
    b.min_bmi == null ? `under ${show(b.max_bmi)}` : b.max_bmi == null ? `${show(b.min_bmi)} and up` : `${show(b.min_bmi)} – ${show(b.max_bmi)}`;
  const inside = (b) => lastBmi != null && (b.min_bmi == null || lastBmi >= b.min_bmi) && (b.max_bmi == null || lastBmi < b.max_bmi);
  const groupLabel = { male: "men", female: "women", other: "everyone else" }[refs.gender_group];
  box.innerHTML = `
    <table class="refs-table">
      <caption>Weight references <small>${refs.custom ? "your own values" : `defaults for ${groupLabel}`} · <a href="#/settings">edit</a></small></caption>
      <thead><tr><th>Bracket</th><th>Body type</th><th class="n">${unit === "bmi" ? "BMI" : "Weight"}</th></tr></thead>
      <tbody>${refs.brackets
        .map(
          (b) => `<tr class="${inside(b) ? "current" : ""}">
        <td>${esc(b.label)}${inside(b) ? ` <span class="you">← latest</span>` : ""}</td><td>${esc(b.body_type)}</td><td class="n">${range(b)}</td></tr>`
        )
        .join("")}</tbody>
    </table>`;
}

const SVG_NS = "http://www.w3.org/2000/svg";
const chartData = new WeakMap();

/**
 * Single-series bar chart with per-bar hover tooltip. The dashed target line is
 * each day's target (same key), so it steps where a target period changes.
 */
function barChart(el, days, key, unit, digits = 0) {
  chartData.set(el, { days, key, unit, digits, line: false });
  drawChart(el);
}

/** Dots joined by a line, for measurements (weight, body fat) whose axis shouldn't start at 0. */
function lineChart(el, days, key, unit, digits = 1) {
  chartData.set(el, { days, key, unit, digits, line: true });
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
  const { days, key, unit, digits, line } = spec;
  const tgt = (d) => d.targets?.[key] ?? null;
  const W = el.clientWidth, H = el.clientHeight;
  if (!W || !H) return;
  const m = { top: 14, right: 8, bottom: 22, left: 44 };
  const iw = W - m.left - m.right, ih = H - m.top - m.bottom;
  let minV = 0, maxV;
  if (line) {
    // a padded range around the values, in whole steps
    const vals = days.map((d) => d[key]).filter((v) => v != null);
    const lo = vals.length ? Math.min(...vals) : 0, hi = vals.length ? Math.max(...vals) : 1;
    const raw = Math.max(hi - lo, 1) / 4, pow = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((k) => k * pow).find((v) => v >= raw); // round steps
    minV = Math.max(0, Math.floor(lo / step) * step - step);
    maxV = minV + step * Math.max(4, Math.ceil((hi - minV) / step) + 1);
  } else {
    maxV = niceMax(Math.max(...days.map((d) => tgt(d) ?? 0), ...days.map((d) => d[key] ?? 0)) * 1.05);
  }
  const y = (v) => m.top + ih - ((v - minV) / (maxV - minV)) * ih;
  const band = iw / days.length;
  const gap = Math.min(2, band * 0.25);
  const bw = Math.max(1, band - gap);

  let s = `<g class="grid axis">`;
  for (let i = 0; i <= 4; i++) {
    const v = minV + ((maxV - minV) / 4) * i;
    s += `<line x1="${m.left}" x2="${W - m.right}" y1="${y(v)}" y2="${y(v)}"/>`;
    s += `<text x="${m.left - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v, digits)}</text>`;
  }
  s += `</g><g class="axis">`;
  const every = Math.ceil(days.length / Math.max(1, Math.floor(iw / 64)));
  days.forEach((d, i) => {
    if ((days.length - 1 - i) % every) return;
    // MM-DD: the year is the same for nearly every label
    s += `<text x="${m.left + i * band + band / 2}" y="${H - 6}" text-anchor="middle">${d.day.slice(5)}</text>`;
  });
  s += `</g><g>`;
  if (line) {
    const pts = days.map((d, i) => [d[key], m.left + i * band + band / 2]).filter(([v]) => v != null);
    if (pts.length > 1) s += `<path class="line" d="${pts.map(([v, x], j) => `${j ? "L" : "M"}${x},${y(v)}`).join("")}"/>`;
  }
  days.forEach((d, i) => {
    const v = d[key];
    if (line) {
      if (v != null) s += `<circle class="dot" data-i="${i}" cx="${m.left + i * band + band / 2}" cy="${y(v)}" r="3.5"/>`;
      return;
    }
    if (!v) return;
    const x = m.left + i * band + gap / 2, top = y(v), h = m.top + ih - top;
    const r = Math.min(4, bw / 2, h);
    // rounded data-end, square baseline
    s += `<path class="bar" data-i="${i}" d="M${x},${m.top + ih}V${top + r}Q${x},${top} ${x + r},${top}H${x + bw - r}Q${x + bw},${top} ${x + bw},${top + r}V${m.top + ih}Z"/>`;
  });
  s += `</g>`;
  // target: one horizontal segment per run of days with the same value
  let path = "";
  let prev = null;
  days.forEach((d, i) => {
    const v = tgt(d);
    const x0 = m.left + i * band, x1 = x0 + band;
    if (v == null) {
      // no target that day: the line breaks
    } else if (prev == null) path += `M${x0},${y(v)}H${x1}`;
    else if (prev === v) path += `H${x1}`;
    else path += `V${y(v)}H${x1}`; // step to the new period's value
    prev = v;
  });
  if (path) {
    s += `<path class="target" fill="none" d="${path}"/>`;
    const last = tgt(days[days.length - 1]);
    if (last != null) s += `<text class="target-lbl" x="${W - m.right}" y="${y(last) - 5}" text-anchor="end">target ${fmt(last, digits)}</text>`;
  }
  if (!days.some((d) => d[key] != null && d[key] !== 0)) {
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
    $$(".bar.hot, .dot.hot", svg).forEach((b) => b.classList.remove("hot"));
    if (!hit) return (tip.hidden = true);
    const i = Number(hit.dataset.i);
    const d = days[i];
    $(`.bar[data-i="${i}"], .dot[data-i="${i}"]`, svg)?.classList.add("hot");
    const v = d[key];
    const target = tgt(d);
    tip.innerHTML = `<b>${fmtDayWd(d.day)}</b>${fmt(v, digits)} ${unit}${target && v != null ? ` · ${fmt((v / target) * 100)}% of target ${fmt(target, digits)}` : ""}`;
    tip.hidden = false;
    const tw = tip.offsetWidth;
    tip.style.left = `${Math.min(e.clientX + 12, window.innerWidth - tw - 8)}px`;
    tip.style.top = `${e.clientY + 14}px`;
  });
  svg.addEventListener("mouseleave", () => {
    tip.hidden = true;
    $$(".bar.hot, .dot.hot", svg).forEach((b) => b.classList.remove("hot"));
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
  const { profile, meals } = state.config;
  const today = todayISO();
  const tgt = state.targets
    .map((t) => {
      const v = targetOn(t.periods, today);
      const shown = v == null ? "—" : t.key === "sleep_h" ? `${v} h` : `${fmt(v)} ${t.unit === "kcal" || t.unit === "steps" ? "" : t.unit}`;
      return `<tr><td>${TARGET_EMOJI[t.key] ?? ""} ${esc(t.label)}</td><td class="n">${shown}</td></tr>`;
    })
    .join("");
  $("#help-settings").innerHTML = `
    <dl class="help-dl">
      <dt>⚖️ Body weight</dt><dd>${
        state.profile.last_weight
          ? `${fmt(state.profile.last_weight.weight_kg, 1)} kg, logged ${fmtDay(state.profile.last_weight.day)}`
          : `${fmtQty(profile.weight_kg)} kg, from <code>info/config.toml</code> until you log a weigh-in`
      }</dd>
      <dt>📏 Height</dt><dd>${state.profile.height_cm != null ? `${fmt(state.profile.height_cm, 1)} cm` : "not set"}, in <a href="#/settings">Settings</a></dd>
      <dt>🍽️ Meals</dt><dd>${meals.names.map(esc).join(", ")}</dd>
      <dt>🏃 Exercise types</dt><dd>${state.activityTypes.length}, in <a href="#/settings">Settings</a></dd>
    </dl>
    <h3>🎯 Today's targets</h3>
    <table class="help-table"><tbody>${tgt}</tbody></table>
    <p>Change them in <a href="#/settings">Settings</a>.</p>`;
}

// --- help index ----------------------------------------------------------------

/** Index links scroll within the Help tab (a plain #anchor would change the route),
 * and the section being read is marked in the index. */
let markHelpIndex = () => {};

function wireHelpIndex() {
  const links = $$(".help-index a[data-jump]");
  $(".help-index").addEventListener("click", (e) => {
    const a = e.target.closest("a[data-jump]");
    if (!a) return;
    e.preventDefault();
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    // A section near the end can't scroll up to the top, so the scroll position alone
    // would mark a later entry: keep the clicked one marked until the jump has landed.
    jumping = true;
    setCurrent(a.dataset.jump);
    clearTimeout(jumpTimer);
    jumpTimer = setTimeout(() => (jumping = false), 1500); // in case no scrollend comes
    document.getElementById(a.dataset.jump).scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  });
  let jumping = false, jumpTimer;
  addEventListener("scrollend", () => (jumping = false));
  const setCurrent = (id) => {
    for (const a of links) {
      if (a.dataset.jump === id) a.setAttribute("aria-current", "location");
      else a.removeAttribute("aria-current");
    }
  };
  const ids = links.map((a) => a.dataset.jump);
  const targets = ids.map((id) => document.getElementById(id));
  const mark = () => {
    if (state.view !== "help" || jumping) return;
    // The last section whose top has scrolled past the upper third of the window.
    const line = innerHeight / 3;
    let current = ids[0];
    for (const [i, el] of targets.entries()) if (el.getBoundingClientRect().top <= line) current = ids[i];
    if (scrollY > 0 && innerHeight + scrollY >= document.documentElement.scrollHeight - 2) current = ids.at(-1);
    setCurrent(current);
  };
  addEventListener("scroll", mark, { passive: true });
  markHelpIndex = () => requestAnimationFrame(mark); // also on a direct load of #/help
}

// --- light / dark mode -------------------------------------------------------------

/** The theme on screen: the one picked with the toggle, else the system's. */
function currentTheme() {
  return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}

function labelThemeButton() {
  const label = currentTheme() === "dark" ? "Switch to light mode" : "Switch to dark mode";
  $("#theme-btn").title = label;
  $("#theme-btn").setAttribute("aria-label", label);
}

function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem("pamela-theme", next); // only a per-browser preference
  } catch {}
  labelThemeButton(); // everything else, charts included, is drawn with CSS variables
}

// --- deleting: one day, or whole kinds of data (Danger Zone) ----------------------

/** Lets saves in progress (and a note being typed) land first, so none of them
 * recreates what's about to be deleted. With ``dropNote``, unsaved note typing is discarded. */
async function settleSaves(dropNote = false) {
  if (dropNote) {
    clearTimeout(noteTimer);
    notePending = null;
  }
  document.activeElement?.blur?.();
  if (!dropNote) flushNote();
  while (inFlight.size) await Promise.allSettled([...inFlight]);
}

async function clearDay() {
  const d = state.dayData;
  if (!d) return;
  const m = d.metrics;
  const parts = [];
  if (d.entries.length) parts.push(`${d.entries.length} food entr${d.entries.length === 1 ? "y" : "ies"}`);
  if (d.activities.length) parts.push(`${d.activities.length} activit${d.activities.length === 1 ? "y" : "ies"}`);
  if (["steps", "sleep_min", "mood", "weight_kg", "body_fat_pct"].some((k) => m[k] != null) || m.feelings?.length) parts.push("the check-in");
  if (d.note || $("#notes-input").value.trim()) parts.push("the note");
  if (!parts.length) return toast("Nothing is logged on this day");
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}` : parts[0];
  if (!confirm(`Clear ${fmtDayWd(d.day)}?\n\nThis deletes ${list}, as if the day had never been filled in. It can't be undone.`)) return;
  const day = d.day;
  try {
    await settleSaves(true);
    await api("DELETE", `/days/${day}`);
    resetActivityForm();
    await loadDay();
    toast(`${fmtDayWd(day)} cleared`);
  } catch (err) {
    showError(err);
  }
}

function buildWipeList() {
  $("#wipe-list").innerHTML = state.vocab.wipe_targets
    .map((t) => `<label class="wipe-item"><input type="checkbox" name="what" value="${t.key}"><span><b>${esc(t.label)}</b><small>${esc(t.hint)}</small></span></label>`)
    .join("");
}

/** Keeps "Select all" (checked, unchecked or in between) and the button in step. */
function updateWipeForm() {
  const boxes = $$('#wipe-list input[name="what"]');
  const n = boxes.filter((b) => b.checked).length;
  const all = $("#wipe-all");
  all.checked = n === boxes.length;
  all.indeterminate = n > 0 && n < boxes.length;
  const btn = $("#wipe-btn");
  btn.disabled = !n;
  btn.textContent = n === boxes.length ? "Delete everything…" : n ? `Delete ${n} selected…` : "Delete selected…";
}

function wipeSelection() {
  return $$('#wipe-list input[name="what"]').filter((b) => b.checked).map((b) => b.value);
}

function openWipeDialog() {
  const what = wipeSelection();
  if (!what.length) return;
  const everything = what.length === state.vocab.wipe_targets.length;
  $("#wipe-sum").innerHTML = state.vocab.wipe_targets
    .filter((t) => what.includes(t.key))
    .map((t) => `<li><b>${esc(t.label)}</b>: ${esc(t.hint)}</li>`)
    .join("");
  $("#wipe-alert").hidden = !everything;
  $("#wipe-phrase").textContent = everything ? "delete all" : "delete";
  $("#wipe-input").value = "";
  $("#wipe-confirm").disabled = true;
  $("#wipe-confirm").textContent = everything ? "Delete everything" : "Delete";
  $("#wipe-dialog").classList.toggle("everything", everything);
  $("#wipe-dialog").showModal();
  $("#wipe-input").focus();
}

function wipeTyped() {
  return $("#wipe-input").value.trim().toLowerCase() === $("#wipe-phrase").textContent;
}

async function runWipe() {
  const what = wipeSelection();
  if (!what.length || !wipeTyped()) return;
  const btn = $("#wipe-confirm");
  btn.disabled = true;
  try {
    await settleSaves(true);
    const { counts } = await api("POST", "/wipe", { what });
    $("#wipe-dialog").close();
    for (const b of $$('#wipe-list input[name="what"]')) b.checked = false;
    updateWipeForm();
    if (what.includes("foods")) state.draft = null; // its foods are gone
    state.foods = [];
    state.groceries = null;
    if (what.includes("foods") || what.includes("groceries")) resetCartForm();
    await loadSavedMeals().catch(() => {});
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    toast(`Deleted ${fmt(total)} item${total === 1 ? "" : "s"}`);
  } catch (err) {
    btn.disabled = false;
    showError(err);
  }
}

// --- exit ("Save & close") ------------------------------------------------------

function openExitDialog() {
  const notes = [];
  if (state.draft) notes.push(`The saved-meal draft “${state.draft.name}” isn't logged yet and will be discarded.`);
  $("#exit-warn").textContent = notes.join(" ");
  $("#exit-warn").hidden = !notes.length;
  $("#exit-dialog").showModal();
}

async function saveAndClose() {
  const btn = $("#exit-confirm");
  btn.disabled = true;
  btn.textContent = "Saving…";
  // Blurring fires "change" on a field still being typed in (steps, weight…), so it saves too.
  document.activeElement?.blur?.();
  flushNote();
  try {
    // A save can start another (e.g. a reload after it), so wait until nothing is left.
    while (inFlight.size) await Promise.allSettled([...inFlight]);
    await api("POST", "/shutdown");
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Save & close";
    $("#exit-dialog").close();
    return showError(err.status ? err : new Error("Couldn't reach Pamela's server. Is it still running?"));
  }
  $("#exit-dialog").close();
  document.title = "Pamela · closed";
  document.body.innerHTML = `
    <main class="closed">
      <div class="card closed-card">
        <img src="/static/pamela.svg" alt="" width="72" height="72">
        <h1>👋 Pamela is closed</h1>
        <p>Everything is saved and the server has stopped.</p>
        <p class="hint">You can close this tab. To open Pamela again, run <code>make serve</code>.</p>
      </div>
    </main>`;
  // Browsers only let a page close a tab that a script opened; otherwise this does nothing.
  window.close();
}

// --- wiring ------------------------------------------------------------------

function wire() {
  window.addEventListener("hashchange", route);
  $("#exit-btn").addEventListener("click", openExitDialog);
  $("#theme-btn").addEventListener("click", toggleTheme);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => labelThemeButton());
  labelThemeButton();
  $("#exit-cancel").addEventListener("click", () => $("#exit-dialog").close());
  $("#exit-confirm").addEventListener("click", saveAndClose);
  wireHelpIndex();

  // top bar
  $("#prev-day").addEventListener("click", () => goDay(addDays(state.day, -1)));
  $("#next-day").addEventListener("click", () => goDay(addDays(state.day, 1)));
  $("#today-btn").addEventListener("click", () => goDay(todayISO()));
  $("#day-btn").addEventListener("click", openDayPicker);
  $("#day-input").addEventListener("change", (e) => {
    const v = e.target.value;
    if (!v) return;
    if (v > todayISO()) {
      toast("Days in the future can't be opened yet", true);
      e.target.value = state.day;
      return;
    }
    goDay(v);
  });
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target.closest("input, select, textarea")) return;
    if (e.key === "?") location.hash = "#/help";
    if (state.view !== "day") return;
    if (e.key === "[") goDay(addDays(state.day, -1));
    if (e.key === "]") goDay(addDays(state.day, 1)); // ignored on today
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
  $("#steps-input").addEventListener("change", () => commitUnlessAdding("steps", commitSteps));
  $("#sleep-input").addEventListener("change", () => commitUnlessAdding("sleep", commitSleep));
  for (const btn of $$("[data-add]")) {
    const which = btn.dataset.add;
    const commit = which === "steps" ? commitSteps : commitSleep;
    // keep the focus in the field, so clicking "+" doesn't first save the value as the total
    btn.addEventListener("mousedown", (e) => e.preventDefault());
    btn.addEventListener("click", () => addToMetric(which));
    // tabbed to "+" and then away without pressing it: save as a normal edit
    btn.addEventListener("blur", (e) => e.relatedTarget !== $(`#${which}-input`) && commit());
  }
  $("#weight-input").addEventListener("change", (e) =>
    commitBody(e.target, "weight_kg", 0, 500, "Weight: type kilograms, like 72.5")
  );
  $("#bodyfat-input").addEventListener("change", (e) =>
    commitBody(e.target, "body_fat_pct", 0, 99.9, "Body fat: type a percentage, like 18.5")
  );
  for (const id of ["#steps-input", "#sleep-input", "#weight-input", "#bodyfat-input"]) {
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

  // notes
  $("#notes-input").addEventListener("input", noteTyped);
  $("#notes-input").addEventListener("change", flushNote);
  window.addEventListener("pagehide", flushNote);

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
  $("#act-cancel").addEventListener("click", resetActivityForm);
  $("#clear-day").addEventListener("click", clearDay);

  // Danger Zone (its checkboxes come with the vocabulary: buildVocabControls)
  $("#wipe-list").addEventListener("change", updateWipeForm);
  $("#wipe-all").addEventListener("change", (e) => {
    for (const b of $$('#wipe-list input[name="what"]')) b.checked = e.target.checked;
    updateWipeForm();
  });
  $("#wipe-form").addEventListener("submit", (e) => {
    e.preventDefault();
    openWipeDialog();
  });
  $("#wipe-input").addEventListener("input", () => ($("#wipe-confirm").disabled = !wipeTyped()));
  $("#wipe-dialog-form").addEventListener("submit", (e) => {
    e.preventDefault(); // stay open until the delete is done
    runWipe();
  });
  $("#wipe-cancel").addEventListener("click", () => $("#wipe-dialog").close());
  $("#comfort-stars").addEventListener("click", (e) => {
    const star = e.target.closest("[data-star]");
    if (!star) return;
    const input = $("#activity-form").elements.comfort;
    input.value = input.value === star.dataset.star ? "" : star.dataset.star;
    renderComfortStars();
  });
  renderComfortStars();
  // the reminder shows up at 9 PM (and goes at midnight) without a reload
  setInterval(updateStepsReminder, 60_000);
  $("#act-list").addEventListener("click", async (e) => {
    const edit = e.target.closest("[data-edit-activity]");
    if (edit) return editActivity(Number(edit.dataset.editActivity));
    const del = e.target.closest("[data-del-activity]");
    if (!del) return;
    try {
      await api("DELETE", `/activities/${del.dataset.delActivity}`);
      if (state.editingActivityId === Number(del.dataset.delActivity)) resetActivityForm();
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
    // A diet implies the broader ones (vegan -> vegetarian -> pescatarian and
    // ovolactovegetarian): checking one checks those, unchecking one unchecks the
    // stricter ones.
    const implies = state.vocab.diet_implies;
    if (!(e.target.name in implies) && !Object.values(implies).flat().includes(e.target.name)) return;
    const el = foodForm.elements;
    if (e.target.checked) {
      const todo = [e.target.name];
      while (todo.length) {
        for (const t of implies[todo.pop()] ?? []) {
          el[t].checked = true;
          todo.push(t);
        }
      }
    } else {
      for (let changed = true; changed; ) {
        changed = false;
        for (const [strict, broader] of Object.entries(implies)) {
          if (el[strict].checked && !broader.every((b) => el[b].checked)) {
            el[strict].checked = false;
            changed = true;
          }
        }
      }
    }
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
  $("#group-filter").addEventListener("change", renderFoods);
  $("#ean-status").addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit-food]");
    if (edit) editFood(Number(edit.dataset.editFood));
  });
  $("#tag-filter").addEventListener("click", (e) => {
    const chip = e.target.closest("[data-tag]");
    if (!chip) return;
    const on = !state.foodTagFilter.has(chip.dataset.tag);
    if (on) state.foodTagFilter.add(chip.dataset.tag);
    else state.foodTagFilter.delete(chip.dataset.tag);
    chip.setAttribute("aria-pressed", String(on));
    renderFoods();
  });
  $("#food-saved").addEventListener("click", (e) => {
    const go = e.target.closest("[data-goto-food]");
    if (go) goToFood(Number(go.dataset.gotoFood));
  });
  const hideBtn = $("#hide-tags");
  hideBtn.setAttribute("aria-pressed", String(state.hideTags));
  hideBtn.addEventListener("click", () => {
    state.hideTags = !state.hideTags;
    prefSet("pamela-hide-tags", state.hideTags ? "1" : "0");
    hideBtn.setAttribute("aria-pressed", String(state.hideTags));
    $("#foods-groups").classList.toggle("hide-tags", state.hideTags);
  });
  $("#foods-groups").addEventListener("click", (e) => {
    const sort = e.target.closest("[data-sort]");
    if (sort) return sortFoodsBy(sort.dataset.sort);
    const edit = e.target.closest("[data-edit-food]");
    if (edit) return editFood(Number(edit.dataset.editFood));
    const del = e.target.closest("[data-del-food]");
    if (del) deleteFood(Number(del.dataset.delFood));
  });

  // groceries
  foodCombo({
    input: $("#trip-search"),
    list: $("#trip-suggest"),
    onPick: (f) => {
      $("#trip-search").value = "";
      addTripItem(f);
    },
  });
  $("#trip-form").addEventListener("submit", submitTrip);
  $("#trip-day").addEventListener("change", renderTrip); // expiry dates can't be before it
  $("#trip-body").addEventListener("input", tripInput);
  $("#trip-body").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.closest("input")) {
      e.preventDefault(); // Enter in a row moves on to the next food instead of submitting
      $("#trip-search").focus();
    }
  });
  $("#trip-body").addEventListener("click", (e) => {
    const del = e.target.closest("[data-trip-del]");
    if (!del) return;
    const it = state.trip[Number(del.dataset.tripDel)];
    if (it.used > 1e-6 && !confirm(`Remove ${it.food.name} from this cart? ${fmtQty(it.used)} ${it.food.unit} of it was already eaten or thrown out; those meals will take it from other carts, if there's any.`)) return;
    state.trip.splice(Number(del.dataset.tripDel), 1);
    renderTrip();
  });
  $("#cart-cancel").addEventListener("click", resetCartForm);
  $("#extra-add").addEventListener("click", addExtra);
  $("#extra-body").addEventListener("input", extraInput);
  $("#extra-body").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.closest("input")) e.preventDefault();
  });
  $("#extra-body").addEventListener("click", (e) => {
    const del = e.target.closest("[data-extra-del]");
    if (!del) return;
    state.tripExtras.splice(Number(del.dataset.extraDel), 1);
    renderTrip();
  });
  $("#trip-discount").addEventListener("input", renderTripTotal);
  $("#trip-fee").addEventListener("input", renderTripTotal);
  $("#trip-fee").addEventListener("keydown", (e) => e.key === "Enter" && e.preventDefault());
  $("#trip-discount").addEventListener("keydown", (e) => e.key === "Enter" && e.preventDefault());
  $("#cart-delete").addEventListener("click", () => deleteCart(state.editingCartId));
  $("#stock-filter").addEventListener("input", () => renderGroceries());
  for (const r of $$('input[name="stock-sort"]')) r.addEventListener("change", () => renderGroceries());
  $("#view-groceries").addEventListener("click", (e) => {
    const t = e.target.closest("[data-buy-again], [data-expire-lot], [data-edit-cart], [data-del-cart], [data-undo-expired], [data-more-carts]");
    if (!t) return;
    const d = t.dataset;
    if (d.buyAgain) buyAgain(Number(d.buyAgain));
    else if (d.expireLot) openExpire(Number(d.expireLot));
    else if (d.editCart) editCart(Number(d.editCart));
    else if (d.delCart) deleteCart(Number(d.delCart));
    else if (d.undoExpired) undoExpired(Number(d.undoExpired));
    else if ("moreCarts" in d) {
      state.cartsShown += CARTS_PAGE;
      renderCarts();
    }
  });
  $("#expire-form").addEventListener("submit", submitExpire);
  $("#expire-cancel").addEventListener("click", () => $("#expire-dialog").close());

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
  wireTargets();
  $("#profile-form").addEventListener("submit", submitProfile);
  const refsForm = $("#refs-form");
  refsForm.addEventListener("input", checkRefs);
  refsForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const vals = checkRefs();
    if (vals) saveRefs(vals);
  });
  refsForm.addEventListener("click", (e) => {
    const preset = e.target.closest("[data-refs-preset]");
    if (preset) renderRefsForm(state.bodyRefs.defaults[preset.dataset.refsPreset]);
  });
  $("#refs-reset").addEventListener("click", () => saveRefs(null));
  $("#at-form").addEventListener("submit", submitType);
  $("#at-form").elements.met.addEventListener("input", updateTypeHint);
  $("#at-form").elements.category.addEventListener("input", updateTypeEmojiPlaceholder);
  $("#at-cancel").addEventListener("click", resetTypeForm);
  $("#at-filter").addEventListener("input", renderTypes);
  $("#at-body").addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit-type]");
    if (edit) return editType(Number(edit.dataset.editType));
    const del = e.target.closest("[data-del-type]");
    if (del) deleteType(Number(del.dataset.delType));
  });

  // history
  for (const r of $$('input[name="weight-unit"]')) {
    r.addEventListener("change", () => {
      state.weightUnit = r.value;
      prefSet("pamela-weight-unit", r.value);
      renderWeight();
    });
  }
  for (const r of $$('input[name="range"]')) {
    r.addEventListener("change", () => {
      state.historyRange = Number(r.value);
      loadHistory();
    });
  }
  const ro = new ResizeObserver((entries) => entries.forEach((en) => drawChart(en.target)));
  for (const id of ["#chart-kcal", "#chart-protein", "#chart-steps", "#chart-sleep", "#chart-weight", "#chart-bodyfat"]) {
    ro.observe($(id));
  }

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
    [state.vocab] = await Promise.all([api("GET", "/vocab"), loadActivityTypes(), loadSavedMeals(), loadTargets(), loadProfile()]);
  } catch (err) {
    return showError(err);
  }
  buildVocabControls();
  $("#profile-gender").innerHTML = state.vocab.genders.map((g) => `<option value="${g.key}">${esc(g.label)}</option>`).join("");
  fillConfigControls();
  updateFormUnit();
  route();
}

init();
