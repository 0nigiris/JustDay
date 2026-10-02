// Лестница нейросетей для OpenCode.
//
// Зачем. Обычный клиент к одной модели и привязан: кончился лимит — работа встала, и дальше её
// двигает человек руками. А лимит кончается предсказуемо, раз в несколько часов, и всё это время
// рядом стоят другие модели, которые прекрасно доделают начатое.
//
// Что делает. Держит поставщиков лестницей: наверху тот, кем хочется думать всегда, ниже — те, кем
// можно, пока верхний молчит. Отказ, похожий на лимит, спускает на ступень вниз и говорит об этом.
// Пока мы внизу, раз в четверть часа у верхнего спрашивают одним словом: «ты уже отвечаешь?»
// Ответил — поднимаемся обратно. Молчит — работаем дальше там, где работаем.
//
// Почему спрашивают, а не ждут по часам. Угадать миг возвращения лимита нечем: об этом не говорят
// внятно. Угадывание стоит отказа посреди разговора, проверка — одного слова.
//
// Третья ступень снизу — крошечная модель для мелочей: «который час», «спасибо», «повтори». Такое
// не стоит и лёгкой облачной. Инструменты крошечной почти не даются, поэтому берётся она только
// там, где делать ничего не надо.
//
// Настройка лежит рядом: ~/.config/opencode/justday-ladder.json
//   { "ladder": ["anthropic/claude-opus-4-5", "openrouter/deepseek/deepseek-chat"],
//     "tiny": "ollama/qwen3:0.6b", "probeMinutes": 15, "quiet": false }
import { readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

const CONFIG = join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "opencode", "justday-ladder.json")
const AUTH = join(process.env.XDG_DATA_HOME || join(homedir(), ".local", "share"), "opencode", "auth.json")

// Ступень, на которую нечем войти, — не ступень, а провал. Поставщик без ключа отвечает обычной
// ошибкой, лестница считает её лимитом и спускается; разговор начинается с двух провалов подряд,
// и человек видит, что отвечает кто-то не тот. Поэтому ступени без входа пропускаются сразу.
//
// Про anthropic отдельно: войти в него подпиской Claude нельзя — с февраля 2026 Anthropic
// разрешает такой вход только своим Claude Code и claude.ai. Для оболочки это значит ключ API
// (платный по токенам) или ничего. Подписка остаётся там, где она разрешена: в самом Claude Code.
const ENV_KEY = {
  anthropic: "ANTHROPIC_API_KEY",
  openrouter: "OPENROUTER_API_KEY",
  groq: "GROQ_API_KEY",
  deepseek: "DEEPSEEK_API_KEY",
  openai: "OPENAI_API_KEY",
  google: "GEMINI_API_KEY",
}
// Местные модели живут на этой машине: им вход не нужен, нужен запущенный ollama.
const LOCAL = new Set(["ollama", "lmstudio", "llamacpp", "local"])

// Лимит и обрыв связи — разные беды. При лимите есть куда пойти: соседняя модель в том же
// интернете работает. При обрыве идти некуда, и спускаться по лестнице бессмысленно — внизу тот же
// самый оборванный интернет.
const LIMIT = /(rate[_ ]?limit|usage limit|quota|credit|insufficient|billing|payment required|429|529|overloaded|capacity|too many requests|limit reached|exhaust)/i
const NETWORK = /(connection refused|network is unreachable|name or service not known|etimedout|enotfound|socket hang up)/i

// Мелочь, которой хватит крошечной модели: короткая фраза без просьбы что-то сделать. Правило
// нарочно робкое — ошибиться в сторону «отдать нормальной модели» дёшево, в обратную нет.
const DOING = /(открой|запусти|включи|выключи|закрой|найди|поставь|сделай|напиши|перепиши|почини|разбер|собери|поищи|open|run|write|fix|refactor|search|install|deploy|commit)/i

const defaults = {
  ladder: ["anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5", "anthropic/claude-haiku-4-5"],
  tiny: "",
  probeMinutes: 15,
  tinyMaxChars: 80,
  quiet: false,
}

function split(name) {
  const at = String(name || "").indexOf("/")
  if (at <= 0) return null
  return { providerID: name.slice(0, at), modelID: name.slice(at + 1) }
}

function logged() {
  try {
    return JSON.parse(readFileSync(AUTH, "utf8")) || {}
  } catch {
    return {}
  }
}

// Есть ли чем войти на эту ступень: запись в auth.json оболочки или ключ в окружении (его кладёт
// `justday shell`, достав из связки ключей рабочего стола).
function reachable(name, auth) {
  const p = split(name)?.providerID
  if (!p) return false
  if (LOCAL.has(p)) return true
  if (auth[p]) return true
  const env = ENV_KEY[p]
  return !!(env && process.env[env])
}

function settings() {
  let cfg
  try {
    cfg = { ...defaults, ...JSON.parse(readFileSync(CONFIG, "utf8")) }
  } catch {
    cfg = { ...defaults }
  }
  const all = (cfg.ladder || []).map(String)
  const auth = logged()
  const live = all.filter((n) => reachable(n, auth))
  // Если войти нечем вообще никуда — оставляем лестницу как есть: пусть лучше скажет ошибку
  // поставщика, чем молча не ответит ничего.
  cfg.ladder = live.length ? live : all
  cfg.skipped = all.filter((n) => !live.includes(n))
  if (cfg.tiny && !reachable(cfg.tiny, auth)) cfg.tiny = ""
  return cfg
}

