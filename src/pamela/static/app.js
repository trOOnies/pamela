// Pamela frontend - vanilla JS, no build step.
// Views are routed by URL hash: #/ (today), #/day/YYYY-MM-DD, #/foods, #/history

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const MACROS = [
  { key: "protein_g", label: "Protein", short: "P", color: "var(--c-protein)" },
  { key: "carbs_g", label: "Carbs", short: "C", color: "var(--c-carbs)" },
  { key: "fat_g", label: "Fat", short: "F", color: "var(--c-fat)" },
  { key: "fiber_g", label: "Fiber", short: "Fib", color: "var(--c-fiber)" },
];

const state = {
  config: null,
  view: "day",
  day: todayISO(),
  dayData: null,
  foods: [],          // full catalog (Foods view)
  editingFoodId: null,
  suggestions: [],    // combobox results
  activeSuggestion: -1,
  selectedFood: null, // food chosen in the entry form
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
      msg = data.detail.map((e) => `${(e.loc || []).filter((l) => l !== "body").join(".")}: ${e.msg}`).join("\n");
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

// --- config ------------------------------------------------------------------

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

function fillConfigControls() {
  const cfg = state.config;
  const mealSel = $("#entry-meal");
  const prevMeal = mealSel.value;
  mealSel.innerHTML = cfg.meals.names.map((m) => `<option>${esc(m)}</option>`).join("");
  if (cfg.meals.names.includes(prevMeal)) mealSel.value = prevMeal;
  else mealSel.value = defaultMeal();

  const typeSel = $("#act-type");
  const prevType = typeSel.value;
  typeSel.innerHTML = cfg.activity_types.map((t) => `<option>${esc(t.name)}</option>`).join("");
  if (cfg.activity_types.some((t) => t.name === prevType)) typeSel.value = prevType;
  updateActivityForm();
}

/** Guess the meal from the time of day, spreading configured meals over 06:00-22:00. */
function defaultMeal() {
  const names = state.config.meals.names;
  if (state.day !== todayISO()) return names[0];
  const h = new Date().getHours() + new Date().getMinutes() / 60;
  const frac = Math.min(Math.max((h - 6) / 16, 0), 0.999);
  return names[Math.floor(frac * names.length)];
}

// --- routing -----------------------------------------------------------------

function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  let view = parts[0] || "day";
  if (!["day", "foods", "history"].includes(view)) view = "day";
  state.view = view;
  if (view === "day") {
    const d = parts[1];
    state.day = d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : todayISO();
  }
  for (const v of ["day", "foods", "history"]) $(`#view-${v}`).hidden = v !== view;
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
  if (state.view === "history") return loadHistory();
}

