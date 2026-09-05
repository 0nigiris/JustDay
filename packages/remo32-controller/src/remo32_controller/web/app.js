"use strict";
/* Remo32 — интерфейс.
 *
 * Без сборщика и без фреймворка: страница должна открываться мгновенно
 * даже на плохой мобильной связи, а править её должно быть можно
 * текстовым редактором.
 */

const STATE_LABEL = {
  online: "онлайн",
  offline: "выключен",
  unknown: "неизвестно",
  connecting: "подключается",
  error: "ошибка",
};

const el = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

/* ---------------------------------------------------------------- сеть */

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

/* ------------------------------------------------------------ уведомления */

function toast(message, kind = "", requestId = null) {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.innerHTML =
    esc(message) + (requestId ? `<span class="rid">запрос ${esc(requestId)}</span>` : "");
  el("toasts").append(node);
  setTimeout(() => {
    node.style.opacity = "0";
    setTimeout(() => node.remove(), 250);
  }, kind === "err" ? 6000 : 3000);
}

/* ------------------------------------------------------------------ вход */

async function refreshAuth() {
  const status = await api("/api/auth/status");
  if (status.authenticated) {
    showMain();
    return true;
  }
  showLogin(status);
  return false;
}

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

/* ------------------------------------------------------------ отрисовка */

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