function textOf(parts) {
  return (parts || []).filter((p) => p && p.type === "text").map((p) => p.text || "").join(" ").trim()
}

export const JustDayLadder = async ({ client }) => {
  let cfg = settings()
  let step = 0            // на какой ступени стоим: 0 — наверху
  let fellAt = 0          // когда спустились
  let probedAt = 0        // когда в последний раз спрашивали верхнего
  let probing = false
  let scratch = ""        // отдельная сессия для проверок: в рабочую они лезть не должны
  let toldSkipped = false // про пропущенные ступени говорим один раз за запуск, а не каждый раз

  const say = async (text) => {
    if (cfg.quiet) return
    try {
      await client.tui.showToast({ body: { message: text, variant: "info" } })
    } catch {
      // Островка может и не быть — тогда просто молчим, это не повод ронять разговор.
    }
  }

  const here = () => split(cfg.ladder[Math.min(step, cfg.ladder.length - 1)])

  // Ту, что приходит на смену, надо ввести в курс дела. Она не видела ничего из того, что здесь
  // происходило, и начинать с «продолжай» — всё равно что не начинать. Заметка кладётся в разговор
  // без ответа: это контекст, а не реплика, и человеку отвечать на неё не надо.
  const handoff = async (sessionID, from, to) => {
    if (!sessionID) return
    const text = [
      `Модель сменилась: ${from} → ${to}. У верхней кончился лимит, работу продолжаешь ты.`,
      "Прочитай ПЕРЕДАЧА.md в корне проекта — там что делалось, что уже сделано, что дальше и чего",
      "делать нельзя. Веди этот файл дальше сам: отключиться можно в любую секунду.",
    ].join(" ")
    try {
      await client.session.prompt({
        path: { id: sessionID },
        body: { noReply: true, parts: [{ type: "text", text }] },
      })
    } catch {
      // Не вышло — не беда: заметка на диске всё равно лежит, и человек о смене уже знает.
    }
  }

  const down = async (why, sessionID) => {
    if (step >= cfg.ladder.length - 1) {
      await say("Лимит, а спускаться больше некуда — жду.")
      return false
    }
    step += 1
    fellAt = Date.now()
    probedAt = Date.now()
    const now = cfg.ladder[step]
    await say(`Лимит у ${cfg.ladder[step - 1]} — перешёл на ${now}.`)
    await handoff(sessionID, cfg.ladder[step - 1], now)
    return true
  }

  // Проверка верхнего: один крошечный вопрос в отдельной сессии. Переключать рабочую, чтобы
  // выяснить, что лимит ещё не вернулся, нельзя: это отказ посреди разговора ради любопытства.
  const probe = async () => {
    const want = split(cfg.ladder[0])
    if (!want) return false
    try {
      if (!scratch) {
        const made = await client.session.create({ body: { title: "justday: проверка лестницы" } })
        scratch = made?.data?.id || made?.id || ""
      }
      if (!scratch) return false
      const r = await client.session.prompt({
        path: { id: scratch },
        body: { model: want, parts: [{ type: "text", text: "ok" }] },
      })
      const said = JSON.stringify(r?.data ?? r ?? "")
      return !LIMIT.test(said)
    } catch (e) {
      return !LIMIT.test(String(e?.message || e))
    }
  }

  const up = async () => {
    if (step === 0 || probing) return
    const every = Math.max(1, Number(cfg.probeMinutes) || 15) * 60 * 1000
    if (Date.now() - probedAt < every) return
    probing = true
    probedAt = Date.now()
    try {
      if (await probe()) {
        const was = cfg.ladder[step]
        step = 0
        fellAt = 0
        await say(`${cfg.ladder[0]} снова отвечает — вернулся к нему с ${was}.`)
      }
    } finally {
      probing = false
    }
  }

  return {
    // Каждое новое сообщение уходит той модели, на которой мы сейчас стоим. Мелочь — крошечной.
    "chat.message": async (_input, output) => {
      cfg = settings()
      if (!toldSkipped && cfg.skipped.length) {
        toldSkipped = true
        await say(`Пропускаю ступени без входа: ${cfg.skipped.join(", ")}. Работаю с ${cfg.ladder[0]}.`)
      }
      const model = here()
      if (!model) return
      const words = textOf(output.parts)
      const tiny = cfg.tiny && words.length > 0 && words.length <= (cfg.tinyMaxChars || 80) && !DOING.test(words)
      const want = tiny ? split(cfg.tiny) : model
      if (want && output.message) output.message.model = want
    },

    event: async ({ event }) => {
      if (!event || !event.type) return
      if (event.type === "session.error") {
        const said = JSON.stringify(event.properties || event)
        if (NETWORK.test(said)) return      // внизу тот же оборванный интернет
        if (LIMIT.test(said)) await down(said, (event.properties || {}).sessionID)
        return
      }
      // Подниматься обратно можно только между делами: забрать работу у того, кто её делает,
      // посередине — значит её потерять. Нижний договаривает своё, и место занимает верхний.
      if (event.type === "session.idle") await up()
    },
  }
}

export default JustDayLadder
