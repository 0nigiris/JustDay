"use strict";
/* Стенд оформления: ?screen=... оставляет на экране один блок, чтобы снять
   картинку для README. Без параметра видно всё сразу — так удобнее работать.

   Отдельным файлом, а не в разметке: у интерфейса строгий CSP (script-src 'self'),
   и встроенный скрипт браузер просто не выполнит — как и в самом приложении. */
addEventListener("DOMContentLoaded", () => {
  const want = new URLSearchParams(location.search).get("screen");
  const stage = document.getElementById("stage");

  // Стримдек живёт отдельным слоем: он занимает весь экран и рисуется вместо
  // приложения, ровно как при повороте телефона.
  if (want === "stage") {
    document.body.dataset.mode = "deck";
    document.getElementById("main").remove();
    stage.hidden = false;
    return;
  }
  stage.remove();

  if (!want) return;
  for (const node of document.querySelectorAll("[data-screen]")) {
    if (node.dataset.screen !== want) node.remove();
  }
  const titles = { jarvis: "JustDay", deck: "Пульт", pcs: "Компьютеры" };
  document.body.dataset.route = want;
  document.getElementById("page-title").textContent = titles[want] || "JustDay";
  document.getElementById("page-title-sm").textContent = titles[want] || "JustDay";
  for (const tab of document.querySelectorAll(".tab")) {
    const on = tab.textContent.trim() === titles[want];
    tab.classList.toggle("on", on);
  }
});
