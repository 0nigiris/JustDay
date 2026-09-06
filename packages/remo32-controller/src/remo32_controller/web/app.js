"use strict";
/* Remo32 — интерфейс.
 *
 * Без сборщика и без фреймворка, одним файлом: страница должна открываться
 * мгновенно на плохой мобильной связи, а править её должно быть можно
 * текстовым редактором. Один файл — ещё и потому, что версия статики
 * подставляется в адрес при выдаче страницы; у отдельных модулей адреса
 * пришлось бы версионировать по одному, и первый же пропущенный дал бы
 * браузеру выполнять старый код рядом с новым.
 *
 * Главный экран — пульт. Это пульт от компьютера, а не панель мониторинга:
 * чаще всего нужно нажать кнопку, а не посмотреть загрузку процессора.
 * Поэтому кнопки крупные и первыми, а характеристики — отдельной вкладкой.
 */

/* ========================================================== мелочи ===== */

const el = (id) => document.getElementById(id);

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const STATE_LABEL = {
  online: "онлайн",
  offline: "выключен",
  unknown: "неизвестно",
  connecting: "подключается",
  error: "ошибка",
};

const fmtBytes = (bytes) => {
  if (bytes == null) return "—";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`;
};

const fmtUptime = (seconds) => {
  if (seconds == null) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d} д ${h} ч`;
  if (h) return `${h} ч ${m} мин`;
  return `${m} мин`;
};

const buzz = (pattern) => navigator.vibrate?.(pattern);

/* ============================================ настройки этого телефона ==

   Избранное и выбранный компьютер — свойства устройства, а не системы: у
   телефона и планшета наборы разные. Поэтому localStorage, а не конфиг.
   Любое обращение обёрнуто: в приватном режиме сам доступ бросает
   исключение, и падать из-за этого интерфейс не должен. */

const store = {
  get(key, fallback = null) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : value;
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* приватный режим — переживём */
    }
  },
  json(key, fallback) {
    try {
      const value = JSON.parse(this.get(key, "null"));
      return value ?? fallback;
    } catch {
      return fallback;
    }
  },
  setJson(key, value) {
    this.set(key, JSON.stringify(value));
  },
};

const KEY_FAV = "remo32.favorites";
const KEY_PC = "remo32.pc";
const KEY_ROUTE = "remo32.route";

/* ============================================================== сеть ==== */

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  let body = null;
  try {
    body = await response.json();
  } catch {
    throw new Error(`сервер вернул не JSON (HTTP ${response.status})`);
  }

  if (response.status === 401) {
    showLogin();
    throw new Error("требуется вход");
  }
  if (!body.ok) {
    const error = new Error(body.error?.message || `HTTP ${response.status}`);
    error.code = body.error?.code;
    error.requestId = body.request_id;
    throw error;
  }
  return body.data;
}

/* ========================================================= состояние ==== */

const state = {
  pcs: [],
  schedules: [],
  esp32: null,
  auth: null,
  form: { open: false, editId: null },
  rendering: false,
};

/* Компьютер, которым сейчас управляет пульт. Если сохранённый исчез из
   конфигурации — берём первый живой, а не показываем пустоту. */
function activePc() {
  const saved = store.get(KEY_PC);
  return (
    state.pcs.find((p) => p.id === saved) ||
    state.pcs.find((p) => p.state === "online") ||
    state.pcs[0] ||
    null
  );
}

/* ==================================================== уведомления ======= */

function toast(message, kind = "", requestId = null) {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.innerHTML =
    esc(message) + (requestId ? `<span class="rid">запрос ${esc(requestId)}</span>` : "");
  el("toasts").append(node);
  setTimeout(() => {
    node.style.opacity = "0";
    setTimeout(() => node.remove(), 250);
  }, kind === "err" ? 6000 : 2600);
}

/* ==================================================== подтверждение =====

   Своё окно вместо confirm(). Системное на телефоне выезжает у верхнего
   края — далеко от пальца, кнопки в нём называются «ОК» и «Отмена», и
   опасное действие ничем не отличается от безобидного. */

let sheetResolve = null;

function confirmSheet({ title, text = "", yes = "Да", icon = "⚠️", danger = true }) {
  el("sheet-icon").textContent = icon;
  el("sheet-title").textContent = title;
  el("sheet-text").textContent = text;
  const yesButton = el("sheet-yes");
  yesButton.textContent = yes;
  yesButton.className = `btn ${danger ? "danger" : "primary"}`;
  el("sheet").hidden = false;
  buzz(10);
  return new Promise((resolve) => {
    sheetResolve = resolve;
  });
}

document.addEventListener("click", (event) => {
  const answer = event.target.closest("[data-sheet]")?.dataset.sheet;
  if (!answer) return;
  el("sheet").hidden = true;
  sheetResolve?.(answer === "yes");
  sheetResolve = null;
});

/* ============================================================== вход ==== */

function showLogin(status = null) {
  el("main").hidden = true;
  el("login").hidden = false;
  if (status) {
    const canPasskey = status.passkey_available && window.PublicKeyCredential;
    el("passkey-btn").hidden = !canPasskey;
    el("login-divider").hidden = !canPasskey || !status.password_enabled;
    el("password-form").hidden = !status.password_enabled;
  }
}

function showMain() {
  el("login").hidden = true;
  el("main").hidden = false;
}

