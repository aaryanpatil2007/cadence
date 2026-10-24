// Render each caption to a transparent PNG (clean white pill, ink text, Ada).
// Output: caps/<id>.png
import { chromium } from "playwright";
import { mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const film = JSON.parse(readFileSync(join(process.cwd(), "film.json"), "utf8"));
const caps = film.captions;
mkdirSync(join(process.cwd(), "caps"), { recursive: true });

const html = (text) => `<!doctype html><html><head><meta charset="utf8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@500&display=swap');
html,body{margin:0;background:transparent}
.pill{display:inline-flex;align-items:center;gap:9px;background:#fff;color:#0a0b0c;
  font-family:'Hanken Grotesk',system-ui,sans-serif;font-weight:500;font-size:23px;
  letter-spacing:-.01em;padding:13px 22px;border-radius:9999px;border:1px solid rgba(10,11,12,.1);
  box-shadow:0 5px 18px rgba(10,11,12,.09);white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;background:#00543d;flex:0 0 auto}
</style></head><body><div class="pill"><span class="dot"></span>${text}</div></body></html>`;

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 200 }, deviceScaleFactor: 2 });
for (const c of caps) {
  await p.setContent(html(c.text), { waitUntil: "networkidle" });
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(120);
  const el = await p.locator(".pill");
  await el.screenshot({ path: join(process.cwd(), "caps", `${c.id}.png`), omitBackground: true });
}
await b.close();
console.log(`rendered ${caps.length} captions`);
