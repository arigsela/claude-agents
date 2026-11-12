// Render a blog-diagrams spec: the HTML page, a 2x still PNG, and, when the spec has steps,
// a GIF, an MP4 and a step sheet (one panel per step) for review.
//
// Usage: node render.mjs SPEC.json [--out DIR] [--still] [--fps 12] [--force] [--keep-frames]
//   --out DIR      where the PNG, GIF and MP4 go (default: next to the spec)
//   --still        the PNG only, no animation
//   --fps N        frames per second for the GIF (default 12)
//   --force        encode even when the layout check finds problems
//   --keep-frames  keep the PNG frames (in a folder next to the spec)
// The HTML page and the step sheet always go next to the spec.
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SKILL = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const die = (msg, code = 2) => { console.error(`blog-diagrams: ${msg}`); process.exit(code); };

// ---------- arguments ----------
const argv = process.argv.slice(2);
const opts = { fps: 12 };
const positional = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === '--out') opts.out = argv[++i];
  else if (a === '--fps') opts.fps = Number(argv[++i]);
  else if (a === '--still') opts.still = true;
  else if (a === '--force') opts.force = true;
  else if (a === '--keep-frames') opts.keepFrames = true;
  else if (a.startsWith('--')) die(`unknown option ${a}`);
  else positional.push(a);
}
if (positional.length !== 1) die('usage: node render.mjs SPEC.json [--out DIR] [--still] [--fps 12] [--force] [--keep-frames]');
if (!(opts.fps > 0 && opts.fps <= 30)) die('--fps must be between 1 and 30');

const specPath = path.resolve(positional[0]);
const specDir = path.dirname(specPath);
let spec;
try { spec = JSON.parse(fs.readFileSync(specPath, 'utf8')); } catch (e) { die(`${specPath}: ${e.message}`); }
const name = spec.name || path.basename(specPath, '.json');
if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) die(`"name" must be lowercase letters, digits and hyphens (got "${name}")`);
const outDir = path.resolve(opts.out || specDir);
fs.mkdirSync(outDir, { recursive: true });

// Icons from files ("icon": "file:k8s/pod.svg") are inlined, so the page stands alone.
for (const n of spec.nodes || []) {
  if (typeof n.icon !== 'string' || !n.icon.startsWith('file:')) continue;
  const rel = n.icon.slice(5);
  const found = [path.resolve(specDir, rel), path.join(SKILL, 'icons', rel)].find(f => fs.existsSync(f));
  if (!found) die(`${n.id}: icon file "${rel}" not found next to the spec or in ${path.join(SKILL, 'icons')}`);
  const mime = { '.svg': 'image/svg+xml', '.png': 'image/png' }[path.extname(found).toLowerCase()];
  if (!mime) die(`${n.id}: icon "${rel}" must be .svg or .png`);
  n.iconSrc = `data:${mime};base64,${fs.readFileSync(found).toString('base64')}`;
}

const engine = fs.readFileSync(path.join(SKILL, 'engine', 'engine.html'), 'utf8');
const PLACEHOLDER = '/*__SPEC__*/{}';
if (!engine.includes(PLACEHOLDER)) die('engine.html has lost its spec placeholder');
const htmlPath = path.join(specDir, `${name}.html`);
fs.writeFileSync(htmlPath, engine.replace(PLACEHOLDER, () => JSON.stringify(spec).replace(/</g, '\\u003c')));

// ---------- headless Chrome over the DevTools protocol ----------
const CHROME = process.env.CHROME || [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].find(f => fs.existsSync(f));
if (!CHROME) die('Chrome not found; set CHROME=/path/to/chrome');

const sleep = ms => new Promise(r => setTimeout(r, ms));
const kb = f => `${Math.round(fs.statSync(f).size / 1024)} KB`;
// Chrome's throwaway profile lives next to the spec and is deleted at the end.
const profile = fs.mkdtempSync(path.join(specDir, `.${name}-chrome-`));
const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--hide-scrollbars',
  '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--force-color-profile=srgb', 'about:blank'], { stdio: 'ignore' });