function metric(label, value, percent = null, note = null) {
  const cls = percent == null ? "metric na" : "metric";
  const barClass = percent >= 90 ? "crit" : percent >= 70 ? "hot" : "";
  const bar =
    percent == null
      ? ""
      : `<div class="bar"><i class="${barClass}" style="width:${Math.min(100, percent)}%"></i></div>`;
  return `<div class="${cls}">
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
    metric("CPU", cpu == null ? "нет данных" : `${cpu.toFixed(0)}%`, cpu,
      cpuTemp != null ? `${cpuTemp.toFixed(0)}°` : null),
    metric("RAM", mem == null ? "нет данных" : `${mem.toFixed(0)}%`, mem,
      stats.memory?.total_bytes ? fmtBytes(stats.memory.total_bytes) : null),
  ];

  // GPU показываем только если он есть: пустая плитка «нет данных» бесполезна.
  if (gpu) {
    parts.push(
      metric("GPU", gpu.utilization_percent == null ? "—" : `${gpu.utilization_percent.toFixed(0)}%`,
        gpu.utilization_percent,
        gpu.temperature_celsius != null ? `${gpu.temperature_celsius.toFixed(0)}°` : null),
    );
  }
  if (rootDisk) {
    parts.push(metric("Диск", rootDisk.usage_percent == null ? "—" : `${rootDisk.usage_percent.toFixed(0)}%`,
      rootDisk.usage_percent, rootDisk.free_bytes ? `${fmtBytes(rootDisk.free_bytes)} своб.` : null));
  }
  parts.push(metric("Аптайм", fmtUptime(stats.uptime_seconds), null));

  return `<div class="metrics">${parts.join("")}</div>`;
}

function renderActions(pc) {
  if (!pc.actions?.length) return "";
  const groups = new Map();
  for (const action of pc.actions) {
    const key = action.group || "Действия";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(action);
  }

  let html = "";
  for (const [group, actions] of groups) {
    html += `<div class="group-title">${esc(group)}</div><div class="actions">`;
    for (const action of actions) {
      const unavailable = action.available === false;
      html += `<button class="act ${action.dangerous ? "danger" : ""}"
        data-pc="${esc(pc.id)}" data-action="${esc(action.id)}"
        ${unavailable ? "disabled" : ""}
        title="${esc(action.description || action.name)}">
        ${action.icon ? esc(action.icon) + " " : ""}${esc(action.name)}
      </button>`;
    }
    html += `</div>`;
  }
  return html;
}

function renderPc(pc) {
  const state = pc.state;
  const online = state === "online";

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
    if (pc.terminal_supported) {
      body += `<div class="group-title">Терминал</div><div class="actions">
        <button class="act primary" onclick="location.href='/terminal?pc=${encodeURIComponent(pc.id)}'">⌨️ Открыть</button>
      </div>`;
    }
    body += renderActions(pc);
    body += `<div class="row">
      <button class="act danger" data-power="restart" data-pc="${esc(pc.id)}">🔄 Перезагрузка</button>
      <button class="act danger" data-power="shutdown" data-pc="${esc(pc.id)}">⏻ Выключить</button>
    </div>`;
  } else if (pc.wake_supported) {
    body = `<div class="row">
      <button class="act primary" data-wake="${esc(pc.id)}">⏻ Включить</button>
    </div>`;
  } else {
    body = `<div class="meta">MAC-адрес не задан — разбудить нечем</div>`;
  }

  return `<section class="card ${pc.stale && online ? "stale" : ""}">
    <div class="card-head">
      <span class="dot ${esc(state)}"></span>
      <h2>${esc(pc.name)}</h2>
      <span class="state-label">${esc(STATE_LABEL[state] || state)}</span>
    </div>
    ${meta}
    ${body}
  </section>`;
}

function renderEsp32(status) {
  if (!status) return "";
  const sim = status.simulated
    ? `<div class="meta warn">режим симуляции: настоящее железо не подключено</div>`
    : "";
  const online = status.state === "online";

  let details = "";
  if (online) {
    const parts = [
      metric("Wi-Fi", status.wifi_rssi_dbm != null ? `${status.wifi_rssi_dbm} дБм` : "—", null,
        status.wifi_ssid || null),
      metric("Heap", fmtBytes(status.free_heap_bytes), null,
        status.psram_present ? "PSRAM есть" : "без PSRAM"),
      metric("Аптайм", fmtUptime(status.uptime_seconds), null),
    ];
    details = `<div class="metrics">${parts.join("")}</div>`;
    if (status.gpio?.length) {
      details += `<div class="group-title">GPIO</div><div class="actions">`;
      for (const pin of status.gpio) {
        const lvl = pin.level == null ? "?" : pin.level ? "1" : "0";
        details += `<button class="act" disabled title="${esc(pin.label || "")}">
          ${esc(pin.mode === "input" ? "⬅" : "➡")} ${pin.pin}: ${lvl}
        </button>`;
      }
      details += `</div>`;
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

/* --------------------------------------------------------------- сценарии */

let refreshing = false;

/* --- расписание ----------------------------------------------------------
 *
 * Правила редактируются прямо с телефона: время, дни недели, ПК и действие.
 * Список действий берётся из уже загруженных данных ПК — отдельного запроса
 * не нужно, а для выключенного ПК действий просто не будет, и это честно
 * показано в форме.
 */

const DAY_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

let lastSchedules = [];
let lastPcs = [];
let formOpen = false;
let formEditId = null;

function daysLabel(days) {
  if (!days.length || days.length === 7) return "ежедневно";
  if (String(days) === "0,1,2,3,4") return "будни";
  if (String(days) === "5,6") return "выходные";
  return days.map((d) => DAY_SHORT[d]).join(" ");
}

function actionsOf(pcId) {
  return lastPcs.find((p) => p.id === pcId)?.actions || [];
}

function actionLabel(pcId, actionId) {
  const action = actionsOf(pcId).find((a) => a.id === actionId);
  if (!action) return actionId;
  return `${action.icon ? action.icon + " " : ""}${action.name}`;
}

function renderScheduleRow(entry) {
  const pc = lastPcs.find((p) => p.id === entry.pc_id);
  const pcName = pc ? pc.name : entry.pc_id;

  let status = "";
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
    <div class="actions">
      <button class="act" data-sched-run="${esc(entry.id)}">▶ Выполнить сейчас</button>
      <button class="act" data-sched-edit="${esc(entry.id)}">✎ Изменить</button>
      <button class="act danger" data-sched-del="${esc(entry.id)}">🗑 Удалить</button>
    </div>
  </div>`;
}

function renderScheduleForm() {
  if (!formOpen) return "";
  const entry = formEditId ? lastSchedules.find((s) => s.id === formEditId) : null;
  const pcId = entry?.pc_id || lastPcs[0]?.id || "";
  const days = entry?.days || [];

  const pcOptions = lastPcs
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
    <div class="actions">
      <button class="act primary" type="submit">${entry ? "Сохранить" : "Добавить"}</button>
      <button class="act" type="button" id="sf-cancel">Отмена</button>
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
    .map(
      (a) =>
        `<option value="${esc(a.id)}" ${a.id === selectedActionId ? "selected" : ""}>${esc(
          (a.group ? a.group + ": " : "") + a.name,
        )}</option>`,
    )
    .join("");
}

