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
  approvals: [],         // чего компьютер ждёт от нас прямо сейчас
  approvalsEnabled: false,
  editor: null,          // состояние редактора кнопок текущего ПК
  buttonForm: null,      // черновик формы: null — форма закрыта
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

/* Выключение сервера — отдельный разговор: на нём живёт само управление. */
async function confirmPower(pc, what) {
  const name = pc?.name || "компьютер";
  if (what !== "shutdown") {
    return confirmSheet({
      icon: "🔄",
      title: `Перезагрузить ${name}?`,
      text: "Компьютер вернётся сам через минуту-полторы.",
      yes: "Перезагрузить",
    });
  }
  if (pc?.hosts_controller) {
    const first = await confirmSheet({
      icon: "🖥",
      title: `${name} — ваш сервер`,
      text: "На нём живёт само управление: после выключения телефон не сможет ни разбудить его, "
        + "ни что-нибудь запустить. Поднимать придётся кнопкой на корпусе или платой-сторожем.",
      yes: "Всё равно выключить",
    });
    if (!first) return false;
  }
  return confirmSheet({
    icon: "⏻",
    title: `Выключить ${name}?`,
    text: pc?.hosts_controller
      ? "Последняя проверка. Может, хватит заблокировать экран или закрыть лишние программы?"
      : "Плата-сторож получит указание не будить его: выключение считается плановым.",
    yes: "Выключить",
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
  buttons: { title: "Свои кнопки", view: () => viewButtons(), parent: "more" },
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
      : `<div class="bar"><i class="${barClass}" style="transform:scaleX(${Math.min(100, percent) / 100})"></i></div>`;
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

// Настройки сторожа, прочитанные из самой платы.
//
// Это не украшение. Консоль у платы только по USB, а стоит она в розетке
// без провода: единственный способ узнать, какой MAC в неё записан, —
// спросить по сети. Когда побудка не срабатывает, первый вопрос всегда
// один: пакет вообще уходил по верному адресу?
function guardConfigBlock(cfg) {
  if (!cfg) {
    return `<div class="meta">Прошивка платы не сообщает настройки сторожа — обновите её,
      чтобы видеть, какой MAC в неё записан.</div>`;
  }

  // Сверяем записанный в плату MAC с тем ПК, которого она стережёт.
  // Расхождение выглядит как полностью исправная система, которая молча
  // будит несуществующую машину, — поймать это глазами почти невозможно.
  const norm = (m) => (m || "").toLowerCase().replace(/[^0-9a-f]/g, "");
  const guarded = state.pcs.find((pc) => norm(pc.mac_address) === norm(cfg.mac_address));
  const known = state.pcs.some((pc) => norm(pc.mac_address));
  const warning = !cfg.mac_address
    ? `<div class="meta err">MAC не записан — будить некого.</div>`
    : (!guarded && known)
      ? `<div class="meta err">Этот MAC не совпадает ни с одним известным ПК.
         Сторож будет будить не ту машину.</div>`
      : "";

  return `<div class="kv">
      <div><span>Стережёт</span><b>${esc(cfg.host || "—")}</b></div>
      <div><span>MAC</span><b>${esc(cfg.mac_address || "не задан")}</b></div>
      <div><span>Ждёт перед побудкой</span><b>${esc(cfg.grace_minutes ?? "—")} мин</b></div>
      <div><span>Пауза между попытками</span><b>${esc(cfg.retry_minutes ?? "—")} мин</b></div>
      <div><span>Попыток</span><b>${cfg.max_attempts ? esc(cfg.max_attempts) : "без предела"}</b></div>
    </div>${warning}`;
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
      details += guardConfigBlock(g.config);
      if (g.config) {
        const off = g.config.enabled === false;
        details += `<div class="row"><button class="btn ${off ? "primary" : "danger"}"
          data-guard="${off ? "on" : "off"}">${off ? "👁 Включить слежку" : "🚫 Выключить слежку"}</button></div>`;
      }
    }
    // Кнопка. Главное здесь — «изменений уровня»: если после нажатия оно
    // стоит на месте, сигнал не доходит до вывода, и искать ошибку в
    // разборе нажатий бесполезно. Плата висит на стене, консоль только по
    // USB — без этих чисел жалобу «кнопка не работает» разобрать нечем.
    if (status.button) {
      const b = status.button;
      const mute = "color:var(--text-dim)";
      details += `<div class="group-title">Кнопка</div>
        <div class="kv">
          <div><span>Вывод</span><b>${b.configured ? `GPIO${esc(b.pin)}` : "выключена"}</b></div>
          <div><span>Сейчас</span><b>${b.pressed_now ? "нажата" : "отпущена"}</b></div>
          <div><span>Изменений уровня</span><b>${esc(b.level_changes ?? 0)}</b></div>
          <div><span>Коротких нажатий</span><b>${esc(b.short_presses ?? 0)}</b></div>
          <div><span>Долгих нажатий</span><b>${esc(b.long_presses ?? 0)}</b></div>
        </div>`;
      if (b.configured && (b.level_changes ?? 0) === 0) {
        details += `<div class="banner warn">Плата ни разу не заметила нажатия.
          Нажмите кнопку и обновите экран: если «изменений уровня» осталось нулём,
          вывод GPIO${esc(b.pin)} не тот. Сменить: команда <code>pins button &lt;номер&gt;</code>
          в консоли платы по USB.</div>`;
      }
      if (status.led) {
        details += `<div class="meta" style="${mute}">Светодиод: ${
          status.led.type ? `GPIO${esc(status.led.pin)}, ${
            status.led.type === 2 ? "адресный" : "обычный"}` : "не настроен"}</div>`;
      }
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

/* ============================================ подтверждение входа ======

   Компьютер спрашивает — телефон отвечает. Так работают часы с Mac, и
   ровно это здесь: пароль не хранится и не передаётся, подтверждается
   факт «это я».

   Запросы показываются на любой вкладке и первыми: человек уже стоит у
   компьютера и ждёт, искать их по меню он не станет. */

const APPROVAL_TITLES = {
  login: "Вход в систему",
  sudo: "Команда от имени root",
  other: "Подтверждение",
};

function approvalBlock() {
  if (!state.approvals.length) return "";

  return state.approvals
    .filter((a) => a.state === "pending")
    .map((a) => `
      <section class="card approval">
        <div class="card-head">
          <span class="dot connecting"></span>
          <h2>${esc(APPROVAL_TITLES[a.kind] || a.kind)}</h2>
          <span class="state-label">${esc(a.seconds_left)} с</span>
        </div>
        <div class="kv">
          <div><span class="label">Откуда</span><span class="value">${esc(a.source || "—")}</span></div>
          ${a.command ? `<div><span class="label">Команда</span><span class="value">${esc(a.command)}</span></div>` : ""}
        </div>
        <div class="row">
          <button class="btn" data-approve="${esc(a.id)}" data-ok="0">Отклонить</button>
          <button class="btn primary" data-approve="${esc(a.id)}" data-ok="1">Подтвердить</button>
        </div>
      </section>`)
    .join("");
}

/* ==================================================== свои кнопки =======

   Своя кнопка — это команда, которую машина выполнит. Поэтому форма
   намеренно не даёт ввести командную строку: отдельно программа, отдельно
   аргументы, вид действия — из списка. Так «удобно» не превращается в
   «через интерфейс можно выполнить что угодно одной строкой».

   Кнопки из agent.toml показаны здесь же, но только на чтение: тот файл
   ведёт человек, и переписывать его комментарии программа не вправе. */

const KIND_NAMES = {
  desktop: "Приложение",
  exec: "Программа",
  tmux: "Команда в tmux",
  systemd_user: "Служба (пользователя)",
  systemd_system: "Служба (системная)",
  shell_script: "Скрипт с диска",
};

const KIND_HINTS = {
  desktop: "Запускает окно на экране компьютера: браузер, игру, редактор.",
  exec: "Запускает программу без графики. Окна не будет.",
  tmux: "Запускает команду в фоновой сессии tmux — она переживёт обрыв связи, и к ней можно подключиться из терминала.",
  systemd_user: "Управляет службой, настроенной у пользователя.",
  systemd_system: "Управляет системной службой. Обычно требует прав.",
  shell_script: "Запускает файл, который вы заранее положили на диск.",
};

/* Идентификатор из названия: латиница как есть, кириллица — транслитом.
   Правила простые и предсказуемые; при правке идентификатор уже не
   меняется, иначе кнопка потеряла бы избранное и расписания. */
const TRANSLIT = {
  а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z",
  и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r",
  с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "c", ч: "ch", ш: "sh", щ: "sch",
  ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
};

function slugify(name) {
  const base = [...name.toLowerCase()]
    .map((ch) => (TRANSLIT[ch] !== undefined ? TRANSLIT[ch] : ch))
    .join("")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
  // Идентификатор обязан начинаться с буквы или цифры.
  return /^[a-z0-9]/.test(base) ? base : `knopka-${Date.now().toString(36)}`;
}

const editorPc = () => activePc();

function buttonRow(action) {
  const kind = KIND_NAMES[action.kind] || action.kind;
  const tag = action.editable ? "" : `<span class="tag">в файле</span>`;
  return `<button class="list-row" data-edit-button="${esc(action.id)}" ${action.editable ? "" : "disabled"}>
    <span class="ico">${esc(action.icon || "•")}</span>
    <span class="body">
      <span class="title">${esc(action.name)}</span>
      <span class="sub">${esc(kind)}${action.group ? ` · ${esc(action.group)}` : ""}</span>
    </span>
    ${tag}
    <span class="chev">${action.editable ? "›" : ""}</span>
  </button>`;
}

function viewButtons() {
  const pc = editorPc();
  if (!pc) return `<div class="empty">Сначала настройте хотя бы один компьютер.</div>`;
  if (state.buttonForm) return buttonForm(pc);

  const editor = state.editor;
  if (!editor) return `<div class="empty">Загрузка…</div>`;

  if (!editor.enabled) {
    return `<div class="banner warn">Правка кнопок на «${esc(pc.name)}» выключена.
      Включить: <code>actions_editor.enabled = true</code> в конфигурации агента.</div>
      <div class="empty">Кнопки этой машины описаны в её <code>agent.toml</code>.</div>`;
  }

  const all = pc.actions || [];
  const mine = all.filter((a) => a.editable);
  const fromFile = all.filter((a) => !a.editable);

  return `
  <div class="banner">Кнопки появляются на пульте компьютера «${esc(pc.name)}».
    Сменить компьютер — на вкладке «Ещё».</div>

  ${mine.length ? `<div class="group-title">Мои кнопки</div>
    <div class="list">${mine.map(buttonRow).join("")}</div>` : ""}

  <div class="row"><button class="btn primary" id="button-add">＋ Добавить кнопку</button></div>

  ${fromFile.length ? `<div class="group-title">Из файла agent.toml</div>
    <div class="list">${fromFile.map(buttonRow).join("")}</div>
    <div class="meta" style="padding:8px 4px;color:var(--text-faint);font-size:13px">
      Эти кнопки меняются только в самом файле: там ваши комментарии и порядок,
      и программа их не переписывает.</div>` : ""}`;
}

/* Поля, зависящие от вида действия. Отдельная функция, потому что при
   смене вида перерисовывается только этот кусок — введённое имя и значок
   при этом обязаны сохраниться. */
function kindFields(draft) {
  const argvText = (draft.argv || []).join("\n");
  const program = `
    <div class="field">
      <label for="f-program">Программа</label>
      <input id="f-program" value="${esc((draft.argv || [])[0] || "")}" placeholder="obs">
      <div class="hint">Имя программы или полный путь. Без аргументов.</div>
    </div>
    <div class="field">
      <label for="f-args">Аргументы</label>
      <textarea id="f-args" placeholder="-c">${esc((draft.argv || []).slice(1).join("\n"))}</textarea>
      <div class="hint">По одному в строке. Это не командная строка:
        <code>&amp;&amp;</code>, <code>|</code> и <code>&gt;</code> здесь не работают —
        для такого положите скрипт на диск и выберите вид «Скрипт с диска».</div>
    </div>`;

  const workdir = `
    <div class="field">
      <label for="f-workdir">Рабочий каталог</label>
      <input id="f-workdir" value="${esc(draft.workdir || "")}" placeholder="~/проекты">
      <div class="hint">Необязательно. Отсюда команда начнёт работу.</div>
    </div>`;

  if (draft.kind === "desktop" || draft.kind === "exec") return program + workdir;

  if (draft.kind === "tmux") {
    return `
    <div class="field">
      <label for="f-session">Имя сессии</label>
      <input id="f-session" value="${esc(draft.session || "")}" placeholder="main">
      <div class="hint">Латиница, цифры, дефис. К этой сессии подключается веб-терминал.</div>
    </div>` + program + workdir;
  }

  if (draft.kind === "systemd_user" || draft.kind === "systemd_system") {
    const verbs = ["start", "stop", "restart", "reload", "status", "is-active"];
    return `
    <div class="field">
      <label for="f-unit">Юнит</label>
      <input id="f-unit" value="${esc(draft.unit || "")}" placeholder="minecraft.service">
    </div>
    <div class="field">
      <label for="f-verb">Что сделать</label>
      <select id="f-verb">${verbs
        .map((v) => `<option value="${v}" ${draft.verb === v ? "selected" : ""}>${v}</option>`)
        .join("")}</select>
    </div>`;
  }

  return `
    <div class="field">
      <label for="f-script">Путь к скрипту</label>
      <input id="f-script" value="${esc(draft.script || "")}" placeholder="/home/имя/bin/backup.sh">
      <div class="hint">Абсолютный путь к исполняемому файлу.</div>
    </div>
    <div class="field">
      <label for="f-args">Аргументы</label>
      <textarea id="f-args" placeholder="">${esc((draft.args || []).join("\n"))}</textarea>
      <div class="hint">По одному в строке.</div>
    </div>` + workdir;
}

function buttonForm(pc) {
  const draft = state.buttonForm;
  const isNew = !draft.id;

  return `
  <section class="card">
    <div class="card-head"><h2>${isNew ? "Новая кнопка" : "Правка кнопки"}</h2></div>

    ${draft.error ? `<div class="form-error">${esc(draft.error)}</div>` : ""}

    <div class="sheet-form">
      <div class="field">
        <label for="f-name">Название</label>
        <input id="f-name" value="${esc(draft.name || "")}" placeholder="OBS Studio" autofocus>
      </div>

      <div class="field">
        <label for="f-icon">Значок</label>
        <input id="f-icon" value="${esc(draft.icon || "")}" placeholder="🎥" maxlength="8">
        <div class="hint">Один эмодзи. Он и будет виден на пульте.</div>
      </div>

      <div class="field">
        <label for="f-group">Группа</label>
        <input id="f-group" value="${esc(draft.group || "")}" placeholder="Стрим">
        <div class="hint">Необязательно. Кнопки одной группы встают на свой лист пульта.</div>
      </div>

      <div class="field">
        <label for="f-kind">Вид</label>
        <select id="f-kind">${Object.entries(KIND_NAMES)
          .map(([k, label]) => `<option value="${k}" ${draft.kind === k ? "selected" : ""}>${esc(label)}</option>`)
          .join("")}</select>
        <div class="hint">${esc(KIND_HINTS[draft.kind] || "")}</div>
      </div>

      ${kindFields(draft)}

      <div class="kv">
        <div>
          <span class="label">Спрашивать перед запуском</span>
          <button class="switch ${draft.dangerous ? "on" : ""}" id="f-dangerous"
            aria-pressed="${draft.dangerous ? "true" : "false"}"></button>
        </div>
      </div>
    </div>

    <div class="row">
      <button class="btn" id="button-cancel">Отмена</button>
      <button class="btn primary" id="button-save">Сохранить</button>
    </div>
    ${isNew ? "" : `<div class="row"><button class="btn danger" id="button-delete">Удалить кнопку</button></div>`}
  </section>`;
}

/* Собирает описание из полей формы. Значения читаются из DOM, а не
   накапливаются на каждое нажатие клавиши: так форму нельзя рассинхронить
   с тем, что человек видит. */
function collectForm() {
  const draft = state.buttonForm;
  const value = (id) => el(id)?.value.trim() ?? "";
  const lines = (id) =>
    (el(id)?.value || "").split("\n").map((s) => s.trim()).filter(Boolean);

  const body = {
    name: value("f-name"),
    kind: draft.kind,
    dangerous: draft.dangerous || false,
  };
  const icon = value("f-icon");
  const group = value("f-group");
  const workdir = value("f-workdir");
  if (icon) body.icon = icon;
  if (group) body.group = group;
  if (workdir) body.workdir = workdir;

  if (draft.kind === "systemd_user" || draft.kind === "systemd_system") {
    body.unit = value("f-unit");
    body.verb = value("f-verb");
  } else if (draft.kind === "shell_script") {
    body.script = value("f-script");
    body.args = lines("f-args");
  } else {
    const program = value("f-program");
    body.argv = program ? [program, ...lines("f-args")] : [];
    if (draft.kind === "tmux") body.session = value("f-session");
  }
  return body;
}

/* То же самое, но чтобы не потерять введённое при смене вида. */
function stashForm() {
  const draft = state.buttonForm;
  if (!draft) return;
  Object.assign(draft, collectForm());
}

async function loadEditor(force = false) {
  const pc = editorPc();
  if (!pc) return;
  if (state.editor && !force) return;
  state.editor = await api(`/api/pcs/${encodeURIComponent(pc.id)}/action-editor`).catch(() => ({
    enabled: false,
    actions: [],
  }));
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
    <div class="card-head"><h2>Вход в компьютер</h2></div>
    <div class="row"><button class="btn" id="more-session"
      ${state.approvalsEnabled ? "" : "disabled"}>🔓 Разрешить следующий вход</button></div>
    <div class="meta">${state.approvalsEnabled
      ? "Нажмите перед тем, как идти к компьютеру: следующий вход пройдёт без пароля. Разрешение сгорает через пару минут и после первого использования."
      : "Выключено. Включается в конфигурации агента: approvals.enabled — и настройкой PAM, см. справку."}</div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Приложение на телефон</h2></div>
    <div class="row"><button class="btn" id="more-apk">📲 Скачать APK</button></div>
    <div class="meta" id="apk-note">Значок на рабочем столе вместо вкладки браузера.
      Дальше приложение обновляется само: при запуске спрашивает эту же машину.</div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Свои кнопки</h2></div>
    <div class="row"><button class="btn" data-go="buttons">🎛 Настроить кнопки пульта</button></div>
    <div class="meta">Добавить свою кнопку: запуск приложения, службы или команды в tmux.</div>
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
    <div class="row">
      <button class="btn" id="more-logout">🚪 Выйти</button>
      <button class="btn danger" id="more-logout-all">🧹 Выйти на всех устройствах</button>
    </div>
    <div class="meta">Второе — если телефон потерялся: завершит сессии везде,
      включая это устройство. Войти заново придётся всюду.</div>
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

    // Запросы на подтверждение спрашиваем у активного ПК на каждой
    // перерисовке: человек уже стоит у компьютера и ждёт ответа, задержка
    // здесь заметнее, чем лишний запрос по локальной сети.
    const pc = activePc();
    if (pc && pc.state === "online") {
      const list = await api(`/api/pcs/${encodeURIComponent(pc.id)}/approvals`).catch(() => null);
      state.approvals = list?.items || [];
      state.approvalsEnabled = list?.enabled ?? false;
    } else {
      state.approvals = [];
    }
    if (current === "buttons") await loadEditor(force);

    // Лист, на котором стоит палец, при обновлении данных сбрасываться
    // не должен.
    const pager = el("pager");
    const offset = pager ? pager.scrollLeft : 0;

    syncChrome();
    el("view").innerHTML = approvalBlock() + ROUTES[current].view();

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

/* Смена вида действия меняет набор полей. Введённое до этого сохраняем:
   человек уже написал название и значок, терять их из-за смены вида нельзя. */
document.addEventListener("change", (event) => {
  if (event.target.id !== "f-kind" || !state.buttonForm) return;
  stashForm();
  state.buttonForm.kind = event.target.value;
  state.buttonForm.error = null;
  render(true);
});

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
      const ok = await confirmPower(pc, what);
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

  /* --- свои кнопки --- */
  if (d.approve) {
    const ok = d.ok === "1";
    buzz(ok ? 12 : 6);
    return run(button,
      () => api(`/api/pcs/${encodeURIComponent(activePc().id)}/approvals/${encodeURIComponent(d.approve)}`,
        { method: "POST", body: JSON.stringify({ approved: ok }) }),
      () => {
        toast(ok ? "Подтверждено" : "Отклонено", ok ? "ok" : "err");
        render(true);
      });
  }

  if (button.id === "more-session") {
    return run(button,
      () => api(`/api/pcs/${encodeURIComponent(activePc().id)}/approvals/session`, { method: "POST" }),
      (approval) => toast(`Следующий вход без пароля — ${approval.seconds_left} с`, "ok"));
  }

  if (button.id === "more-logout-all") {
    const ok = await confirmSheet({
      icon: "🧹",
      title: "Выйти на всех устройствах?",
      text: "Все сессии будут завершены, включая эту. Придётся войти заново везде.",
      yes: "Выйти везде",
    });
    if (!ok) return;
    return run(button, () => api("/api/auth/logout-everywhere", { method: "POST" }),
      () => { toast("Все сессии завершены", "ok"); showLogin(); });
  }

  if (button.id === "more-apk") {
    // Ссылку открываем в новой вкладке, а не через fetch: файл должен
    // уйти в «Загрузки» браузера, а не в память страницы.
    return run(button, async () => {
      const release = await api("/api/app/latest");
      window.location.href = "/api/app/download";
      return release;
    }, (release) => toast(`Версия ${release.version_name}`, "ok"));
  }

  if (button.id === "button-add") {
    const pc = editorPc();
    const limit = state.editor?.max_actions ?? 64;
    if ((pc?.actions || []).filter((a) => a.editable).length >= limit) {
      return toast(`Больше ${limit} своих кнопок нельзя`, "err");
    }
    state.buttonForm = { kind: "desktop", dangerous: false };
    state.form.open = true;
    return render(true);
  }
  if (d.editButton) {
    const found = (state.editor?.actions || []).find((a) => a.id === d.editButton);
    if (!found) return toast("не нашёл описание этой кнопки", "err");
    // Копия, а не сама запись: отмена должна оставлять список нетронутым.
    state.buttonForm = JSON.parse(JSON.stringify(found));
    state.form.open = true;
    return render(true);
  }
  if (button.id === "f-dangerous") {
    stashForm();
    state.buttonForm.dangerous = !state.buttonForm.dangerous;
    button.classList.toggle("on", state.buttonForm.dangerous);
    button.setAttribute("aria-pressed", state.buttonForm.dangerous ? "true" : "false");
    buzz(6);
    return;
  }
  if (button.id === "button-cancel") {
    state.buttonForm = null;
    state.form.open = false;
    return render(true);
  }
  if (button.id === "button-save") {
    const pc = editorPc();
    const draft = state.buttonForm;
    const body = collectForm();
    if (!body.name) {
      draft.error = "Без названия кнопку не найти на пульте";
      Object.assign(draft, body);
      return render(true);
    }
    const id = draft.id || slugify(body.name);
    return run(button,
      () => api(`/api/pcs/${encodeURIComponent(pc.id)}/action-editor/${encodeURIComponent(id)}`,
        { method: "PUT", body: JSON.stringify(body) }),
      async () => {
        state.buttonForm = null;
        state.form.open = false;
        toast(draft.id ? "Кнопка изменена" : "Кнопка добавлена", "ok");
        await loadEditor(true);
        render(true);
      });
  }
  if (button.id === "button-delete") {
    const pc = editorPc();
    const draft = state.buttonForm;
    const ok = await confirmSheet({
      icon: "🗑",
      title: `Удалить «${draft.name}»?`,
      text: "Кнопка исчезнет с пульта. Сама программа на компьютере останется.",
      yes: "Удалить",
    });
    if (!ok) return;
    return run(button,
      () => api(`/api/pcs/${encodeURIComponent(pc.id)}/action-editor/${encodeURIComponent(draft.id)}`,
        { method: "DELETE" }),
      async () => {
        state.buttonForm = null;
        state.form.open = false;
        toast("Кнопка удалена", "ok");
        await loadEditor(true);
        render(true);
      });
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
    const ok = await confirmPower(pc, d.power);
    if (!ok) return;
    return run(button, () => api(`/api/pcs/${encodeURIComponent(d.pc)}/${d.power}`, { method: "POST" }),
      (result) => {
        toast(result.message || "команда отправлена", result.success ? "ok" : "err");
        setTimeout(() => render(true), 2000);
      });
  }

  /* --- сторож --- */
  if (d.guard) {
    const on = d.guard === "on";
    if (!on) {
      const ok = await confirmSheet({
        icon: "🚫",
        title: "Выключить слежку?",
        text: "Плата перестанет следить за компьютером и не поднимет его, если он погаснет, "
            + "пока тебя нет дома. Настройка сохраняется в плате и переживёт её перезагрузку.",
        yes: "Выключить",
      });
      if (!ok) return;
    }
    return run(button,
      () => api("/api/esp32/guard", { method: "POST", body: JSON.stringify({ enabled: on }) }),
      () => {
        toast(on ? "Сторож снова следит" : "Сторож выключен", on ? "ok" : "err");
        render(true);
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
