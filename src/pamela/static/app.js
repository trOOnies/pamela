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
  $("#tag-filter").innerHTML = tags
    .map((t) => `<button type="button" class="chip tag-chip tag-${t.key}" data-tag="${t.key}" aria-pressed="false">${esc(t.label)}</button>`)
    .join("");
}

// --- routing -----------------------------------------------------------------

const VIEWS = ["day", "foods", "meals", "history", "settings", "help"];

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
  renderDayNav();
  document.title = `${fmtDayWd(state.day)} · Pamela`;
  const day = state.day;
  try {
    const data = await api("GET", `/days/${day}`);
    if (day !== state.day) return; // user navigated meanwhile
    state.dayData = data;
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

/** The emoji of a logged activity's type, if that type still exists. */
function activityIcon(name) {
  const t = state.activityTypes.find((x) => x.name.toLowerCase() === name.toLowerCase());
  return t ? `<span class="act-emoji" aria-hidden="true">${t.icon}</span>` : "";
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
        <div><span class="t">${activityIcon(a.type)}${esc(a.type)}</span> <span class="d">${bits.join(" · ")}</span></div>
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
  const t = state.dayData.targets;
  const steps = $("#steps-input"), sleep = $("#sleep-input");
  const weight = $("#weight-input"), fat = $("#bodyfat-input");
  // don't clobber what the user is typing
  if (document.activeElement !== steps) steps.value = m.steps ?? "";
  if (document.activeElement !== sleep) sleep.value = m.sleep_min != null ? fmtSleep(m.sleep_min) : "";
  if (document.activeElement !== weight) weight.value = m.weight_kg ?? "";
  if (document.activeElement !== fat) fat.value = m.body_fat_pct ?? "";
  for (const el of [sleep, weight, fat]) el.classList.remove("invalid");
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
      <td class="act"><button type="button" class="row-btn icon" data-edit-food="${f.id}" title="Edit" aria-label="Edit ${esc(f.name)}">${PENCIL}</button><button type="button" class="row-btn del" data-del-food="${f.id}" aria-label="Delete ${esc(f.name)}">✕</button></td>
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

async function submitProfile(ev) {
  ev.preventDefault();
  const v = formValues(ev.currentTarget);
  try {
    state.profile = await api("PUT", "/profile", { gender: v.gender, height_cm: num(v.height_cm) });
    renderProfile();
    toast("Profile saved");
  } catch (err) {
    showError(err);
  }
}

async function loadSettings() {
  document.title = "Settings · Pamela";
  try {
    await Promise.all([loadActivityTypes(), loadTargets(), loadProfile()]);
    renderProfile();
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
  lineChart($("#chart-weight"), days, "weight_kg", "kg", 1);
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
  wireTargets();
  $("#profile-form").addEventListener("submit", submitProfile);
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