function renderSchedules() {
  const rows = lastSchedules.length
    ? lastSchedules.map(renderScheduleRow).join("")
    : `<div class="empty">Расписаний нет. Например: погасить подсветку в 23:00.</div>`;

  return `
  <section class="card">
    <div class="card-head">
      <h2>⏰ Расписание</h2>
      ${formOpen ? "" : `<button class="icon-btn" id="sched-add" title="Добавить правило">+</button>`}
    </div>
    ${renderScheduleForm()}
    ${rows}
  </section>`;
}

async function render(force = false) {
  if (refreshing) return;
  // Живые обновления приходят каждые несколько секунд. Если в этот момент
  // перерисовать открытую форму, введённый текст пропадёт прямо под пальцем.
  if (formOpen && !force) return;
  refreshing = true;
  try {
    const [pcs, esp32, schedules] = await Promise.all([
      api("/api/pcs"),
      api("/api/esp32/status").catch(() => null),
      api("/api/schedules").catch(() => []),
    ]);

    lastPcs = pcs;
    lastSchedules = schedules;

    const html =
      (pcs.length
        ? pcs.map(renderPc).join("")
        : `<div class="empty">Ни одного ПК не настроено.<br>
           Добавьте секцию <code>[[pcs]]</code> в конфигурацию контроллера.</div>`) +
      renderSchedules() +
      renderEsp32(esp32);

    el("content").innerHTML = html;
    // Список действий заполняется после вставки разметки: он зависит от
    // выбранного в форме ПК, а не от порядка полей в шаблоне.
    if (formOpen) {
      fillActionSelect(lastSchedules.find((s) => s.id === formEditId)?.action_id);
    }
  } catch (error) {
    if (error.message !== "требуется вход") {
      el("content").innerHTML = `<div class="empty">Ошибка: ${esc(error.message)}</div>`;
    }
  } finally {
    refreshing = false;
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

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  if (button.dataset.action) {
    await withBusy(button, async () => {
      try {
        const result = await api(
          `/api/pcs/${encodeURIComponent(button.dataset.pc)}/actions/${encodeURIComponent(button.dataset.action)}`,
          { method: "POST" },
        );
        toast(result.message || (result.success ? "готово" : "не выполнено"),
          result.success ? "ok" : "err");
      } catch (error) {
        toast(error.message, "err", error.requestId);
      }
    });
    return;
  }

  if (button.id === "sched-add") {
    formOpen = true;
    formEditId = null;
    await render(true);
    return;
  }

  if (button.id === "sf-cancel") {
    formOpen = false;
    formEditId = null;
    await render(true);
    return;
  }

  if (button.dataset.day !== undefined) {
    button.classList.toggle("on");
    return;
  }

  if (button.dataset.schedEdit) {
    formOpen = true;
    formEditId = button.dataset.schedEdit;
    await render(true);
    return;
  }

  if (button.dataset.schedToggle) {
    const entry = lastSchedules.find((s) => s.id === button.dataset.schedToggle);
    await withBusy(button, async () => {
      try {
        await api(`/api/schedules/${encodeURIComponent(button.dataset.schedToggle)}`, {
          method: "PATCH",
          body: JSON.stringify({ enabled: !entry.enabled }),
        });
        await render(true);
      } catch (error) {
        toast(error.message, "err", error.requestId);
      }
    });
    return;
  }

  if (button.dataset.schedRun) {
    await withBusy(button, async () => {
      try {
        const entry = await api(`/api/schedules/${encodeURIComponent(button.dataset.schedRun)}/run`, {
          method: "POST",
        });
        toast(entry.last_ok ? "выполнено" : entry.last_message || "не выполнено",
          entry.last_ok ? "ok" : "err");
        await render(true);
      } catch (error) {
        toast(error.message, "err", error.requestId);
      }
    });
    return;
  }

  if (button.dataset.schedDel) {
    if (!confirm("Удалить правило?")) return;
    await withBusy(button, async () => {
      try {
        await api(`/api/schedules/${encodeURIComponent(button.dataset.schedDel)}`, {
          method: "DELETE",
        });
        toast("правило удалено", "ok");
        await render(true);
      } catch (error) {
        toast(error.message, "err", error.requestId);
      }
    });
    return;
  }

  if (button.dataset.wake) {
    await withBusy(button, async () => {
      try {
        const result = await api(`/api/pcs/${encodeURIComponent(button.dataset.wake)}/wake`, {
          method: "POST",
        });
        const ways = result.attempts.filter((a) => a.ok).map((a) => a.method).join(", ");
        toast(`Magic packet отправлен (${ways}). Ждём загрузки…`, "ok");
        setTimeout(render, 3000);
      } catch (error) {
        toast(error.message, "err", error.requestId);
      }
    });
    return;
  }

  if (button.dataset.power) {
    const isShutdown = button.dataset.power === "shutdown";
    if (!confirm(isShutdown ? "Выключить компьютер?" : "Перезагрузить компьютер?")) return;
    await withBusy(button, async () => {
      try {
        const result = await api(
          `/api/pcs/${encodeURIComponent(button.dataset.pc)}/${button.dataset.power}`,
          { method: "POST" },
        );
        toast(result.message || "команда отправлена", result.success ? "ok" : "err");
        setTimeout(render, 2000);
      } catch (error) {
        toast(error.message, "err", error.requestId);
      }
    });
  }
});