async function connect() {
  const portFile = path.join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 80; i++) {
    try {
      const port = fs.readFileSync(portFile, 'utf8').split('\n')[0].trim();
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = list.find(t => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(150);
  }
  throw new Error('headless Chrome did not start');
}

let exitCode = 0;
try {
  const ws = new WebSocket(await connect());
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let seq = 0;
  const waiting = new Map(), pageErrors = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
    else if (m.method === 'Runtime.exceptionThrown') pageErrors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  };
  const send = (method, params = {}) => new Promise(res => { const id = ++seq; waiting.set(id, res); ws.send(JSON.stringify({ id, method, params })); });
  const evaluate = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text);
    return r.result.result.value;
  };
  const shot = async file => fs.writeFileSync(file, Buffer.from((await send('Page.captureScreenshot', { format: 'png' })).result.data, 'base64'));
  const metrics = (dsf, [w, h]) => send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dsf, mobile: false });

  await send('Runtime.enable');
  await send('Page.enable');
  await metrics(1, [1600, 1350]);
  await send('Page.navigate', { url: 'file://' + htmlPath + '?capture=1' });
  let ready = false;
  for (let i = 0; i < 50 && !ready; i++) { await sleep(100); ready = await evaluate('typeof window.__check === "function"').catch(() => false); }
  if (!ready) throw new Error('the page did not start' + (pageErrors.length ? `: ${pageErrors.join('; ')}` : ''));
  await evaluate('document.fonts.ready.then(() => true)');
  const size = await evaluate('window.__SIZE');
  await metrics(1, size);
  await sleep(100);
  const info = await evaluate('window.__check()');
  const probs = [...info.problems, ...pageErrors.map(e => `page error: ${e}`)];

  console.log(`blog-diagrams: ${name}  ${size[0]}x${size[1]}  ${info.nodes} nodes, ${info.edges} edges, ${info.steps} steps` +
              (info.seconds ? `, ${info.seconds.toFixed(1)} s` : ''));
  console.log(`  ${probs.length} problem${probs.length === 1 ? '' : 's'}`);
  for (const p of probs) console.log(`  - ${p}`);
  console.log(`  html   ${htmlPath}`);

  await metrics(2, size);
  await evaluate('window.__setT(window.__FINAL)');
  await sleep(150);
  const stillPath = path.join(outDir, `${name}.png`);
  await shot(stillPath);
  console.log(`  still  ${stillPath}  ${size[0] * 2}x${size[1] * 2}  ${kb(stillPath)}`);

  if (probs.length && !opts.force) {
    console.log('  Fix the problems and run again (or pass --force). No animation rendered.');
    exitCode = 1;
  } else if (!opts.still && info.steps) {
    const hasFfmpeg = spawnSync('ffmpeg', ['-version'], { stdio: 'ignore' }).status === 0;
    if (!hasFfmpeg) { console.log('  ffmpeg not found (brew install ffmpeg): no GIF or MP4.'); exitCode = 1; }
    else {
      const framesDir = path.join(specDir, `.${name}-frames`);
      fs.rmSync(framesDir, { recursive: true, force: true });
      fs.mkdirSync(framesDir);
      await metrics(1, size);
      const fps = opts.fps, frames = Math.round(info.seconds * fps), t0 = Date.now();
      for (let f = 0; f < frames; f++) {
        await evaluate(`window.__setT(${f / fps})`);
        await shot(path.join(framesDir, `f${String(f).padStart(4, '0')}.png`));
      }
      const pattern = path.join(framesDir, 'f%04d.png');
      const ff = args => {
        const r = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args], { encoding: 'utf8' });
        if (r.status !== 0) throw new Error(`ffmpeg failed: ${r.stderr.trim().split('\n').pop()}`);
      };
      const palette = path.join(framesDir, 'palette.png');
      const gifPath = path.join(outDir, `${name}.gif`), mp4Path = path.join(outDir, `${name}.mp4`);
      ff(['-framerate', String(fps), '-i', pattern, '-vf', 'palettegen=max_colors=128:stats_mode=diff', palette]);
      ff(['-framerate', String(fps), '-i', pattern, '-i', palette, '-lavfi', 'paletteuse=dither=none:diff_mode=rectangle', '-loop', '0', gifPath]);
      ff(['-framerate', String(fps), '-i', pattern, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-movflags', '+faststart', '-r', '30', mp4Path]);
      // Step sheet: the last frame of each step, then the final frame.
      const picks = [...info.stepEnds.map(t => Math.max(0, Math.round(t * fps) - 1)), frames - 1];
      const cols = Math.min(3, picks.length), rows = Math.ceil(picks.length / cols);
      const sheetPath = path.join(specDir, `${name}-steps.png`);
      ff(['-framerate', String(fps), '-i', pattern, '-vf',
          `select='${picks.map(n => `eq(n\\,${n})`).join('+')}',scale=540:-1,tile=${cols}x${rows}:padding=12:margin=12:color=white`,
          '-frames:v', '1', '-fps_mode', 'vfr', sheetPath]);
      console.log(`  gif    ${gifPath}  ${kb(gifPath)}  (${frames} frames at ${fps} fps, ${((Date.now() - t0) / 1000).toFixed(0)} s to render)`);
      console.log(`  mp4    ${mp4Path}  ${kb(mp4Path)}`);
      console.log(`  steps  ${sheetPath}`);
      if (fs.statSync(gifPath).size > 5 * 1024 * 1024) console.log('  The GIF is over 5 MB: try --fps 10, or fewer steps.');
      if (opts.keepFrames) console.log(`  frames ${framesDir}`);
      else fs.rmSync(framesDir, { recursive: true, force: true });
    }
  }
  ws.close();
} catch (e) {
  console.error(`blog-diagrams: ${e.message}`);
  exitCode = 1;
} finally {
  chrome.kill();
  await sleep(300);
  fs.rmSync(profile, { recursive: true, force: true });
}
process.exit(exitCode);
