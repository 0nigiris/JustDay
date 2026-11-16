// Kubai Icons (MIT, github.com/kubai087/kubai-icons) → полоски кадров PNG для QML.
//
// Иконки Kubai рисуются SVG с фильтрами (тень, блик) и двигаются JS-скриптом в браузерном DOM. Qt не
// умеет ни SVG-фильтры, ни этот скрипт, а тащить в островок браузер ради значков — тяжело (и на
// Windows тоже). Поэтому заранее: jsdom прогоняет draw() иконки на N шагах наведения, resvg рисует
// каждый кадр, кадры ложатся в одну полоску. QML (KubaiIcon.qml) листает её по кадрам.
//
// Запуск (зависимости — во временной папке, не в репозитории):
//   npm i --prefix ДИР kubai-icons @resvg/resvg-js jsdom
//   node scripts/kubai-sprites.mjs ДИР island/icons/kubai имя[=наше]:#цвет …
import { createRequire } from 'node:module';
import { mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [dir, out, ...specs] = process.argv.slice(2);
const req = createRequire(join(dir, 'node_modules', 'x.js'));
const imp = (m) => import(pathToFileURL(req.resolve(m)).href);
const { toSvg } = await imp('kubai-icons');
const { Resvg } = req('@resvg/resvg-js');
const { JSDOM } = req('jsdom');

const FRAMES = 16, SIZE = 64;   // 64 px — значок до 32 px на экране с двойной плотностью
const hex = (c) => c.replace('#', '').match(/../g).map((h) => parseInt(h, 16));
const mix = (a, p, b) => '#' + hex(a).map((v, i) => Math.round(v * p + hex(b)[i] * (1 - p))
  .toString(16).padStart(2, '0')).join('');

// resvg не знает CSS-переменных и color-mix() — считаем цвета сами. color-mix бывает вложенным
// (тень от тени), поэтому разворачиваем изнутри, пока есть что разворачивать.
const full = (c) => (c.length === 4 ? c.replace(/(\w)/g, '$1$1') : c);
function resolve(svg, color) {
  svg = svg
    .replace(/var\(--ki-e,var\(--ki-c,currentColor\)\)/g, color)
    .replace(/var\(--ki-c,currentColor\)/g, color)
    .replace(/var\(--ki-[a-z],([^()]*)\)/g, '$1')
    .replace(/currentColor/g, color);
  const mixRe = /color-mix\(in srgb,(#[0-9a-f]{3,6})(?: ([\d.]+)%)?,(#[0-9a-f]{3,6})(?: ([\d.]+)%)?\)/gi;
  for (let prev = ''; prev !== svg;) {
    prev = svg;
    svg = svg.replace(mixRe, (_, a, p, b, q) => {
      const pa = p !== undefined ? p / 100 : q !== undefined ? 1 - q / 100 : 0.5;
      return mix(full(a), pa, full(b));
    });
  }
  return svg;
}

mkdirSync(out, { recursive: true });
for (const spec of specs) {
  // «volume=volume-2:#0a84ff» — у Kubai одно имя, у нас (JD.glyph) другое
  const [names, color] = spec.split(':');
  const [src, name = src] = names.split('=');
  const icon = (await imp(`kubai-icons/icons/${src}`)).default;
  const a = icon.target ? icon.target(false) : {}, b = icon.target ? icon.target(true) : {};
  const frames = [];
  for (let i = 0; i < FRAMES; i++) {
    const t = i / (FRAMES - 1);
    const dom = new JSDOM(`<body>${toSvg(icon, { color, size: SIZE, id: `f${i}` })}</body>`);
    const svg = dom.window.document.querySelector('svg');
    const E = {};
    for (const el of svg.querySelectorAll('[data-n]')) E[el.getAttribute('data-n')] = el;
    const p = {};
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
      const x = a[k] ?? 0, y = b[k] ?? x;
      p[k] = typeof x === 'number' && typeof y === 'number' ? x + (y - x) * t : (t < 0.5 ? x : y);
    }
    if (icon.draw) icon.draw(p, E);
    svg.setAttribute('x', String(i * SIZE));
    frames.push(svg.outerHTML);
  }
  const strip = `<svg xmlns="http://www.w3.org/2000/svg" width="${SIZE * FRAMES}" height="${SIZE}">${frames.join('')}</svg>`;
  const png = new Resvg(resolve(strip, color)).render().asPng();
  writeFileSync(join(out, `${name}-${color.slice(1)}.png`), png);
  console.log(name, color, png.length);
}

// Список готовых полосок: QML показывает Kubai только там, где файл есть, иначе — прежний значок
const have = readdirSync(out).filter((f) => f.endsWith('.png')).map((f) => f.slice(0, -4)).sort();
writeFileSync(join(out, 'list.js'), `// Создано scripts/kubai-sprites.mjs, руками не править.\n.pragma library\nvar frames = ${FRAMES};\nvar size = ${SIZE};\nvar have = ${JSON.stringify(Object.fromEntries(have.map((h) => [h, true])))};\n`);