/* --- сохранение правила ---------------------------------------------------
 *
 * Слушатели повешены на document, а не на саму форму: разметка
 * пересоздаётся при каждой перерисовке, и обработчик на элементе умер бы
 * вместе с ней.
 */

document.addEventListener("change", (event) => {
  if (event.target.id === "sf-pc") fillActionSelect(null);
});

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

  const submitButton = event.target.querySelector("button[type=submit]");
  await withBusy(submitButton, async () => {
    try {
      if (formEditId) {
        await api(`/api/schedules/${encodeURIComponent(formEditId)}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        toast("правило сохранено", "ok");
      } else {
        // Идентификатор пользователю не нужен: он служит только адресом
        // записи в API и файле.
        payload.id = `s${Date.now().toString(36)}`;
        payload.enabled = true;
        await api("/api/schedules", { method: "POST", body: JSON.stringify(payload) });
        toast("правило добавлено", "ok");
      }
      formOpen = false;
      formEditId = null;
      await render(true);
    } catch (error) {
      toast(error.message, "err", error.requestId);
    }
  });
});

el("refresh-btn").addEventListener("click", () => render(true));

el("menu-btn").addEventListener("click", async () => {
  const status = await api("/api/auth/status");
  const options = ["1 — Зарегистрировать passkey на этом устройстве", "2 — Выйти", "3 — Открыть документацию API"];
  const choice = prompt(`Remo32 — меню\n\n${options.join("\n")}\n\nВведите номер:`);
  if (choice === "1") {
    if (!status.passkey_configured) {
      toast("Passkey не настроен: задайте auth.webauthn_rp_id и откройте интерфейс по HTTPS", "err");
      return;
    }
    await registerPasskey();
  } else if (choice === "2") {
    await api("/api/auth/logout", { method: "POST" });
    location.reload();
  } else if (choice === "3") {
    location.href = "/docs";
  }
});

/* --- живые обновления ---------------------------------------------------- */

let eventSource = null;

function connectEvents() {
  eventSource?.close();
  eventSource = new EventSource("/api/events");

  eventSource.addEventListener("hello", () => {
    el("conn-status").textContent = "живое обновление включено";
  });
  eventSource.addEventListener("update", render);
  eventSource.onerror = () => {
    el("conn-status").textContent = "переподключение…";
    // Браузер переподключает EventSource сам; наша задача — не мешать.
  };
}

async function start() {
  await render();
  connectEvents();
  // Подстраховка на случай, если события не дойдут: редкий фоновый опрос.
  setInterval(() => {
    if (!document.hidden) render();
  }, 15000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) render();
  });
}

(async () => {
  if (await refreshAuth()) await start();
})();
