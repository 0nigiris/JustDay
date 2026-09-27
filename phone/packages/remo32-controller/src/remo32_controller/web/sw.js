/* Оболочка пульта, которая открывается всегда.

   Раньше приложение без компьютера было пустым экраном с ошибкой сети: в
   дороге его незачем было и открывать. Теперь разметка, стили, скрипт и
   значки лежат в кэше браузера, и приложение поднимается без связи — с
   честной надписью «компьютер не в сети» и с возможностью оставить
   сообщение, которое уйдёт, когда компьютер появится.

   Данные (всё под /api) не кэшируются никогда: показать вчерашнюю
   температуру процессора как сегодняшнюю хуже, чем не показать ничего. */

const VERSION = "__ASSET_VERSION__";
const CACHE = `remo32-${VERSION}`;
const SHELL = __PRECACHE__;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

/* Страница: сначала сеть (чтобы новая версия приезжала сама), при неудаче —
   то, что лежит в кэше. Статика: сразу из кэша, а обновление подтягивается
   в фоне. Запросы к данным сюда вообще не заходят. */
self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(shellKey(url), copy));
          return response;
        })
        .catch(() => caches.match(shellKey(url)).then((hit) => hit || caches.match("/"))),
    );
    return;
  }

  event.respondWith(
    caches.match(request, { ignoreSearch: true }).then((hit) => {
      const fresh = fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => hit);
      return hit || fresh;
    }),
  );
});

/* Ключ для страницы: и «/», и «/terminal» — свои страницы, а параметры
   в адресе (сессия терминала) на содержимое не влияют. */
function shellKey(url) {
  return url.pathname === "/terminal" ? "/terminal" : "/";
}
