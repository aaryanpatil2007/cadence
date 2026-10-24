// Cadence film capture: drive the REAL UI with an animated cursor + smooth
// scroll, capture smooth frames via CDP screencast (tied to real render).
// Output: frames/<scene>/frame_*.jpg + timings.json per scene.
import { chromium } from "playwright";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";

const W = 1920, H = 1080, DSF = 2;
const OUT = join(process.cwd(), "frames");

// cursor + motion helpers injected into every page
const INIT = `
window.__cad = (() => {
  const clamp = (x,a,b)=>Math.min(b,Math.max(a,x));
  const easeInOut = t => t<0.5 ? 2*t*t : 1-Math.pow(-2*t+2,2)/2;
  let cur, fadeTimer;
  // a small, realistic macOS-style pointer (SVG arrow) — hidden unless moving
  const ARROW = '<svg width="20" height="20" viewBox="0 0 24 24" style="display:block;filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))">'+
    '<path d="M5 3 L5 19 L9.2 15 L12 21 L15 19.6 L12.2 13.8 L18 13.6 Z" fill="#111" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  function cursor(){
    if(cur) return cur;
    cur = document.createElement('div');
    cur.style.cssText = 'position:fixed;z-index:999999;left:0;top:0;pointer-events:none;'+
      'opacity:0;transition:opacity .18s ease;will-change:transform,opacity';
    cur.innerHTML = ARROW;
    document.body.appendChild(cur);
    cur._x=-80; cur._y=window.innerHeight+80; place();   // parked off-screen
    return cur;
  }
  function place(){ cur.style.transform='translate('+cur._x+'px,'+cur._y+'px)'; }
  function show(){ clearTimeout(fadeTimer); cursor().style.opacity='1'; }
  function idle(){ clearTimeout(fadeTimer); fadeTimer=setTimeout(()=>{ if(cur) cur.style.opacity='0'; }, 650); }
  function pos(){ const c=cursor(); return {x:c._x,y:c._y}; }
  function move(x,y,ms){ const c=cursor(); show();
    // if parked off-screen, teleport near the target first so it doesn't streak
    if(c._y>window.innerHeight){ c._x=clamp(x+120,40,window.innerWidth-40); c._y=clamp(y+90,40,window.innerHeight-40); place(); }
    const sx=c._x,sy=c._y; const t0=performance.now();
    return new Promise(res=>{ (function loop(now){ const t=clamp((now-t0)/ms,0,1); const e=easeInOut(t);
      c._x=sx+(x-sx)*e; c._y=sy+(y-sy)*e; place();
      if(t<1) requestAnimationFrame(loop); else { idle(); res(); } })(t0); }); }
  function pulse(){ const c=cursor(); show(); const r=document.createElement('div');
    r.style.cssText='position:fixed;z-index:999998;left:'+c._x+'px;top:'+c._y+'px;width:8px;height:8px;'+
      'border:2px solid rgba(0,84,61,.8);border-radius:50%;pointer-events:none;transform:translate(-50%,-50%)';
    document.body.appendChild(r); const t0=performance.now();
    (function loop(now){ const t=clamp((now-t0)/420,0,1); const s=1+t*3.4;
      r.style.width=(8*s)+'px'; r.style.height=(8*s)+'px'; r.style.opacity=String(1-t);
      if(t<1) requestAnimationFrame(loop); else r.remove(); })(t0); idle(); }
  function scrollTo(el, top, ms){ const t0=performance.now(); const s=el.scrollTop;
    return new Promise(res=>{ (function loop(now){ const t=clamp((now-t0)/ms,0,1); const e=easeInOut(t);
      el.scrollTop=s+(top-s)*e; if(t<1) requestAnimationFrame(loop); else res(); })(t0); }); }
  return {cursor,move,pos,pulse,scrollTo,place};
})();
`;

async function captureScene(context, name, url, sceneFn) {
  const dir = join(OUT, name);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const page = await context.newPage();
  await page.addInitScript(INIT);
  await page.goto(url, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts && document.fonts.ready);
  await page.evaluate(() => window.__cad.cursor());
  await page.waitForTimeout(250);

  const client = await context.newCDPSession(page);
  const frames = [];
  client.on("Page.screencastFrame", async (f) => {
    frames.push({ data: f.data, ts: f.metadata.timestamp });
    try { await client.send("Page.screencastFrameAck", { sessionId: f.sessionId }); } catch {}
  });
  await client.send("Page.startScreencast", {
    format: "jpeg", quality: 92, maxWidth: W, maxHeight: H, everyNthFrame: 1,
  });

  const api = makeApi(page);
  await sceneFn(api);

  await page.waitForTimeout(120);
  await client.send("Page.stopScreencast");
  await page.waitForTimeout(80);

  const t0 = frames.length ? frames[0].ts : 0;
  const timings = [];
  frames.forEach((fr, i) => {
    const fn = `frame_${String(i).padStart(4, "0")}.jpg`;
    writeFileSync(join(dir, fn), Buffer.from(fr.data, "base64"));
    timings.push({ file: fn, t: fr.ts - t0 });
  });
  writeFileSync(join(dir, "timings.json"), JSON.stringify(timings));
  await page.close();
  console.log(`  [${name}] ${frames.length} frames, ${(timings.at(-1)?.t ?? 0).toFixed(2)}s`);
  return timings.at(-1)?.t ?? 0;
}

function makeApi(page) {
  const centerOf = async (sel) => {
    const b = await page.locator(sel).first().boundingBox();
    if (!b) throw new Error("no element: " + sel);
    return { x: b.x + b.width / 2, y: b.y + b.height / 2, b };
  };
  return {
    page,
    wait: (ms) => page.waitForTimeout(ms),
    moveTo: (x, y, ms = 650) => page.evaluate(([x, y, ms]) => window.__cad.move(x, y, ms), [x, y, ms]),
    async move(sel, ms = 650) { const c = await centerOf(sel); await this.moveTo(c.x, c.y, ms); return c; },
    async click(sel, ms = 650) {
      const c = await centerOf(sel);
      await this.moveTo(c.x, c.y, ms);
      await page.evaluate(() => window.__cad.pulse());
      await page.waitForTimeout(90);
      await page.mouse.click(c.x, c.y);
      return c;
    },
    async clickXY(x, y, ms = 650) {
      await this.moveTo(x, y, ms);
      await page.evaluate(() => window.__cad.pulse());
      await page.waitForTimeout(90);
      await page.mouse.click(x, y);
    },
    async type(sel, text, cps = 14) {
      await page.locator(sel).first().click();
      await page.keyboard.type(text, { delay: 1000 / cps });
    },
    async scroll(sel, top, ms = 900) {
      await page.evaluate(([sel, top, ms]) => {
        const el = sel === "window" ? document.scrollingElement : document.querySelector(sel);
        return window.__cad.scrollTo(el, top, ms);
      }, [sel, top, ms]);
    },
    hash: (h) => page.evaluate((h) => { location.hash = h; }, h),
    goto: (u) => page.goto(u, { waitUntil: "networkidle" }),
    evaluate: (...a) => page.evaluate(...a),
  };
}

export { captureScene, W, H, DSF, OUT, chromium };