function goDay(iso) {
  location.hash = iso === todayISO() ? "#/" : `#/day/${iso}`;
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
    renderActivities();
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
    html += `<tr class="meal-head"><td>${esc(meal)}</td><td class="n">${
      canAdd ? `<button type="button" class="row-btn add-to" data-add-meal="${esc(meal)}">+ add</button>` : ""
    }</td>${rows.length ? macroCells(sub) : '<td colspan="5"></td>'}<td></td></tr>`;
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

// entry form -------------------------------------------------------------------

function entryMode() {
  return $('input[name="entry-mode"]:checked').value;
}

function setEntryMode(mode) {
  $(`input[name="entry-mode"][value="${mode}"]`).checked = true;
  $("#entry-form").classList.toggle("quick", mode === "quick");
}

function updatePreview() {
  const f = state.selectedFood;
  const qty = num($("#entry-qty").value);
  $("#entry-unit").textContent = f ? f.unit : "g";
  if (!f) {
    $("#entry-preview").textContent = "";
    return;
  }
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
  $("#entry-qty").value = food.basis_qty;
  closeSuggest();
  updatePreview();
  $("#entry-qty").focus();
  $("#entry-qty").select();
}

function closeSuggest() {
  $("#food-suggest").hidden = true;
  $("#food-search").setAttribute("aria-expanded", "false");
  $("#food-search").removeAttribute("aria-activedescendant");
  state.activeSuggestion = -1;
}

function renderSuggest() {
  const list = $("#food-suggest");
  const q = $("#food-search").value.trim();
  let html = state.suggestions
    .map(
      (f, i) => `<li role="option" id="sugg-${i}" data-i="${i}" aria-selected="${i === state.activeSuggestion}">
        <span>${esc(f.name)} ${f.brand ? `<span class="brand-tag">${esc(f.brand)}</span>` : ""}</span>
        <span class="meta">${fmt(f.kcal)} kcal / ${fmtQty(f.basis_qty)} ${esc(f.unit)}</span></li>`
    )
    .join("");
  if (q) {
    html += `<li role="option" class="create" data-create="1" id="sugg-create" aria-selected="${state.activeSuggestion === state.suggestions.length}">
      <span>+ Create “${esc(q)}” in Foods</span></li>`;
  }
  list.innerHTML = html;
  list.hidden = !html;
  $("#food-search").setAttribute("aria-expanded", String(!!html));
  const active = state.activeSuggestion >= 0 ? $(`[aria-selected="true"]`, list) : null;
  if (active) {
    $("#food-search").setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  } else {
    $("#food-search").removeAttribute("aria-activedescendant");
  }
}

let suggestSeq = 0;
const searchFoods = debounce(async () => {
  const q = $("#food-search").value.trim();
  const seq = ++suggestSeq;
  try {
    const foods = await api("GET", `/foods?limit=12&q=${encodeURIComponent(q)}`);
    if (seq !== suggestSeq) return;
    state.suggestions = foods;
    state.activeSuggestion = foods.length ? 0 : -1;
    if (document.activeElement === $("#food-search")) renderSuggest();
  } catch (err) {
    showError(err);
  }
}, 120);

function pickSuggestion(i) {
  if (i < 0) return;
  if (i >= state.suggestions.length) {
    // "create" option: jump to the Foods view with the name prefilled
    const name = $("#food-search").value.trim();
    closeSuggest();
    location.hash = "#/foods";
    resetFoodForm();
    $("#food-form").elements.name.value = name;
    $("#food-form").elements.basis_qty.focus();
    return;
  }
  selectFood(state.suggestions[i]);
}

async function submitEntry(ev) {
  ev.preventDefault();
  const form = ev.currentTarget;
  const v = formValues(form);
  let body = { day: state.day, meal: v.meal };
  if (entryMode() === "catalog") {
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
    if (entryMode() === "catalog") {
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

// activity form ---------------------------------------------------------------

function currentActivityType() {
  const name = $("#act-type").value;
  return state.config.activity_types.find((t) => t.name === name);
}

function updateActivityForm() {
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
  } catch (err) {
    showError(err);
  }
}

// --- foods view --------------------------------------------------------------

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
  const rows = state.foods.filter((f) => {
    const hay = `${f.name} ${f.brand}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
  $("#foods-count").textContent = rows.length === state.foods.length ? `(${rows.length})` : `(${rows.length} of ${state.foods.length})`;
  $("#foods-body").innerHTML = rows.length
    ? rows
        .map(
          (f) => `<tr class="${f.id === state.editingFoodId ? "editing" : ""}">
      <td>${esc(f.name)}</td><td>${esc(f.brand)}</td>
      <td class="n">${fmtQty(f.basis_qty)} ${esc(f.unit)}</td>
      ${macroCells(f)}
      <td class="n">${f.uses}</td>
      <td class="act"><button type="button" class="row-btn" data-edit-food="${f.id}">Edit</button><button type="button" class="row-btn del" data-del-food="${f.id}" aria-label="Delete ${esc(f.name)}">✕</button></td>
    </tr>`
        )
        .join("")
    : `<tr class="empty"><td colspan="10">${state.foods.length ? "No matches" : "No foods yet - add your first one with the form."}</td></tr>`;
}

function resetFoodForm() {
  const form = $("#food-form");
  form.reset();
  state.editingFoodId = null;
  $("#food-form-h").textContent = "New food";
  $("#food-submit").textContent = "Save food";
  $("#food-cancel").hidden = true;
  updateKcalHint();
  renderFoods();
}

function editFood(id) {
  const f = state.foods.find((x) => x.id === id);
  if (!f) return;
  state.editingFoodId = id;
  const form = $("#food-form");
  for (const k of ["name", "brand", "basis_qty", "unit", "kcal", ...MACROS.map((m) => m.key)]) form.elements[k].value = f[k];
  $("#food-form-h").textContent = "Edit food";
  $("#food-submit").textContent = "Update food";
  $("#food-cancel").hidden = false;
  updateKcalHint();
  renderFoods();
  form.elements.name.focus();
}

/** Compares entered kcal with 4/4/9 kcal per gram of protein/carbs/fat. */
function updateKcalHint() {
  const el = $("#food-form").elements;
  const p = num(el.protein_g.value) ?? 0, c = num(el.carbs_g.value) ?? 0, f = num(el.fat_g.value) ?? 0;
  const est = p * 4 + c * 4 + f * 9;
  $("#food-kcal-hint").textContent = est ? `Macros add up to ≈ ${fmt(est)} kcal` : "";
}

async function submitFood(ev) {
  ev.preventDefault();
  const v = formValues(ev.currentTarget);
  const body = {
    name: v.name.trim(),
    brand: v.brand.trim(),
    basis_qty: num(v.basis_qty),
    unit: v.unit.trim(),
    kcal: num(v.kcal) ?? 0,
  };
  for (const m of MACROS) body[m.key] = num(v[m.key]) ?? 0;
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
    $("#food-form").elements.name.focus();
  } catch (err) {
    showError(err);
  }
}

async function deleteFood(id) {
  const f = state.foods.find((x) => x.id === id);
  if (!f || !confirm(`Delete “${f.name}”? Past log entries keep their values.`)) return;
  try {
    await api("DELETE", `/foods/${id}`);
    if (state.editingFoodId === id) resetFoodForm();
    await loadFoods();
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
    renderHistory(days);
  } catch (err) {
    showError(err);
  }
}

function renderHistory(days) {
  const logged = days.filter((d) => d.entry_count > 0);
  const avg = (key, list = logged) => (list.length ? list.reduce((s, d) => s + d[key], 0) / list.length : null);
  const t = state.config.targets;
  const activeDays = days.filter((d) => d.active_min > 0).length;
  $("#history-tiles").innerHTML = [
    ["Avg kcal / logged day", fmt(avg("kcal")), t.kcal ? `target ${fmt(t.kcal)}` : ""],
    ["Avg protein", `${fmt(avg("protein_g"))} g`, t.protein_g ? `target ${fmt(t.protein_g)} g` : ""],
    ["Days logged", `${logged.length}`, `of ${days.length}`],
    ["Active days", `${activeDays}`, `of ${days.length}`],
    ["Avg burned / day", fmt(avg("burned_kcal", days)), "kcal"],
  ]
    .map(([k, v, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v} <small>${s}</small></div></div>`)
    .join("");

  barChart($("#chart-kcal"), days, "kcal", t.kcal, "kcal");
  barChart($("#chart-protein"), days, "protein_g", t.protein_g, "g");

  $("#history-body").innerHTML = [...days]
    .reverse()
    .map(
      (d) => `<tr class="${d.entry_count || d.active_min ? "" : "nodata"}">
      <td><a href="#/day/${d.day}">${fmtDay(d.day)}</a></td>
      <td class="n">${fmt(d.kcal)}</td>
      ${MACROS.map((m) => `<td class="n">${fmt(d[m.key])}</td>`).join("")}
      <td class="n">${fmt(d.burned_kcal)}</td><td class="n">${fmt(d.active_min)}</td>
    </tr>`
    )
    .join("");
}

const SVG_NS = "http://www.w3.org/2000/svg";
const chartData = new WeakMap();

/** Single-series bar chart with a dashed target line and per-bar hover tooltip. */
function barChart(el, days, key, target, unit) {
  chartData.set(el, { days, key, target, unit });
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
  const { days, key, target, unit } = spec;
  const W = el.clientWidth, H = el.clientHeight;
  if (!W || !H) return;
  const m = { top: 14, right: 8, bottom: 22, left: 40 };
  const iw = W - m.left - m.right, ih = H - m.top - m.bottom;
  const maxV = niceMax(Math.max(target || 0, ...days.map((d) => d[key])) * 1.05);
  const y = (v) => m.top + ih - (v / maxV) * ih;
  const band = iw / days.length;
  const gap = Math.min(2, band * 0.25);
  const bw = Math.max(1, band - gap);

  let s = `<g class="grid axis">`;
  for (let i = 0; i <= 4; i++) {
    const v = (maxV / 4) * i;
    s += `<line x1="${m.left}" x2="${W - m.right}" y1="${y(v)}" y2="${y(v)}"/>`;
    s += `<text x="${m.left - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`;
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
    s += `<text class="target-lbl" x="${W - m.right}" y="${y(target) - 5}" text-anchor="end">target ${fmt(target)}</text>`;
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
    tip.innerHTML = `<b>${fmtDay(d.day)}</b>${fmt(d[key])} ${unit}${target ? ` · ${fmt((d[key] / target) * 100)}% of target` : ""}`;
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

// --- wiring ------------------------------------------------------------------

function wire() {
  window.addEventListener("hashchange", route);

  // top bar
  $("#prev-day").addEventListener("click", () => goDay(addDays(state.day, -1)));
  $("#next-day").addEventListener("click", () => goDay(addDays(state.day, 1)));
  $("#today-btn").addEventListener("click", () => goDay(todayISO()));
  $("#day-input").addEventListener("change", (e) => e.target.value && goDay(e.target.value));
  document.addEventListener("keydown", (e) => {
    if (state.view !== "day" || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target.closest("input, select, textarea")) return;
    if (e.key === "[") goDay(addDays(state.day, -1));
    if (e.key === "]") goDay(addDays(state.day, 1));
  });

  // entry form
  for (const r of $$('input[name="entry-mode"]')) r.addEventListener("change", () => setEntryMode(entryMode()));
  $("#entry-form").addEventListener("submit", submitEntry);
  $("#entry-qty").addEventListener("input", updatePreview);
  const search = $("#food-search");
  search.addEventListener("input", () => {
    state.selectedFood = null;
    updatePreview();
    searchFoods();
  });
  search.addEventListener("focus", searchFoods);
  search.addEventListener("blur", () => setTimeout(closeSuggest, 150));
  search.addEventListener("keydown", (e) => {
    const n = state.suggestions.length + (search.value.trim() ? 1 : 0);
    if (e.key === "ArrowDown" && n) {
      e.preventDefault();
      state.activeSuggestion = (state.activeSuggestion + 1) % n;
      renderSuggest();
    } else if (e.key === "ArrowUp" && n) {
      e.preventDefault();
      state.activeSuggestion = (state.activeSuggestion - 1 + n) % n;
      renderSuggest();
    } else if (e.key === "Enter") {
      if (!$("#food-suggest").hidden && state.activeSuggestion >= 0) {
        e.preventDefault();
        pickSuggestion(state.activeSuggestion);
      } else if (!state.selectedFood) {
        e.preventDefault();
      }
    } else if (e.key === "Escape") {
      closeSuggest();
    }
  });
  // mousedown (not click) so it fires before the input's blur closes the list
  $("#food-suggest").addEventListener("mousedown", (e) => {
    const li = e.target.closest("li");
    if (!li) return;
    e.preventDefault();
    pickSuggestion(li.dataset.create ? state.suggestions.length : Number(li.dataset.i));
  });

  // log table
  $("#log-body").addEventListener("click", async (e) => {
    const add = e.target.closest("[data-add-meal]");
    if (add) {
      $("#entry-meal").value = add.dataset.addMeal;
      (entryMode() === "catalog" ? $("#food-search") : $("#quick-name")).focus();
      return;
    }
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
  $("#food-form").addEventListener("submit", submitFood);
  $("#food-form").addEventListener("input", updateKcalHint);
  $("#food-cancel").addEventListener("click", resetFoodForm);
  $("#foods-filter").addEventListener("input", renderFoods);
  $("#foods-body").addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit-food]");
    if (edit) return editFood(Number(edit.dataset.editFood));
    const del = e.target.closest("[data-del-food]");
    if (del) deleteFood(Number(del.dataset.delFood));
  });

  // history
  for (const r of $$('input[name="range"]')) {
    r.addEventListener("change", () => {
      state.historyRange = Number(r.value);
      loadHistory();
    });
  }
  const ro = new ResizeObserver((entries) => entries.forEach((en) => drawChart(en.target)));
  ro.observe($("#chart-kcal"));
  ro.observe($("#chart-protein"));

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
  fillConfigControls();
  route();
}

init();