async function refreshAuth() {
  const status = await api("/api/auth/status");
  state.auth = status;
  if (status.authenticated) {
    showMain();
    return true;
  }
  showLogin(status);
  return false;
}

el("password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  el("login-error").textContent = "";
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password: el("password").value }),
    });
    el("password").value = "";
    showMain();
    await start();
  } catch (error) {
    el("login-error").textContent = error.message;
  }
});

/* --- passkey ------------------------------------------------------------ */

const b64urlToBuf = (value) => {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "="));
  return Uint8Array.from(binary, (c) => c.charCodeAt(0));
};

const bufToB64url = (buffer) =>
  btoa(String.fromCharCode(...new Uint8Array(buffer)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");

function serializeAssertion(assertion) {
  return {
    id: assertion.id,
    rawId: bufToB64url(assertion.rawId),
    type: assertion.type,
    response: {
      clientDataJSON: bufToB64url(assertion.response.clientDataJSON),
      authenticatorData: bufToB64url(assertion.response.authenticatorData),
      signature: bufToB64url(assertion.response.signature),
      userHandle: assertion.response.userHandle ? bufToB64url(assertion.response.userHandle) : null,
    },
  };
}

el("passkey-btn").addEventListener("click", async () => {
  el("login-error").textContent = "";
  try {
    const { handle, options } = await api("/api/auth/passkey/login/options", { method: "POST" });
    options.challenge = b64urlToBuf(options.challenge);
    for (const cred of options.allowCredentials || []) cred.id = b64urlToBuf(cred.id);

    const assertion = await navigator.credentials.get({ publicKey: options });
    await api("/api/auth/passkey/login/verify", {
      method: "POST",
      body: JSON.stringify({ handle, credential: serializeAssertion(assertion) }),
    });
    showMain();
    await start();
  } catch (error) {
    el("login-error").textContent = error.message || "не удалось войти по passkey";
  }
});

async function registerPasskey() {
  try {
    const { handle, options } = await api("/api/auth/passkey/register/options", { method: "POST" });
    options.challenge = b64urlToBuf(options.challenge);
    options.user.id = b64urlToBuf(options.user.id);
    for (const cred of options.excludeCredentials || []) cred.id = b64urlToBuf(cred.id);

    const credential = await navigator.credentials.create({ publicKey: options });
    await api("/api/auth/passkey/register/verify", {
      method: "POST",
      body: JSON.stringify({
        handle,
        label: navigator.userAgent.includes("Android") ? "Телефон Android" : "Это устройство",
        credential: {
          id: credential.id,
          rawId: bufToB64url(credential.rawId),
          type: credential.type,
          response: {
            clientDataJSON: bufToB64url(credential.response.clientDataJSON),
            attestationObject: bufToB64url(credential.response.attestationObject),
          },
        },
      }),
    });
    toast("Passkey зарегистрирован — теперь вход по отпечатку", "ok");
  } catch (error) {
    toast(error.message || "не удалось зарегистрировать passkey", "err");
  }
}

/* ============================================================ роутер ====

   Вкладка живёт в адресе, поэтому системная кнопка «назад» ведёт себя
   предсказуемо, а ссылку на нужный экран можно положить на рабочий стол.
   Справка — вложенный экран: своей кнопки в панели у неё нет, но подсветку
   она отдаёт родителю. */

const ROUTES = {
  deck: { title: "Пульт", view: () => viewDeck() },
  pcs: { title: "Компьютеры", view: () => viewPcs() },
  schedule: { title: "Расписание", view: () => viewSchedule() },
  more: { title: "Ещё", view: () => viewMore() },
  help: { title: "Справка", view: () => viewHelp(), parent: "more" },
};
const DEFAULT_ROUTE = "deck";

function route() {
  const name = location.hash.replace(/^#\//, "");
  return ROUTES[name] ? name : DEFAULT_ROUTE;
}

function syncChrome() {
  const current = route();
  const pc = activePc();

  el("page-title").textContent = ROUTES[current].title;

  // Переключатель компьютера нужен только там, где он на что-то влияет,
  // и только если компьютеров больше одного.
  const showPc = state.pcs.length > 1 && (current === "deck" || current === "pcs");
  const pcButton = el("btn-pc");
  pcButton.hidden = !showPc;
  if (showPc && pc) {
    pcButton.innerHTML = `<span class="dot ${esc(pc.state)}"></span>${esc(pc.name)}`;
  }

  const highlight = ROUTES[current].parent || current;
  for (const link of document.querySelectorAll("#tabbar .tab")) {
    const on = link.dataset.tab === highlight;
    link.classList.toggle("on", on);
    link.setAttribute("aria-current", on ? "page" : "false");
  }
  document.body.dataset.route = current;
  store.set(KEY_ROUTE, current);
}

window.addEventListener("hashchange", async () => {
  // Уходя с расписания, форму закрываем: возвращаться к наполовину
  // заполненному полю через две вкладки — не то, чего ждёшь.
  if (route() !== "schedule") state.form = { open: false, editId: null };
  syncChrome();
  await render(true);
  el("view").scrollTop = 0;
});

/* ========================================================== избранное === */

const favKey = (pcId, actionId) => `${pcId}::${actionId}`;
const favorites = () => store.json(KEY_FAV, []);
const isFavorite = (pcId, actionId) => favorites().includes(favKey(pcId, actionId));

function toggleFavorite(pcId, actionId) {
  const key = favKey(pcId, actionId);
  const list = favorites();
  const index = list.indexOf(key);
  if (index >= 0) list.splice(index, 1);
  else list.push(key);
  store.setJson(KEY_FAV, list);
  buzz(index >= 0 ? 15 : [12, 45, 12]);
  return index < 0;
}

/* =========================================================== пульт ======

   Кнопки питания живут не в списке действий, а отдельными ручками API.
   Чтобы их тоже можно было положить в избранное, даём им такой же вид,
   как у обычных действий. */

const POWER = {
  "power:shutdown": { name: "Выключить", icon: "⏻", dangerous: true },
  "power:restart": { name: "Перезагрузка", icon: "🔄", dangerous: true },
  "power:wake": { name: "Включить", icon: "⏻", dangerous: false },
};

function powerFor(pc) {
  const ids =
    pc.state === "online"
      ? ["power:restart", "power:shutdown"]
      : pc.wake_supported
        ? ["power:wake"]
        : [];
  return ids.map((id) => ({ id, available: true, group: "Питание", ...POWER[id] }));
}

function deckButton(pc, action) {
  const off = action.available === false;
  return `<button class="key ${action.dangerous ? "danger" : ""} ${isFavorite(pc.id, action.id) ? "fav" : ""}"
    data-key-pc="${esc(pc.id)}" data-key-action="${esc(action.id)}"
    ${off ? "disabled" : ""}
    title="${esc(action.description || action.name)}">
    <span class="key-ico">${esc(action.icon || "•")}</span>
    <span class="key-cap">${esc(action.name)}</span>
  </button>`;
}

function deckPage(pc, title, actions, note = "") {
  const body = actions.length
    ? `<div class="keys">${actions.map((a) => deckButton(pc, a)).join("")}</div>`
    : `<div class="empty">${esc(note || "Здесь пока пусто")}</div>`;
  return `<section class="page" data-title="${esc(title)}">${body}</section>`;
}

function viewDeck() {
  const pc = activePc();
  if (!pc) {
    return `<div class="empty">Ни одного ПК не настроено.<br>
      Добавьте секцию <code>[[pcs]]</code> в конфигурацию контроллера.</div>`;
  }

  const all = [...(pc.actions || []), ...powerFor(pc)];
  const byId = new Map(all.map((a) => [a.id, a]));

  // Порядок избранного — тот, в котором его добавляли: пользователь сам
  // решил, что важнее, и переставлять за него не нужно.
  const fav = favorites()
    .filter((key) => key.startsWith(`${pc.id}::`))
    .map((key) => byId.get(key.slice(pc.id.length + 2)))
    .filter(Boolean);

  const groups = new Map();
  for (const action of pc.actions || []) {
    const key = action.group || "Действия";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(action);
  }
  const power = powerFor(pc);
  if (power.length) groups.set("Питание", power);

  const offline = pc.state !== "online";
  const pages = [
    deckPage(pc, "Избранное", fav,
      offline
        ? `${pc.name} выключен. Включить его можно на странице «Питание» — листни влево.`
        : "Долгое нажатие на любой кнопке добавляет её сюда."),
    ...[...groups].map(([name, actions]) => deckPage(pc, name, actions)),
  ];

  const dots = pages.map((_, i) => `<i class="${i === 0 ? "on" : ""}"></i>`).join("");
  const warn = offline
    ? `<div class="banner">${esc(pc.name)} — ${esc(STATE_LABEL[pc.state] || pc.state)}. Действия недоступны.</div>`
    : "";

  return `${warn}
    <div class="pager" id="pager">${pages.join("")}</div>
    <div class="dots" id="dots">${dots}</div>`;
}

/* Заголовок страницы и точки ведём по фактической прокрутке, а не по
   «номеру страницы»: палец может остановиться между страницами. */
function bindPager() {
  const pager = el("pager");
  if (!pager) return;
  const dots = el("dots");
  const update = () => {
    const index = Math.round(pager.scrollLeft / pager.clientWidth);
    const page = pager.children[index];
    if (page) el("page-title").textContent = page.dataset.title;
    [...dots.children].forEach((dot, i) => dot.classList.toggle("on", i === index));
  };
  pager.addEventListener("scroll", update, { passive: true });
  update();
}

/* ======================================================= вкладка «ПК» === */

function metric(label, value, percent = null, note = null) {
  const barClass = percent >= 90 ? "crit" : percent >= 70 ? "hot" : "";
  const bar =
    percent == null
      ? ""
      : `<div class="bar"><i class="${barClass}" style="width:${Math.min(100, percent)}%"></i></div>`;
  return `<div class="metric ${percent == null ? "na" : ""}">
    <div class="label">${esc(label)}</div>
    <div class="value">${esc(value)}${note ? ` <small>${esc(note)}</small>` : ""}</div>
    ${bar}
  </div>`;
}

function renderMetrics(stats) {
  if (!stats) return "";
  const cpu = stats.cpu?.usage_percent;
  const mem = stats.memory?.usage_percent;
  const gpu = stats.gpus?.[0];
  const rootDisk = stats.disks?.find((d) => d.mountpoint === "/") || stats.disks?.[0];
  const cpuTemp = stats.temperatures?.find((t) => /package|tctl|cpu/i.test(t.label))?.celsius;

  const parts = [
    metric("Процессор", cpu == null ? "нет данных" : `${cpu.toFixed(0)}%`, cpu,
      cpuTemp != null ? `${cpuTemp.toFixed(0)}°` : null),
    metric("Память", mem == null ? "нет данных" : `${mem.toFixed(0)}%`, mem,
      stats.memory?.total_bytes ? fmtBytes(stats.memory.total_bytes) : null),
  ];
  // Пустая плитка «нет данных» бесполезна: видеокарту показываем, если есть.
  if (gpu) {
    parts.push(metric("Видеокарта",
      gpu.utilization_percent == null ? "—" : `${gpu.utilization_percent.toFixed(0)}%`,
      gpu.utilization_percent,
      gpu.temperature_celsius != null ? `${gpu.temperature_celsius.toFixed(0)}°` : null));
  }
  if (rootDisk) {
    parts.push(metric("Диск",
      rootDisk.usage_percent == null ? "—" : `${rootDisk.usage_percent.toFixed(0)}%`,
      rootDisk.usage_percent,
      rootDisk.free_bytes ? `${fmtBytes(rootDisk.free_bytes)} своб.` : null));
  }
  parts.push(metric("Время работы", fmtUptime(stats.uptime_seconds), null));
  return `<div class="metrics">${parts.join("")}</div>`;
}

function pcCard(pc) {
  const online = pc.state === "online";

  let meta = "";
  if (online && pc.stale) {
    meta = `<div class="meta warn">данные устарели (${Math.round(pc.stats_age_seconds)} с назад)</div>`;
  } else if (!online && pc.last_error) {
    meta = `<div class="meta err">${esc(pc.last_error)}</div>`;
  } else if (!online && pc.last_seen) {
    meta = `<div class="meta">последний раз на связи: ${new Date(pc.last_seen).toLocaleString("ru")}</div>`;
  } else if (pc.description) {
    meta = `<div class="meta">${esc(pc.description)}</div>`;
  }

  let body = "";
  if (online) {
    body = renderMetrics(pc.stats);
    const buttons = [];
    if (pc.terminal_supported) {
      buttons.push(`<button class="btn" data-terminal="${esc(pc.id)}">⌨️ Терминал</button>`);
    }
    buttons.push(`<button class="btn danger" data-power="restart" data-pc="${esc(pc.id)}">🔄 Перезагрузка</button>`);
    buttons.push(`<button class="btn danger" data-power="shutdown" data-pc="${esc(pc.id)}">⏻ Выключить</button>`);
    body += `<div class="row">${buttons.join("")}</div>`;
  } else if (pc.wake_supported) {
    body = `<div class="row"><button class="btn primary" data-wake="${esc(pc.id)}">⏻ Включить</button></div>`;
  } else {
    body = `<div class="meta">MAC-адрес не задан — разбудить нечем</div>`;
  }

  return `<section class="card ${pc.stale && online ? "stale" : ""}">
    <div class="card-head">
      <span class="dot ${esc(pc.state)}"></span>
      <h2>${esc(pc.name)}</h2>
      <span class="state-label">${esc(STATE_LABEL[pc.state] || pc.state)}</span>
    </div>
    ${meta}
    ${body}
  </section>`;
}

function esp32Card(status) {
  if (!status) return "";
  const online = status.state === "online";
  const sim = status.simulated
    ? `<div class="meta warn">режим симуляции: настоящее железо не подключено</div>`
    : "";

  let details = "";
  if (online) {
    details = `<div class="metrics">${[
      metric("Wi-Fi", status.wifi_rssi_dbm != null ? `${status.wifi_rssi_dbm} дБм` : "—", null,
        status.wifi_ssid || null),
      metric("Память", fmtBytes(status.free_heap_bytes), null,
        status.psram_present ? "PSRAM есть" : "без PSRAM"),
      metric("Время работы", fmtUptime(status.uptime_seconds), null),
    ].join("")}</div>`;

    // Сторож — то, ради чего плата существует: он замечает, что ПК погас,
    // и будит его сам, без телефона и без контроллера.
    if (status.guard) {
      const g = status.guard;
      details += `<div class="group-title">Сторож</div>
        <div class="kv">
          <div><span>Режим</span><b>${esc(g.state ?? "—")}</b></div>
          <div><span>ПК на связи</span><b>${g.host_alive ? "да" : "нет"}</b></div>
          <div><span>Попыток разбудить</span><b>${esc(g.attempts ?? 0)}</b></div>
          <div><span>Всего пробуждений</span><b>${esc(g.total_wakes ?? 0)}</b></div>
        </div>`;
    }
    if (status.gpio?.length) {
      details += `<div class="group-title">Выводы</div><div class="kv">` +
        status.gpio.map((pin) =>
          `<div><span>${esc(pin.mode === "input" ? "вход" : "выход")} ${pin.pin} · ${esc(pin.label || "")}</span>` +
          `<b>${pin.level == null ? "?" : pin.level ? "1" : "0"}</b></div>`).join("") +
        `</div>`;
    }
  } else if (status.last_error) {
    details = `<div class="meta err">${esc(status.last_error)}</div>`;
  }

  return `<section class="card">
    <div class="card-head">
      <span class="dot ${esc(status.state)}"></span>
      <h2>ESP32${status.simulated ? " (симулятор)" : ""}</h2>
      <span class="state-label">${esc(STATE_LABEL[status.state] || status.state)}</span>
    </div>
    ${sim}
    ${details}
  </section>`;
}

function viewPcs() {
  if (!state.pcs.length) {
    return `<div class="empty">Ни одного ПК не настроено.</div>`;
  }
  return state.pcs.map(pcCard).join("") + esp32Card(state.esp32);
}

/* ==================================================== вкладка расписания */

const DAY_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

function daysLabel(days) {
  if (!days.length || days.length === 7) return "ежедневно";
  if (String(days) === "0,1,2,3,4") return "будни";
  if (String(days) === "5,6") return "выходные";
  return days.map((d) => DAY_SHORT[d]).join(" ");
}

const actionsOf = (pcId) => state.pcs.find((p) => p.id === pcId)?.actions || [];

function actionLabel(pcId, actionId) {
  const action = actionsOf(pcId).find((a) => a.id === actionId);
  return action ? action.name : actionId;
}

function scheduleRow(entry) {
  const pc = state.pcs.find((p) => p.id === entry.pc_id);
  const pcName = pc ? pc.name : entry.pc_id;

  let status;
  if (entry.last_run_at) {
    const when = new Date(entry.last_run_at).toLocaleString("ru", {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    });
    status = entry.last_ok
      ? `<div class="meta">последний раз: ${esc(when)} — успешно</div>`
      : `<div class="meta err">последний раз: ${esc(when)} — ${esc(entry.last_message || "ошибка")}</div>`;
  } else {
    status = `<div class="meta">ещё ни разу не срабатывало</div>`;
  }

  return `
  <div class="sched ${entry.enabled ? "" : "off"}">
    <div class="sched-head">
      <div class="sched-time">${esc(entry.at)}</div>
      <div class="sched-main">
        <div class="sched-name">${esc(entry.name)}</div>
        <div class="meta">${esc(daysLabel(entry.days))} · ${esc(pcName)} · ${esc(actionLabel(entry.pc_id, entry.action_id))}</div>
      </div>
      <button class="icon-btn" data-sched-toggle="${esc(entry.id)}"
        title="${entry.enabled ? "Выключить правило" : "Включить правило"}">${entry.enabled ? "⏸" : "▶"}</button>
    </div>
    ${status}
    <div class="row">
      <button class="btn" data-sched-run="${esc(entry.id)}">▶ Выполнить</button>
      <button class="btn" data-sched-edit="${esc(entry.id)}">✎ Изменить</button>
      <button class="btn danger" data-sched-del="${esc(entry.id)}">🗑 Удалить</button>
    </div>
  </div>`;
}

function scheduleForm() {
  if (!state.form.open) return "";
  const entry = state.form.editId ? state.schedules.find((s) => s.id === state.form.editId) : null;
  const pcId = entry?.pc_id || state.pcs[0]?.id || "";
  const days = entry?.days || [];

  const pcOptions = state.pcs
    .map((p) => `<option value="${esc(p.id)}" ${p.id === pcId ? "selected" : ""}>${esc(p.name)}</option>`)
    .join("");

  const dayButtons = DAY_SHORT.map(
    (name, index) =>
      `<button type="button" class="day ${days.includes(index) ? "on" : ""}" data-day="${index}">${name}</button>`,
  ).join("");

  return `
  <form class="sched-form" id="sched-form">
    <input type="text" id="sf-name" placeholder="Название, например «Погасить свет»"
      value="${esc(entry?.name || "")}" maxlength="120" required>
    <div class="row">
      <input type="time" id="sf-at" value="${esc(entry?.at || "23:00")}" required>
      <select id="sf-pc">${pcOptions}</select>
    </div>
    <select id="sf-action"></select>
    <div class="days" id="sf-days">${dayButtons}</div>
    <div class="meta">Ни один день не выбран — правило работает каждый день.</div>
    <div class="row">
      <button class="btn primary" type="submit">${entry ? "Сохранить" : "Добавить"}</button>
      <button class="btn" type="button" id="sf-cancel">Отмена</button>
    </div>
  </form>`;
}

function fillActionSelect(selectedActionId) {
  const pcSelect = el("sf-pc");
  const actionSelect = el("sf-action");
  if (!pcSelect || !actionSelect) return;

  const actions = actionsOf(pcSelect.value);
  if (!actions.length) {
    actionSelect.innerHTML = `<option value="">действий нет — ПК выключен?</option>`;
    return;
  }
  actionSelect.innerHTML = actions
    .map((a) =>
      `<option value="${esc(a.id)}" ${a.id === selectedActionId ? "selected" : ""}>${esc(
        (a.group ? a.group + ": " : "") + a.name)}</option>`)
    .join("");
}

function viewSchedule() {
  const rows = state.schedules.length
    ? state.schedules.map(scheduleRow).join("")
    : `<div class="empty">Расписаний нет.<br>Например: погасить подсветку в 23:00.</div>`;

  return `
  <section class="card">
    <div class="card-head">
      <h2>Правила</h2>
      ${state.form.open ? "" : `<button class="icon-btn" id="sched-add" title="Добавить правило">+</button>`}
    </div>
    ${scheduleForm()}
    ${rows}
  </section>`;
}

/* ======================================================== вкладка «Ещё» */

function viewMore() {
  const passkeyReady = state.auth?.passkey_configured && window.PublicKeyCredential;
  const note = passkeyReady
    ? "Вход по отпечатку или лицу вместо пароля."
    : "Нужен HTTPS и заданный auth.webauthn_rp_id — см. справку.";

  const pcButtons = state.pcs
    .map((p) => `<button class="btn ${p.id === activePc()?.id ? "primary" : ""}" data-pick-pc="${esc(p.id)}">
      <span class="dot ${esc(p.state)}"></span>${esc(p.name)}</button>`)
    .join("");

  return `
  <section class="card">
    <div class="card-head"><h2>Компьютер на пульте</h2></div>
    <div class="row">${pcButtons || `<div class="meta">ПК не настроены</div>`}</div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Вход</h2></div>
    <div class="row">
      <button class="btn" id="more-passkey" ${passkeyReady ? "" : "disabled"}>🔑 Зарегистрировать passkey</button>
    </div>
    <div class="meta">${esc(note)}</div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Справка и служебное</h2></div>
    <div class="row">
      <button class="btn" data-go="help">📖 Как этим пользоваться</button>
      <button class="btn" id="more-docs">🛠 Документация API</button>
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Сеанс</h2></div>
    <div class="row"><button class="btn danger" id="more-logout">🚪 Выйти</button></div>
  </section>`;
}

function viewHelp() {
  return `
  <section class="card">
    <div class="card-head"><h2>🎛 Пульт</h2></div>
    <div class="help">
      <p>Главный экран. Крупные кнопки, которые листаются пальцем влево-вправо:
      сначала <b>Избранное</b>, потом по странице на каждую группу действий,
      в конце — <b>Питание</b>.</p>
      <p><b>Долгое нажатие на кнопке кладёт её в избранное</b> и убирает обратно.
      Телефон коротко вибрирует. Порядок — тот, в котором ты добавлял.</p>
      <p>Поверни телефон набок — кнопок в ряду станет больше, всё остальное
      останется прежним.</p>
      <p>Избранное хранится в этом браузере, а не в системе: у телефона и
      планшета могут быть разные наборы.</p>
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>🖥 Компьютеры</h2></div>
    <div class="help">
      <p>Загрузка процессора, памяти, видеокарты и диска, а также кнопки
      питания и терминал.</p>
      <p>Если компьютер выключен, остаётся кнопка <b>Включить</b>: она шлёт
      magic packet. Загрузка занимает минуту-полторы — это нормально.</p>
      <p>Ниже — плата ESP32 и её <b>сторож</b>. Плата сама пингует основной ПК
      и, если он пропал надолго, будит его. Выключить компьютер она не может:
      только включить.</p>
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>⏰ Расписание</h2></div>
    <div class="help">
      <p>Правила вида «в 23:00 по будням погасить подсветку». Время считает
      контроллер на домашнем ПК, поэтому правила срабатывают и с закрытым
      браузером.</p>
      <p>Список действий берётся у выбранного компьютера: для выключенного
      выбирать будет не из чего.</p>
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Если что-то не работает</h2></div>
    <div class="help">
      <p><b>Не открывается с телефона.</b> Включён ли Tailscale? Адрес — это
      тайлнет-адрес домашнего ПК; <code>127.0.0.1</code> означает «сам телефон».</p>
      <p><b>ESP32 «выключена».</b> Скорее всего роутер выдал плате другой адрес.
      Лечится закреплением адреса в настройках роутера.</p>
      <p><b>Компьютер не будится.</b> Wake-on-LAN должен быть включён в BIOS и
      в сетевой карте, а кабель — воткнут: по Wi-Fi это не работает.</p>
      <p>Подробное руководство — файл <code>MANUAL.md</code> в репозитории.</p>
    </div>
  </section>`;
}

/* ========================================================= отрисовка ==== */

async function render(force = false) {
  if (state.rendering) return;
  // Живые обновления приходят каждые несколько секунд. Перерисовка открытой
  // формы стёрла бы введённый текст прямо под пальцем.
  if (state.form.open && !force) return;
  state.rendering = true;

  const current = route();
  try {
    const [pcs, esp32, schedules] = await Promise.all([
      api("/api/pcs"),
      api("/api/esp32/status").catch(() => null),
      api("/api/schedules").catch(() => []),
    ]);
    state.pcs = pcs;
    state.esp32 = esp32;
    state.schedules = schedules;
    if (current === "more") state.auth = await api("/api/auth/status").catch(() => state.auth);

    // Лист, на котором стоит палец, при обновлении данных сбрасываться
    // не должен.
    const pager = el("pager");
    const offset = pager ? pager.scrollLeft : 0;

    syncChrome();
    el("view").innerHTML = ROUTES[current].view();

    if (current === "deck") {
      const fresh = el("pager");
      if (fresh) fresh.scrollLeft = offset;
      bindPager();
    }
    if (current === "schedule" && state.form.open) {
      fillActionSelect(state.schedules.find((s) => s.id === state.form.editId)?.action_id);
    }
  } catch (error) {
    if (error.message !== "требуется вход") {
      el("view").innerHTML = `<div class="empty">Ошибка: ${esc(error.message)}</div>`;
    }
  } finally {
    state.rendering = false;
  }
}

async function withBusy(button, fn) {
  button.classList.add("busy");
  button.disabled = true;
  try {
    return await fn();
  } finally {
    button.classList.remove("busy");
    button.disabled = false;
  }
}

/* Единая обёртка над вызовом API из кнопки: раньше try/catch с toast был
   переписан у каждого обработчика по-своему, и сообщения об ошибках
   отличались там, где отличаться не должны. */
async function run(button, request, onOk) {
  await withBusy(button, async () => {
    try {
      const result = await request();
      onOk?.(result);
    } catch (error) {
      toast(error.message, "err", error.requestId);
    }
  });
}

/* ====================================================== долгое нажатие ==

   Обычное нажатие выполняет действие, удержание — кладёт в избранное.
   Чтобы после удержания не сработало и действие, помечаем кнопку и гасим
   следующий click. */

let pressTimer = null;
let pressedButton = null;

document.addEventListener("pointerdown", (event) => {
  const button = event.target.closest("button.key");
  if (!button) return;
  pressedButton = button;
  // Если после прошлого удержания click почему-то не пришёл (кнопка успела
  // перерисоваться), метка осталась бы висеть и съела бы следующее нажатие.
  delete button.dataset.longpress;
  pressTimer = setTimeout(() => {
    pressTimer = null;
    button.dataset.longpress = "1";
    const added = toggleFavorite(button.dataset.keyPc, button.dataset.keyAction);
    button.classList.toggle("fav", added);
    toast(added ? "добавлено в избранное" : "убрано из избранного", "ok");
  }, 500);
});

const cancelPress = () => {
  clearTimeout(pressTimer);
  pressTimer = null;
  pressedButton = null;
};
document.addEventListener("pointerup", cancelPress);
document.addEventListener("pointercancel", cancelPress);
// Листание страницы пальцем не должно считаться удержанием.
document.addEventListener("pointermove", (event) => {
  if (pressedButton && Math.abs(event.movementX) + Math.abs(event.movementY) > 6) cancelPress();
});

/* ============================================================ нажатия === */

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const d = button.dataset;

  /* --- кнопка пульта --- */
  if (d.keyAction) {
    if (d.longpress) {
      delete d.longpress;
      return;
    }
    const pcId = d.keyPc;
    const id = d.keyAction;

    if (id === "power:wake") {
      return run(button, () => api(`/api/pcs/${encodeURIComponent(pcId)}/wake`, { method: "POST" }),
        (result) => {
          const ways = result.attempts.filter((a) => a.ok).map((a) => a.method).join(", ");
          toast(`Magic packet отправлен (${ways}). Ждём загрузки…`, "ok");
          setTimeout(() => render(true), 3000);
        });
    }
    if (id.startsWith("power:")) {
      const what = id.slice(6);
      const pc = state.pcs.find((p) => p.id === pcId);
      const ok = await confirmSheet({
        icon: what === "shutdown" ? "⏻" : "🔄",
        title: what === "shutdown" ? `Выключить ${pc?.name || "компьютер"}?` : `Перезагрузить ${pc?.name || "компьютер"}?`,
        text: what === "shutdown"
          ? "Плата-сторож получит указание не будить его: выключение считается плановым."
          : "Компьютер вернётся сам через минуту-полторы.",
        yes: what === "shutdown" ? "Выключить" : "Перезагрузить",
      });
      if (!ok) return;
      return run(button, () => api(`/api/pcs/${encodeURIComponent(pcId)}/${what}`, { method: "POST" }),
        (result) => {
          toast(result.message || "команда отправлена", result.success ? "ok" : "err");
          setTimeout(() => render(true), 2000);
        });
    }

    buzz(8);
    return run(button,
      () => api(`/api/pcs/${encodeURIComponent(pcId)}/actions/${encodeURIComponent(id)}`, { method: "POST" }),
      (result) => toast(result.message || (result.success ? "готово" : "не выполнено"),
        result.success ? "ok" : "err"));
  }

  /* --- карточка ПК --- */
  if (d.terminal) {
    location.href = `/terminal?pc=${encodeURIComponent(d.terminal)}`;
    return;
  }
  if (d.wake) {
    return run(button, () => api(`/api/pcs/${encodeURIComponent(d.wake)}/wake`, { method: "POST" }),
      (result) => {
        const ways = result.attempts.filter((a) => a.ok).map((a) => a.method).join(", ");
        toast(`Magic packet отправлен (${ways}). Ждём загрузки…`, "ok");
        setTimeout(() => render(true), 3000);
      });
  }
  if (d.power) {
    const pc = state.pcs.find((p) => p.id === d.pc);
    const ok = await confirmSheet({
      icon: d.power === "shutdown" ? "⏻" : "🔄",
      title: d.power === "shutdown" ? `Выключить ${pc?.name || "компьютер"}?` : `Перезагрузить ${pc?.name || "компьютер"}?`,
      text: d.power === "shutdown"
        ? "Плата-сторож получит указание не будить его: выключение считается плановым."
        : "Компьютер вернётся сам через минуту-полторы.",
      yes: d.power === "shutdown" ? "Выключить" : "Перезагрузить",
    });
    if (!ok) return;
    return run(button, () => api(`/api/pcs/${encodeURIComponent(d.pc)}/${d.power}`, { method: "POST" }),
      (result) => {
        toast(result.message || "команда отправлена", result.success ? "ok" : "err");
        setTimeout(() => render(true), 2000);
      });
  }

  /* --- выбор компьютера --- */
  if (button.id === "btn-pc") {
    // Перебор по кругу: выпадающий список в шапке пульта негде разместить.
    const index = state.pcs.findIndex((p) => p.id === activePc()?.id);
    store.set(KEY_PC, state.pcs[(index + 1) % state.pcs.length].id);
    await render(true);
    return;
  }
  if (d.pickPc) {
    store.set(KEY_PC, d.pickPc);
    toast("компьютер на пульте изменён", "ok");
    await render(true);
    return;
  }

  /* --- расписание --- */
  if (button.id === "sched-add") {
    state.form = { open: true, editId: null };
    return render(true);
  }
  if (button.id === "sf-cancel") {
    state.form = { open: false, editId: null };
    return render(true);
  }
  if (d.day !== undefined) {
    button.classList.toggle("on");
    return;
  }
  if (d.schedEdit) {
    state.form = { open: true, editId: d.schedEdit };
    return render(true);
  }
  if (d.schedToggle) {
    const entry = state.schedules.find((s) => s.id === d.schedToggle);
    return run(button,
      () => api(`/api/schedules/${encodeURIComponent(d.schedToggle)}`, {
        method: "PATCH", body: JSON.stringify({ enabled: !entry.enabled }),
      }),
      () => render(true));
  }
  if (d.schedRun) {
    return run(button,
      () => api(`/api/schedules/${encodeURIComponent(d.schedRun)}/run`, { method: "POST" }),
      (entry) => {
        toast(entry.last_ok ? "выполнено" : entry.last_message || "не выполнено",
          entry.last_ok ? "ok" : "err");
        render(true);
      });
  }
  if (d.schedDel) {
    const entry = state.schedules.find((s) => s.id === d.schedDel);
    const ok = await confirmSheet({
      icon: "🗑", title: "Удалить правило?", text: entry?.name || "", yes: "Удалить",
    });
    if (!ok) return;
    return run(button,
      () => api(`/api/schedules/${encodeURIComponent(d.schedDel)}`, { method: "DELETE" }),
      () => {
        toast("правило удалено", "ok");
        render(true);
      });
  }

  /* --- «Ещё» --- */
  if (d.go) {
    location.hash = `#/${d.go}`;
    return;
  }
  if (button.id === "more-passkey") return withBusy(button, registerPasskey);
  if (button.id === "more-docs") {
    location.href = "/docs";
    return;
  }
  if (button.id === "more-logout") {
    const ok = await confirmSheet({ icon: "🚪", title: "Выйти?", yes: "Выйти" });
    if (!ok) return;
    await api("/api/auth/logout", { method: "POST" });
    location.reload();
    return;
  }
  if (button.id === "btn-refresh") {
    buzz(8);
    return render(true);
  }
});

document.addEventListener("change", (event) => {
  if (event.target.id === "sf-pc") fillActionSelect(null);
});

/* Слушатель на document, а не на форме: разметка пересоздаётся при каждой
   перерисовке, и обработчик на элементе умер бы вместе с ней. */
document.addEventListener("submit", async (event) => {
  if (event.target.id !== "sched-form") return;
  event.preventDefault();

  const days = [...document.querySelectorAll("#sf-days .day.on")].map((b) => Number(b.dataset.day));
  const actionId = el("sf-action").value;
  if (!actionId) {
    toast("нечего выполнять: у выбранного ПК нет доступных действий", "err");
    return;
  }

  const payload = {
    name: el("sf-name").value.trim(),
    at: el("sf-at").value,
    days,
    pc_id: el("sf-pc").value,
    action_id: actionId,
  };

  const submit = event.target.querySelector("button[type=submit]");
  await run(submit, async () => {
    if (state.form.editId) {
      await api(`/api/schedules/${encodeURIComponent(state.form.editId)}`, {
        method: "PATCH", body: JSON.stringify(payload),
      });
      toast("правило сохранено", "ok");
    } else {
      // Идентификатор пользователю не нужен: он служит адресом записи
      // в API и файле.
      payload.id = `s${Date.now().toString(36)}`;
      payload.enabled = true;
      await api("/api/schedules", { method: "POST", body: JSON.stringify(payload) });
      toast("правило добавлено", "ok");
    }
    state.form = { open: false, editId: null };
    await render(true);
  });
});

/* ==================================================== живые обновления == */

let eventSource = null;

function connectEvents() {
  eventSource?.close();
  eventSource = new EventSource("/api/events");
  eventSource.addEventListener("hello", () => {
    el("conn-status").textContent = "живое обновление";
  });
  eventSource.addEventListener("update", () => render());
  eventSource.onerror = () => {
    el("conn-status").textContent = "переподключение…";
    // Браузер переподключает EventSource сам; наша задача — не мешать.
  };
}

async function start() {
  syncChrome();
  await render(true);
  connectEvents();
  // Подстраховка, если события не дойдут: редкий фоновый опрос.
  setInterval(() => {
    if (!document.hidden) render();
  }, 15000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) render();
  });
}

(async () => {
  // Без адреса в строке открываем экран, на котором ушли в прошлый раз.
  if (!location.hash) {
    const saved = store.get(KEY_ROUTE);
    location.replace(`#/${ROUTES[saved] ? saved : DEFAULT_ROUTE}`);
  }
  syncChrome();
  if (await refreshAuth()) await start();
})();
