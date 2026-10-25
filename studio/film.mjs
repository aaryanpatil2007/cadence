// Cadence demo film — scene list. Drives the REAL running UI (demo stack) and
// captures each beat. Presence is scripted via the daemon's /demo/set; the
// agent's reasoning is real Claude, recorded once and replayed frame-perfect.
// Run:  node film.mjs            (all scenes)
//       node film.mjs authorize  (one scene, for iterating)
import { pathToFileURL } from "node:url";
import { join } from "node:path";
import { captureScene, W, H, DSF, chromium } from "./capture.mjs";

const CONSOLE = "http://127.0.0.1:7800";
const BANK = "http://127.0.0.1:7900";
const DAEMON = "http://127.0.0.1:7777";
const LOGO = pathToFileURL(join(process.cwd(), "props", "logo.html")).href;
const LANDING = pathToFileURL(join(process.cwd(), "props", "landing.html")).href;

const setScore = (s) => fetch(`${DAEMON}/demo/set?score=${s}`, { method: "POST" }).catch(() => {});
const identity = (p) => fetch(`${CONSOLE}/graph/identity/verify`, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ persona: p }),
}).catch(() => {});

// fill a controlled React input: click, select-all, retype
async function fill(s, sel, text) {
  await s.click(sel, 500);
  await s.page.keyboard.press("Meta+a");
  await s.page.keyboard.type(text, { delay: 55 });
}

// ---- scenes ----
const SCENES = {
  logo: { url: LOGO, async fn(s) {
    await s.wait(300);
    await s.evaluate(() => window.__play());
    await s.wait(2100);
  }},

  landing: { url: LANDING, async fn(s) {
    await s.wait(400);
    await s.evaluate(() => window.__play());
    await s.wait(6400);
  }},

  mandate: { url: `${CONSOLE}/#/graph`, async fn(s) {
    await setScore(0.95);
    await s.wait(2600);                       // presence + device + money lit
    await s.move('text=Bureau identity', 900);
    await identity("pass");                   // CRS lights the identity tier, live
    await s.wait(3600);                       // nodes flip stale -> lit on poll
    await s.move('text=Margaret Okafor', 800);
    await s.wait(2400);                       // mandate ACTIVE — root of trust
  }},

  authorize: { url: `${CONSOLE}/#/graph`, async fn(s) {
    await setScore(0.95);
    await s.wait(1600);
    await fill(s, 'input[aria-label="amount"]', "6000");
    await s.wait(300);
    await fill(s, 'input[aria-label="recipient"]', "november rent");
    await s.wait(500);
    await s.click('button:has-text("Authorize")', 750);
    await s.wait(5600);                       // Claude reasons over the graph
    await s.wait(3200);                       // allow + Nessie transfer cleared
  }},

  hijack: { url: `${CONSOLE}/#/graph`, async fn(s) {
    await setScore(0.95);
    await s.wait(2000);                       // all green
    await setScore(0.07);                     // someone else takes the keyboard
    await s.wait(4200);                       // presence tier collapses, FROZEN
    await fill(s, 'input[aria-label="amount"]', "900");
    await fill(s, 'input[aria-label="recipient"]', "wire transfer");
    await s.click('button:has-text("Authorize")', 700);
    await s.wait(4800);                       // deny — authority revoked
  }},

  synthetic: { url: `${CONSOLE}/#/graph`, async fn(s) {
    await setScore(0.95);
    await identity("fail");                   // Kayla Brennan — synthetic persona
    await s.wait(3600);                       // Fraud Finder node contradicts
    await s.move('text=Fraud Finder', 800);
    await s.wait(1200);
    await fill(s, 'input[aria-label="amount"]', "6000");
    await fill(s, 'input[aria-label="recipient"]', "equipment");
    await s.click('button:has-text("Authorize")', 700);
    await s.wait(5200);                       // deny — synthetic identity, live CRS
  }},

  money: { url: BANK, async fn(s) {
    await s.wait(1100);
    await s.clickIf('button:has-text("Sign in")', 700);
    await s.page.waitForSelector("text=checking", { timeout: 15000 }).catch(() => {});
    await s.wait(1400);                       // the ledger the agent moved money on
    await s.move('text=checking', 700).catch(() => {});
    await s.wait(2600);
  }},

  close: { url: LANDING, async fn(s) {
    await s.wait(300);
    await s.evaluate(() => window.__play());
    await s.wait(4600);
  }},
};

const ORDER = ["logo", "landing", "mandate", "authorize", "hijack", "synthetic", "money", "close"];

async function main() {
  const only = process.argv[2];
  const list = only ? [only] : ORDER;
  // identity starts stale — the mandate scene lights it on camera (live CRS)
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: W, height: H }, deviceScaleFactor: DSF,
    reducedMotion: "no-preference",
  });
  const durations = {};
  for (const name of list) {
    const sc = SCENES[name];
    console.log(`scene: ${name}`);
    durations[name] = await captureScene(context, name, sc.url, sc.fn);
  }
  await browser.close();
  await setScore(0.93); await identity("pass");   // leave the stack in a good state
  console.log("durations:", JSON.stringify(durations));
}
main();
