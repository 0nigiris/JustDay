.pragma library
// Движок шаров состояний: thinking-orbs 0.3.1 (MIT, © 2026 Jakub Antalik, github.com/Jakubantalik/thinking-orbs),
// собран esbuild из src/engine/index.ts; единственная правка — вырезан MODE_DRAWS (см. ниже). Геометрию рисует island/Orb.qml.
"use strict";
var Orbs = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __getOwnPropSymbols = Object.getOwnPropertySymbols;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __propIsEnum = Object.prototype.propertyIsEnumerable;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __spreadValues = (a, b) => {
    for (var prop in b || (b = {}))
      if (__hasOwnProp.call(b, prop))
        __defNormalProp(a, prop, b[prop]);
    if (__getOwnPropSymbols)
      for (var prop of __getOwnPropSymbols(b)) {
        if (__propIsEnum.call(b, prop))
          __defNormalProp(a, prop, b[prop]);
      }
    return a;
  };
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // src/engine/index.ts
  var engine_exports = {};
  __export(engine_exports, {
    MODE_DRAWS: () => MODE_DRAWS,
    MODE_FRAMES: () => MODE_FRAMES,
    STATE_TO_MODE: () => STATE_TO_MODE,
    finalizeFrame: () => finalizeFrame,
    makeProj: () => makeProj,
    paint: () => paint,
    paintFrame: () => paintFrame,
    paintLines: () => paintLines,
    radiusScale: () => radiusScale,
    resolvePreset: () => resolvePreset
  });

  // src/engine/core.ts
  function lerp(a, b, f) {
    return a + (b - a) * f;
  }
  function frac(x) {
    return x - Math.floor(x);
  }
  function vnoise(x, y) {
    const xi = Math.floor(x);
    const yi = Math.floor(y);
    let fx = x - xi;
    let fy = y - yi;
    fx = fx * fx * (3 - 2 * fx);
    fy = fy * fy * (3 - 2 * fy);
    const a = hashD(xi, yi);
    const b = hashD(xi + 1, yi);
    const c = hashD(xi, yi + 1);
    const d = hashD(xi + 1, yi + 1);
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
  }
  function hashD(a, b) {
    const h = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
    return h - Math.floor(h);
  }
  function fibDir(i, n) {
    const golden = Math.PI * (3 - Math.sqrt(5));
    const y = 1 - 2 * (i + 0.5) / n;
    const rad = Math.sqrt(1 - y * y);
    const a = i * golden;
    return [rad * Math.cos(a), y, rad * Math.sin(a)];
  }
  function angleDelta(a, b) {
    return Math.atan2(Math.sin(a - b), Math.cos(a - b));
  }
  function makeProj(yaw, tilt, cx, cy, scale) {
    const st = Math.sin(tilt);
    const ct = Math.cos(tilt);
    const sy = Math.sin(yaw);
    const cyw = Math.cos(yaw);
    return (x, y, z) => {
      const x1 = x * cyw + z * sy;
      const z1 = -x * sy + z * cyw;
      const y1 = y * ct - z1 * st;
      const z2 = y * st + z1 * ct;
      return [cx + x1 * scale, cy - y1 * scale, z2];
    };
  }
  function paint(ctx, dots, dark, rMin = 0.3) {
    var _a;
    for (const d of dots) {
      const alpha = (_a = d.a) != null ? _a : 1;
      const w = Math.min(1, Math.max(0, d.white));
      const g = Math.round((dark ? 1 - w : w) * 255);
      ctx.fillStyle = `rgba(${g},${g},${g},${alpha})`;
      ctx.beginPath();
      ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  function paintLines(ctx, lines, dark) {
    var _a;
    for (const l of lines) {
      const alpha = (_a = l.a) != null ? _a : 1;
      const w = Math.min(1, Math.max(0, l.white));
      const g = Math.round((dark ? 1 - w : w) * 255);
      ctx.strokeStyle = `rgba(${g},${g},${g},${alpha})`;
      ctx.lineWidth = l.w;
      ctx.beginPath();
      ctx.moveTo(l.x1, l.y1);
      ctx.lineTo(l.x2, l.y2);
      ctx.stroke();
    }
  }
  function finalizeFrame(dots, lines, rMin = 0.3) {
    var _a;
    const visible = [];
    for (const d of dots) {
      if (((_a = d.a) != null ? _a : 1) < 0.02) continue;
      d.r = Math.max(rMin, d.r);
      visible.push(d);
    }
    visible.sort((a, b) => a.z - b.z);
    return { dots: visible, lines: lines.filter((l) => {
      var _a2;
      return ((_a2 = l.a) != null ? _a2 : 1) >= 0.02;
    }) };
  }
  function paintFrame(ctx, frame, dark) {
    if (frame.lines.length) paintLines(ctx, frame.lines, dark);
    paint(ctx, frame.dots, dark);
  }
  function radiusScale(size, pow) {
    return (size / 300) ** pow;
  }

  // src/engine/braid.ts
  var frameBraid = (size, t, o) => {
    var _a, _b, _c, _d, _e, _f;
    const cx = size / 2;
    const cy = size / 2;
    const R = size / 2 * 0.76;
    const pt = makeProj(t * 0.4, 0.3, cx, cy, 1);
    const rs = radiusScale(size, (_a = o.rsPow) != null ? _a : 0.6);
    const dots = [];
    const ghostN = (_b = o.ghostN) != null ? _b : 150;
    for (let i = 0; i < ghostN; i++) {
      const d = fibDir(i, ghostN);
      const [px, py, z] = pt(d[0] * R, d[1] * R, d[2] * R);
      const depth = (z / R + 1) / 2;
      dots.push({ x: px, y: py, z, r: 0.8 * rs, white: 0.78, a: 0.1 + 0.22 * depth });
    }
    const strandN = (_c = o.strandN) != null ? _c : 52;
    const turns = (_d = o.turns) != null ? _d : 3;
    for (let s = 0; s < 3; s++) {
      const phase = s / 3 * 2 * Math.PI;
      for (let i = 0; i < strandN; i++) {
        const u = (frac(i / strandN + t * 0.045) * 2 - 1) * 0.96;
        const surf = Math.sqrt(Math.max(0, 1 - u * u));
        const endFade = Math.min(1, (1 - Math.abs(u)) / 0.1);
        const a = u * Math.PI * turns + phase;
        const weave = 1 + 0.075 * Math.sin(u * Math.PI * turns * 2 + phase * 2 + t * 0.8);
        const rr = surf * R * weave;
        const [px, py, zr] = pt(Math.cos(a) * rr, u * R * weave, Math.sin(a) * rr);
        const depth = (zr / R + 1) / 2;
        dots.push({
          x: px,
          y: py,
          z: zr,
          r: (((_e = o.rBase) != null ? _e : 1.2) + ((_f = o.rDepth) != null ? _f : 1.8) * depth) * rs,
          white: 0.55 - 0.45 * depth,
          a: endFade * (0.45 + 0.55 * depth)
        });
      }
    }
    return finalizeFrame(dots, [], o.rMin);
  };

  // src/engine/lattice.ts
  function solveCycle(time, count, slotDur, rest) {
    const cyc = 2 * count * slotDur + rest;
    const tc = time % cyc;
    const amount = new Array(count).fill(0);
    let active = -1;
    if (tc < 2 * count * slotDur) {
      const slot = Math.floor(tc / slotDur);
      const p = (tc - slot * slotDur) / slotDur;
      const cl = Math.min(1, p / 0.7);
      const ep = 1 - (1 - cl) ** 3;
      if (slot < count) {
        for (let i = 0; i < slot; i++) amount[i] = 1;
        amount[slot] = ep;
        active = slot;
      } else {
        const u = 2 * count - 1 - slot;
        for (let i = 0; i < u; i++) amount[i] = 1;
        amount[u] = 1 - ep;
        active = u;
      }
    }
    return { amount, active };
  }
  function applyMoves(pt3, moves, sc) {
    let [x, y, z] = pt3;
    let inActive = false;
    for (let i = 0; i < moves.length; i++) {
      if (sc.amount[i] <= 0) continue;
      const mv = moves[i];
      const coord = mv.axis === 0 ? x : mv.axis === 1 ? y : z;
      if (coord < mv.lo || coord >= mv.hi) continue;
      if (i === sc.active) inActive = true;
      const a = mv.ang * sc.amount[i];
      const ca = Math.cos(a);
      const sa = Math.sin(a);
      if (mv.axis === 0) {
        const y2 = y * ca - z * sa;
        z = y * sa + z * ca;
        y = y2;
      } else if (mv.axis === 1) {
        const x2 = x * ca + z * sa;
        z = -x * sa + z * ca;
        x = x2;
      } else {
        const x2 = x * ca - y * sa;
        y = x * sa + y * ca;
        x = x2;
      }
    }
    return [x, y, z, inActive];
  }
  function makeMoves(count) {
    const moves = [];
    for (let i = 0; i < count; i++) {
      const axis = Math.min(2, Math.floor(hashD(i, 2.3) * 3));
      const lo = -1 + 0.5 * Math.min(3, Math.floor(hashD(i, 5.9) * 4));
      const dir = hashD(i, 7.7) < 0.5 ? 1 : -1;
      moves.push({ axis, lo, hi: lo + 0.5, ang: dir * Math.PI / 2 });
    }
    return moves;
  }
  var frameGlobe = (size, t, o) => {
    var _a, _b, _c, _d, _e, _f, _g, _h, _i, _j;
    const spin = 0.5;
    const cx = size / 2;
    const cy = size / 2;
    const radius = size / 2 * 0.82;
    const tilt = 0.4 + 0.06 * Math.sin(t * 0.35);
    const pt = makeProj(t * spin, tilt, cx, cy, radius);
    const scan = t * (spin + (1.7 - spin) * ((_a = o.scanMul) != null ? _a : 1));
    const rs = radiusScale(size, (_b = o.rsPow) != null ? _b : 0.6);
    const dimBase = (_c = o.dimBase) != null ? _c : 1;
    const dots = [];
    const latRings = (_d = o.latRings) != null ? _d : 17;
    const lonDensity = (_e = o.lonDensity) != null ? _e : 44;
    for (let li = 0; li <= latRings; li++) {
      const lat = -Math.PI / 2 + li / latRings * Math.PI;
      const cosLat = Math.cos(lat);
      const sinLat = Math.sin(lat);
      const lonCount = Math.max(1, Math.round(Math.abs(cosLat) * lonDensity));
      for (let lj = 0; lj < lonCount; lj++) {
        const lon = lj / lonCount * 2 * Math.PI;
        const [px, py, z] = pt(cosLat * Math.cos(lon), sinLat, cosLat * Math.sin(lon));
        const depth = (z + 1) / 2;
        const d = angleDelta(lon + t * spin, scan);
        const boost = Math.exp(-(d * d) / 0.18) * Math.max(0, z);
        dots.push({
          x: px,
          y: py,
          z,
          r: (((_f = o.rBase) != null ? _f : 0.6) + ((_g = o.rDepth) != null ? _g : 1.7) * depth + ((_h = o.rBoost) != null ? _h : 1) * boost) * rs,
          white: ((_i = o.inkFar) != null ? _i : 0.62) - ((_j = o.inkSpan) != null ? _j : 0.54) * depth,
          // dimBase < 1 fades un-scanned dots so the meridian reads clearly
          a: dimBase + (1 - dimBase) * Math.min(1, boost)
        });
      }
    }
    return finalizeFrame(dots, [], o.rMin);
  };
  var frameRubik = (size, t, o) => {
    var _a, _b, _c, _d, _e, _f, _g, _h, _i;
    const cx = size / 2;
    const cy = size / 2;
    const R = size / 2 * 0.82;
    const pt = makeProj(t * 0.55, 0.35 + 0.1 * Math.sin(t * 0.9), cx, cy, R);
    const rs = radiusScale(size, (_a = o.rsPow) != null ? _a : 0.6);
    const moveCount = (_b = o.moveCount) != null ? _b : 14;
    const moves = makeMoves(moveCount);
    const sc = solveCycle(t, moveCount, 0.42, 1.2);
    const dots = [];
    const latRings = (_c = o.latRings) != null ? _c : 15;
    const lonDensity = (_d = o.lonDensity) != null ? _d : 40;
    for (let li = 0; li <= latRings; li++) {
      const lat = -Math.PI / 2 + li / latRings * Math.PI;
      const cosLat = Math.cos(lat);
      const sinLat = Math.sin(lat);
      const lonCount = Math.max(1, Math.round(Math.abs(cosLat) * lonDensity));
      for (let lj = 0; lj < lonCount; lj++) {
        const lon = lj / lonCount * 2 * Math.PI;
        const [x, y, z, inActive] = applyMoves([cosLat * Math.cos(lon), sinLat, cosLat * Math.sin(lon)], moves, sc);
        const [px, py, zr] = pt(x, y, z);
        const depth = (zr + 1) / 2;
        dots.push({
          x: px,
          y: py,
          z: zr,
          r: (((_e = o.rBase) != null ? _e : 0.6) + ((_f = o.rDepth) != null ? _f : 1.7) * depth + (inActive ? (_g = o.rActive) != null ? _g : 0.3 : 0)) * rs,
          white: ((_h = o.inkFar) != null ? _h : 0.62) - ((_i = o.inkSpan) != null ? _i : 0.54) * depth - (inActive ? 0.14 : 0)
        });
      }
    }
    return finalizeFrame(dots, [], o.rMin);
  };
  var frameWave = (size, t, o) => {
    var _a, _b, _c, _d, _e;
    const cx = size / 2;
    const cy = size / 2;
    const R = size / 2 * 0.874;
    const pt = makeProj(t * 0.18, 0.38, cx, cy, 1);
    const rs = radiusScale(size, (_a = o.rsPow) != null ? _a : 0.6);
    const dots = [];
    const rings = (_b = o.rings) != null ? _b : 15;
    const lonDensity = (_c = o.lonDensity) != null ? _c : 40;
    for (let ri = 0; ri <= rings; ri++) {
      const lat = -Math.PI / 2 + ri / rings * Math.PI;
      const cosLat = Math.cos(lat);
      const sinLat = Math.sin(lat);
      const w = 0.62 * Math.sin(t * 2.1 - ri * 0.52) + 0.38 * Math.sin(t * 1.27 + ri * 0.83);
      const rr = R * (0.88 + 0.105 * w);
      const lonCount = Math.max(1, Math.round(Math.abs(cosLat) * lonDensity));
      for (let lj = 0; lj < lonCount; lj++) {
        const lon = lj / lonCount * 2 * Math.PI;
        const [px, py, z] = pt(cosLat * Math.cos(lon) * rr, sinLat * rr, cosLat * Math.sin(lon) * rr);
        const depth = (z / R + 1) / 2;
        const crest = Math.max(0, w);
        dots.push({
          x: px,
          y: py,
          z,
          r: (((_d = o.rBase) != null ? _d : 0.6) + ((_e = o.rDepth) != null ? _e : 1.7) * depth) * (1 + 0.4 * crest) * rs,
          white: 0.66 - 0.56 * depth - 0.1 * crest
        });
      }
    }
    return finalizeFrame(dots, [], o.rMin);
  };

  // src/engine/morph.ts
  function smoothE(x) {
    return x * x * (3 - 2 * x);
  }
  function polyPath(verts) {
    const V = verts.length;
    const L = [];
    let total = 0;
    for (let i = 0; i < V; i++) {
      const a = verts[i];
      const b = verts[(i + 1) % V];
      const l = Math.hypot(b[0] - a[0], b[1] - a[1]);
      L.push(l);
      total += l;
    }
    return (f) => {
      let target = f * total;
      let i = 0;
      while (target > L[i] && i < V - 1) {
        target -= L[i];
        i++;
      }
      const a = verts[i];
      const b = verts[(i + 1) % V];
      const ff = L[i] ? Math.min(1, target / L[i]) : 0;
      return [a[0] + (b[0] - a[0]) * ff, a[1] + (b[1] - a[1]) * ff];
    };
  }
  var CIRCLE = (f) => {
    const a = -Math.PI / 2 + f * 2 * Math.PI;
    return [Math.cos(a) * 0.24, Math.sin(a) * 0.24];
  };
  var TRIANGLE = polyPath([
    [0, -0.26],
    [0.24, 0.16],
    [-0.24, 0.16]
  ]);
  var SQUARE = polyPath([
    [0, -0.2],
    [0.2, -0.2],
    [0.2, 0.2],
    [-0.2, 0.2],
    [-0.2, -0.2]
  ]);
  var CYCLE = [CIRCLE, TRIANGLE, SQUARE];
  function morphN(d) {
    return Math.max(6, Math.round(34 * d));
  }
  var HOLD = 1.4;
  var MORPH = 0.9;
  var SEG = HOLD + MORPH;
  var frameMorph = (size, t, o) => {
    var _a, _b, _c;
    const K = CYCLE.length;
    const tc = t % (SEG * K);
    const k = Math.floor(tc / SEG);
    const local = tc - k * SEG;
    const m = local > HOLD ? smoothE((local - HOLD) / MORPH) : 0;
    const sprd = (_a = o.spread) != null ? _a : 1;
    const pA = CYCLE[k];
    const pB = CYCLE[(k + 1) % K];
    const M = 160;
    const pts = [];
    for (let i = 0; i < M; i++) {
      const f = i / M;
      const a = pA(f);
      const b = pB(f);
      pts.push([(a[0] + (b[0] - a[0]) * m) * sprd, (a[1] + (b[1] - a[1]) * m) * sprd]);
    }
    const L = [];
    let total = 0;
    for (let i = 0; i < M; i++) {
      const a = pts[i];
      const b = pts[(i + 1) % M];
      const l = Math.hypot(b[0] - a[0], b[1] - a[1]);
      L.push(l);
      total += l;
    }
    const n = morphN((_b = o.iconD) != null ? _b : 1);
    const re = ((_c = o.rDot) != null ? _c : 0.021) * 1.35 * sprd;
    const pulse = 1 + 0.02 * Math.sin(local * 3.1);
    const dots = [];
    const c2 = size / 2;
    let seg = 0;
    let acc = 0;
    for (let k2 = 0; k2 < n; k2++) {
      const target = k2 / n * total;
      while (acc + L[seg] < target && seg < M - 1) {
        acc += L[seg];
        seg++;
      }
      const a = pts[seg];
      const b = pts[(seg + 1) % M];
      const f = L[seg] ? Math.min(1, (target - acc) / L[seg]) : 0;
      const x = (a[0] + (b[0] - a[0]) * f) * pulse;
      const y = (a[1] + (b[1] - a[1]) * f) * pulse;
      dots.push({
        x: c2 + x * size,
        y: c2 + y * size,
        z: 0,
        r: Math.max(0.35, re * size),
        white: 0.1
      });
    }
    return finalizeFrame(dots, [], o.rMin);
  };

  // src/engine/orbits.ts
  var frameOrbits = (size, t, o) => {
    var _a, _b, _c, _d, _e, _f, _g, _h;
    const cx = size / 2;
    const cy = size / 2;
    const R = size / 2 * 0.82;
    const pt = makeProj(t * 0.12, 0.3, cx, cy, 1);
    const rs = radiusScale(size, (_a = o.rsPow) != null ? _a : 0.6);
    const dots = [];
    const orbitN = (_b = o.orbitN) != null ? _b : 12;
    const ghostN = (_c = o.ghostN) != null ? _c : 40;
    const particles = (_d = o.particles) != null ? _d : 3;
    for (let orb = 0; orb < orbitN; orb++) {
      const h1 = hashD(orb, 1.7);
      const h2 = hashD(orb, 5.2);
      const h3 = hashD(orb, 8.9);
      const ro = R * (0.45 + 0.52 * h1);
      const th = h1 * 2 * Math.PI;
      const phi = Math.acos(2 * h2 - 1);
      const nx = Math.sin(phi) * Math.cos(th);
      const ny = Math.cos(phi);
      const nz = Math.sin(phi) * Math.sin(th);
      let ux = -ny;
      let uy = nx;
      const uz = 0;
      const ul = Math.max(1e-6, Math.sqrt(ux * ux + uy * uy));
      ux /= ul;
      uy /= ul;
      const vx = ny * uz - nz * uy;
      const vy = nz * ux - nx * uz;
      const vz = nx * uy - ny * ux;
      const speed = (0.25 + 0.55 * h3) * (h3 > 0.5 ? 1 : -1);
      for (let k = 0; k < ghostN; k++) {
        const a = k / ghostN * 2 * Math.PI;
        const [px, py, z] = pt(
          (ux * Math.cos(a) + vx * Math.sin(a)) * ro,
          (uy * Math.cos(a) + vy * Math.sin(a)) * ro,
          (uz * Math.cos(a) + vz * Math.sin(a)) * ro
        );
        const depth = (z / ro + 1) / 2;
        dots.push({
          x: px,
          y: py,
          z,
          r: ((_e = o.ghostR) != null ? _e : 0.9) * rs,
          white: 0.72,
          a: ((_f = o.ghostA) != null ? _f : 0.5) * (0.4 + 0.6 * depth)
        });
      }
      for (let m = 0; m < particles; m++) {
        const a = t * speed + m / particles * 2 * Math.PI + h2 * 6;
        const [px, py, z] = pt(
          (ux * Math.cos(a) + vx * Math.sin(a)) * ro,
          (uy * Math.cos(a) + vy * Math.sin(a)) * ro,
          (uz * Math.cos(a) + vz * Math.sin(a)) * ro
        );
        const depth = (z / ro + 1) / 2;
        dots.push({
          x: px,
          y: py,
          z,
          r: (((_g = o.partR) != null ? _g : 1.2) + ((_h = o.partRDepth) != null ? _h : 1.6) * depth) * rs,
          white: 0.3 - 0.22 * depth
        });
      }
    }
    return finalizeFrame(dots, [], o.rMin);
  };

  // src/engine/ribbon.ts
  var frameRibbon = (size, t, o) => {
    var _a, _b, _c, _d, _e, _f, _g, _h, _i, _j;
    const cx = size / 2;
    const cy = size / 2;
    const R = size / 2 * 0.78;
    const spin = (_a = o.spin) != null ? _a : 1;
    const camTilt = 0.3;
    const pt = makeProj(t * 0.1 * spin, camTilt, cx, cy, 1);
    const rs = radiusScale(size, (_b = o.rsPow) != null ? _b : 0.6);
    const dots = [];
    const ghostN = (_c = o.ghostN) != null ? _c : 150;
    for (let i = 0; i < ghostN; i++) {
      const d = fibDir(i, ghostN);
      const [px, py, z] = pt(d[0] * R, d[1] * R, d[2] * R);
      const depth = (z / R + 1) / 2;
      dots.push({ x: px, y: py, z, r: 0.8 * rs, white: 0.78, a: 0.1 + 0.22 * depth });
    }
    const ya = t * 0.24 * spin;
    const ta = o.faceOn ? -camTilt : 0.55 + 0.3 * Math.sin(t * 0.18) * spin;
    const ux = Math.cos(ya);
    const uy = 0;
    const uz = Math.sin(ya);
    const vx = -uz * Math.sin(ta);
    const vy = Math.cos(ta);
    const vz = ux * Math.sin(ta);
    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const nz = ux * vy - uy * vx;
    const wobAmp = 0.23 * ((_d = o.wobMul) != null ? _d : 1);
    const baseR = o.faceOn ? R / (1 + 0.85 * wobAmp) : R;
    const baseLanes = (_e = o.lanes) != null ? _e : 5;
    const segs = (_f = o.segs) != null ? _f : 88;
    const lanes = Math.max(1, Math.round(baseLanes * ((_g = o.bandMul) != null ? _g : 1)));
    for (let w = 0; w < lanes; w++) {
      const laneOff = (w - (lanes - 1) / 2) * 0.075;
      const edge = Math.abs(w - (lanes - 1) / 2) / Math.max(1, (lanes - 1) / 2);
      for (let k = 0; k < segs; k++) {
        const a = k / segs * 2 * Math.PI;
        const wob = (0.16 * Math.sin(a * 3 - t * 1.7 + w * 0.22) + 0.07 * Math.sin(a * 5 + t * 1.1)) * ((_h = o.wobMul) != null ? _h : 1);
        const radial = o.faceOn ? 1 + wob : 1;
        const off = o.faceOn ? laneOff : laneOff + wob;
        const x = ux * Math.cos(a) + vx * Math.sin(a) + nx * off;
        const y = uy * Math.cos(a) + vy * Math.sin(a) + ny * off;
        const z = uz * Math.cos(a) + vz * Math.sin(a) + nz * off;
        const l = Math.sqrt(x * x + y * y + z * z);
        const rr = baseR * radial;
        const [px, py, zr] = pt(x / l * rr, y / l * rr, z / l * rr);
        const depth = (zr / R + 1) / 2;
        dots.push({
          x: px,
          y: py,
          z: zr,
          r: (((_i = o.rBase) != null ? _i : 1.1) + ((_j = o.rDepth) != null ? _j : 1.7) * depth) * (1 - 0.25 * edge) * rs,
          white: 0.52 - 0.44 * depth + 0.18 * edge,
          a: 0.4 + 0.6 * depth
        });
      }
    }
    return finalizeFrame(dots, [], o.rMin);
  };

  // src/engine/web.ts
  var frameWeb = (size, t, o) => {
    var _a, _b, _c, _d, _e, _f, _g, _h;
    const cx = size / 2;
    const cy = size / 2;
    const R = size / 2 * 0.8 * ((_a = o.spread) != null ? _a : 1);
    const pt = makeProj(t * 0.12, 0.32, cx, cy, R);
    const rs = radiusScale(size, (_b = o.rsPow) != null ? _b : 0.6);
    const nodeN = (_c = o.nodeN) != null ? _c : 30;
    const thr = (_d = o.thr) != null ? _d : 0.72;
    const nodeR = (_e = o.nodeR) != null ? _e : 1.4;
    const nodeRDepth = (_f = o.nodeRDepth) != null ? _f : 1.8;
    const nodes = [];
    for (let i = 0; i < nodeN; i++) {
      const d = fibDir(i, nodeN);
      const x = d[0] + 0.3 * (vnoise(i * 0.31 + 9, t * 0.24) - 0.5) * 2;
      const y = d[1] + 0.3 * (vnoise(i * 0.53 + 27, t * 0.21) - 0.5) * 2;
      const z = d[2] + 0.3 * (vnoise(i * 0.77 + 55, t * 0.27) - 0.5) * 2;
      const l = Math.sqrt(x * x + y * y + z * z);
      nodes.push([x / l, y / l, z / l]);
    }
    const lines = [];
    const dots = [];
    for (let i = 0; i < nodeN; i++) {
      for (let j = i + 1; j < nodeN; j++) {
        const dx = nodes[i][0] - nodes[j][0];
        const dy = nodes[i][1] - nodes[j][1];
        const dz = nodes[i][2] - nodes[j][2];
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist >= thr) continue;
        const [x1, y1, z1] = pt(nodes[i][0], nodes[i][1], nodes[i][2]);
        const [x2, y2, z2] = pt(nodes[j][0], nodes[j][1], nodes[j][2]);
        const depth = ((z1 + z2) / 2 + 1) / 2;
        lines.push({
          x1,
          y1,
          x2,
          y2,
          white: 0.42,
          a: (1 - dist / thr) * (0.3 + 0.55 * depth),
          w: Math.max(0.6, ((_g = o.lineW) != null ? _g : 0.8) * rs)
        });
      }
    }
    for (let i = 0; i < nodeN; i++) {
      const [px, py, z] = pt(nodes[i][0], nodes[i][1], nodes[i][2]);
      const depth = (z + 1) / 2;
      const pulse = 1 + 0.25 * Math.sin(t * 1.4 + i * 2.7);
      dots.push({
        x: px,
        y: py,
        z,
        r: (nodeR + nodeRDepth * depth) * pulse * rs,
        white: 0.55 - 0.45 * depth
      });
    }
    const signals = (_h = o.signals) != null ? _h : 5;
    for (let s = 0; s < signals; s++) {
      const seg = Math.floor(t * 0.55 + s * 7.31);
      const a = Math.floor(hashD(seg, s * 3.1 + 1.7) * nodeN);
      const b = Math.floor(hashD(seg, s * 5.7 + 4.2) * nodeN);
      if (a === b) continue;
      const f = frac(t * 0.55 + s * 7.31);
      const x = lerp(nodes[a][0], nodes[b][0], f);
      const y = lerp(nodes[a][1], nodes[b][1], f);
      const z = lerp(nodes[a][2], nodes[b][2], f);
      const l = Math.max(1e-6, Math.sqrt(x * x + y * y + z * z));
      const [px, py, zr] = pt(x / l, y / l, z / l);
      const depth = (zr + 1) / 2;
      dots.push({
        x: px,
        y: py,
        z: zr,
        r: (nodeR * 1.5 + nodeRDepth * depth) * rs,
        white: 0.05,
        a: 0.5 + 0.5 * depth
      });
    }
    return finalizeFrame(dots, lines, o.rMin);
  };

  // src/engine/registry.ts
  var MODE_FRAMES = {
    orbits: frameOrbits,
    globe: frameGlobe,
    rubik: frameRubik,
    wave: frameWave,
    web: frameWeb,
    braid: frameBraid,
    ribbon: frameRibbon,
    // ring shares ribbon's geometry — the `faceOn` profile flag switches it
    ring: frameRibbon,
    morph: frameMorph
  };
  // MODE_DRAWS (canvas-рисовальщики) вырезаны: в QML нет Object.fromEntries, а рисует Orb.qml сам
  var MODE_DRAWS = {};


  // src/engine/profiles.ts
  var COUNT_PAIRS = [
    ["latRings", "lonDensity"],
    ["rings", "lonDensity"],
    ["lanes", "segs"]
  ];
  var COUNT_KEYS = ["orbitN", "ghostN", "nodeN", "strandN", "signals"];
  var ICON_DENSITY_KEYS = ["iconD"];
  var RADIUS_KEYS = [
    "rBase",
    "rDepth",
    "rActive",
    "rDot",
    "ghostR",
    "partR",
    "partRDepth",
    "nodeR",
    "nodeRDepth"
  ];
  function scaleCounts(opts, scale) {
    const out = __spreadValues({}, opts);
    const done = /* @__PURE__ */ new Set();
    const rt = Math.sqrt(scale);
    for (const [a, b] of COUNT_PAIRS) {
      const va = out[a];
      const vb = out[b];
      if (va != null && vb != null && !done.has(a) && !done.has(b)) {
        out[a] = Math.max(2, Math.round(va * rt));
        out[b] = Math.max(2, Math.round(vb * rt));
        done.add(a);
        done.add(b);
      }
    }
    for (const k of COUNT_KEYS) {
      const v = out[k];
      if (v != null && v !== 0 && !done.has(k)) out[k] = Math.max(1, Math.round(v * scale));
    }
    for (const k of ICON_DENSITY_KEYS) {
      const v = out[k];
      if (v != null) out[k] = Math.max(0.02, v * scale);
    }
    return out;
  }
  function scaleRadii(opts, scale) {
    var _a;
    const out = __spreadValues({}, opts);
    for (const k of RADIUS_KEYS) {
      const v = out[k];
      if (v != null) out[k] = v * scale;
    }
    out.rSizeMul = ((_a = out.rSizeMul) != null ? _a : 1) * scale;
    return out;
  }
  var BASE_PROFILES = {
    globe: {
      latRings: 17,
      lonDensity: 44,
      rBase: 0.6,
      rDepth: 1.7,
      rBoost: 1,
      inkFar: 0.62,
      inkSpan: 0.54,
      rsPow: 0.6,
      rMin: 0.3
    },
    orbits: {
      orbitN: 12,
      ghostN: 40,
      ghostR: 0.9,
      ghostA: 0.5,
      particles: 3,
      partR: 1.2,
      partRDepth: 1.6,
      rsPow: 0.6,
      rMin: 0.3
    },
    rubik: {
      latRings: 15,
      lonDensity: 40,
      moveCount: 14,
      rBase: 0.6,
      rDepth: 1.7,
      rActive: 0.3,
      inkFar: 0.62,
      inkSpan: 0.54,
      rsPow: 0.6,
      rMin: 0.3
    },
    wave: {
      rings: 15,
      lonDensity: 40,
      rBase: 0.6,
      rDepth: 1.7,
      rsPow: 0.6,
      rMin: 0.3
    },
    web: {
      nodeN: 30,
      thr: 0.72,
      signals: 5,
      nodeR: 1.4,
      nodeRDepth: 1.8,
      lineW: 0.8,
      rsPow: 0.6,
      rMin: 0.3
    },
    braid: {
      strandN: 52,
      turns: 3,
      ghostN: 150,
      rBase: 1.2,
      rDepth: 1.8,
      rsPow: 0.6,
      rMin: 0.3
    },
    ribbon: {
      lanes: 5,
      segs: 88,
      ghostN: 150,
      rBase: 1.1,
      rDepth: 1.7,
      rsPow: 0.6,
      rMin: 0.3
    },
    // ring shares ribbon's painter; faceOn cancels the camera tilt and moves
    // the undulation onto the radius, and there is no ghost sphere behind it
    ring: {
      lanes: 5,
      segs: 88,
      ghostN: 0,
      faceOn: 1,
      rBase: 1.1,
      rDepth: 1.7,
      rsPow: 0.6,
      rMin: 0.3
    },
    morph: {
      rDot: 0.021,
      iconD: 1,
      rMin: 0.25
    }
  };

  // src/presets.ts
  var STATE_TO_MODE = {
    working: "orbits",
    searching: "globe",
    solving: "rubik",
    listening: "wave",
    connecting: "web",
    weaving: "braid",
    composing: "ribbon",
    breathing: "ring",
    shaping: "morph"
  };
  var PRESETS = {
    orbits: {
      64: { speed: 1.885, count: 1, size: 1 },
      20: { speed: 3.9, count: 0.238, size: 2.4 }
    },
    globe: {
      64: { speed: 2.015, count: 0.42, size: 1.15, extra: { scanMul: 4.08, dimBase: 0.45 } },
      20: { speed: 2.665, count: 0.105, size: 1.75, extra: { scanMul: 4.335, dimBase: 0.45 } }
    },
    rubik: {
      64: { speed: 1.82, count: 0.35, size: 1.05 },
      20: { speed: 1.95, count: 0.088, size: 1.9 }
    },
    wave: {
      64: { speed: 4.388, count: 0.341, size: 1 },
      20: { speed: 3.998, count: 0.105, size: 1.6 }
    },
    web: {
      64: { speed: 3.315, count: 1.35, size: 0.95 },
      20: { speed: 6.63, count: 0.25, size: 1.52 }
    },
    braid: {
      64: { speed: 1.625, count: 0.5, size: 1 },
      20: { speed: 2.75, count: 0.1125, size: 1.36 }
    },
    ribbon: {
      64: { speed: 2.34, count: 0.25, size: 0.85, extra: { spin: 0, bandMul: 3.9, wobMul: 1 } },
      20: { speed: 3.12, count: 0.051, size: 1.073, extra: { spin: 0, bandMul: 4.94, wobMul: 1 } }
    },
    ring: {
      64: { speed: 3.24, count: 0.25, size: 0.956, extra: { spin: 0, bandMul: 3.627, wobMul: 0.368 } },
      20: { speed: 3.78, count: 0.028, size: 1.622, extra: { spin: 0, bandMul: 3.968, wobMul: 0.565 } }
    },
    morph: {
      64: { speed: 2.405, count: 0.702, size: 0.395, extra: { spread: 1.45 } },
      20: { speed: 2.08, count: 0.53, size: 1.011, extra: { spread: 1.45 } }
    }
  };
  var cache = /* @__PURE__ */ new Map();
  function resolvePreset(state, size) {
    const key = `${state}-${size}`;
    const hit = cache.get(key);
    if (hit) return hit;
    const mode = STATE_TO_MODE[state];
    const preset = PRESETS[mode][size];
    let opts = __spreadValues({}, BASE_PROFILES[mode]);
    if (preset.count !== 1) opts = scaleCounts(opts, preset.count);
    if (preset.size !== 1) opts = scaleRadii(opts, preset.size);
    if (preset.extra) opts = __spreadValues(__spreadValues({}, opts), preset.extra);
    const resolved = { mode, speed: preset.speed, opts };
    cache.set(key, resolved);
    return resolved;
  }
  return __toCommonJS(engine_exports);
})();
