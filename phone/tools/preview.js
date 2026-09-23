"use strict";
/* Стенд оформления: ?screen=... оставляет на экране один блок, чтобы снять
   картинку для README. Без параметра видно всё сразу — так удобнее работать.

   Отдельным файлом, а не в разметке: у интерфейса строгий CSP (script-src 'self'),
   и встроенный скрипт браузер просто не выполнит — как и в самом приложении. */
addEventListener("DOMContentLoaded", () => {
  const want = new URLSearchParams(location.search).get("screen");
  if (!want) return;
  for (const node of document.querySelectorAll("[data-screen]")) {
    if (node.dataset.screen !== want) node.remove();
  }
  const titles = { jarvis: "JustDay", deck: "Пульт", pcs: "Компьютеры" };
  document.getElementById("page-title").textContent = titles[want] || "JustDay";
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("on", tab.textContent.trim() === titles[want]);
  }
});
