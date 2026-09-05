"use strict";
/* Веб-терминал. Подключается к контроллеру, который проксирует поток на
 * агент. Токен агента в браузер никогда не попадает. */

const params = new URLSearchParams(location.search);
const pcId = params.get("pc");
const sessionName = params.get("session");

const titleEl = document.getElementById("term-title");
const dotEl = document.getElementById("term-dot");

if (!pcId) {
  titleEl.textContent = "не указан ПК";
  throw new Error("параметр pc обязателен");
}
titleEl.textContent = `${pcId}${sessionName ? " / " + sessionName : ""}`;

const term = new Terminal({
  fontSize: 13,
  fontFamily: 'ui-monospace, "JetBrains Mono", "Fira Code", Menlo, monospace',
  cursorBlink: true,
  scrollback: 5000,
  // Курсор и выделение крупнее: пальцем попасть тяжелее, чем мышью.
  theme: {
    background: "#000000",
    foreground: "#e6e9ef",
    cursor: "#4c8dff",
    selectionBackground: "#2a4a7f",
  },
});

const fitAddon = new FitAddon.FitAddon();
term.loadAddon(fitAddon);
term.open(document.getElementById("term"));
fitAddon.fit();

function setState(state) {
  dotEl.className = `dot ${state}`;
}

setState("connecting");
term.writeln("\x1b[90mподключение…\x1b[0m");

const wsUrl = new URL(`/api/pcs/${encodeURIComponent(pcId)}/terminal/ws`, location.href);
wsUrl.protocol = location.protocol === "https:" ? "wss:" : "ws:";
wsUrl.searchParams.set("cols", String(term.cols));
wsUrl.searchParams.set("rows", String(term.rows));
if (sessionName) wsUrl.searchParams.set("session", sessionName);

let socket = null;
let reconnectDelay = 1000;
let closedByUser = false;

function connect() {
  socket = new WebSocket(wsUrl);

  socket.onopen = () => {
    setState("connecting");
    reconnectDelay = 1000;
  };

  socket.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    switch (message.type) {
      case "ready":
        setState("online");
        term.clear();
        sendResize();
        break;
      case "output":
        term.write(message.data || "");
        break;
      case "error":
        setState("error");
        term.writeln(`\r\n\x1b[31m${message.data || "ошибка"}\x1b[0m`);
        break;
      case "exit":
        setState("offline");
        term.writeln("\r\n\x1b[90mсессия завершена\x1b[0m");
        break;
      default:
        break;
    }
  };

  socket.onclose = (event) => {
    setState("offline");
    if (closedByUser) return;
    if (event.code === 4401) {
      term.writeln("\r\n\x1b[31mтребуется вход\x1b[0m");
      setTimeout(() => (location.href = "/"), 1500);
      return;
    }
    if (event.code === 4403) {
      term.writeln(`\r\n\x1b[31m${event.reason || "терминал запрещён"}\x1b[0m`);
      return;
    }
    // Обрыв связи — обычное дело на телефоне. Процессы в tmux при этом
    // продолжают работать, поэтому просто переподключаемся.
    term.writeln(
      `\r\n\x1b[33mсвязь потеряна, переподключение через ${Math.round(reconnectDelay / 1000)} с…\x1b[0m`,
    );
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  };
}

const send = (payload) => {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
};

const sendResize = () => send({ type: "resize", cols: term.cols, rows: term.rows });

term.onData((data) => send({ type: "input", data }));

let resizeTimer = null;
const scheduleFit = () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    fitAddon.fit();
    sendResize();
  }, 150);
};

window.addEventListener("resize", scheduleFit);
// На телефоне появление клавиатуры меняет видимую область, а не окно.
window.visualViewport?.addEventListener("resize", scheduleFit);

for (const button of document.querySelectorAll(".term-keys button")) {
  button.addEventListener("click", () => {
    // data-send хранит escape-последовательности в исходном виде.
    const raw = button.dataset.send.replace(/\\x([0-9a-f]{2})/gi, (_, hex) =>
      String.fromCharCode(parseInt(hex, 16)),
    ).replace(/\\t/g, "\t");
    send({ type: "input", data: raw });
    term.focus();
  });
}

window.addEventListener("beforeunload", () => {
  closedByUser = true;
  socket?.close();
});

connect();
