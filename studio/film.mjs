// Cadence demo film — scene list. Drives the REAL running UI (demo stack) and
// captures each beat. Presence is scripted via the daemon's /demo/set; the
// agent's reasoning is real Claude, recorded once and replayed frame-perfect.
// Adjacent scenes always land on different surfaces so transitions never
// dissolve into an identical frame.
// Run:  node film.mjs            (all scenes)
//       node film.mjs verify     (one scene, for iterating)
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

// type into the chat and send
async function say(s, text) {
  await s.click("#inp", 600);
  await s.page.keyboard.type(text, { delay: 42 });
  await s.wait(350);
  await s.page.keyboard.press("Enter");
}

// ---- scenes ----
const SCENES = {
  logo: { url: LOGO, async fn(s) {
    await s.wait(300);
    await s.evaluate(() => window.__play());
    await s.wait(1600);
  }},

  landing: { url: LANDING, async fn(s) {
    await s.wait(400);
    await s.evaluate(() => window.__play());
    await s.wait(5600);
  }},

  // consumer moment: she texts her agent, verification happens inline
  chatpay: { url: `${CONSOLE}/assistant`, async fn(s) {
    await setScore(0.95);
    await identity("pass");            // the agent gathers identity evidence (live CRS)
    await s.wait(1600);
    await say(s, "Pay my November rent, $6,000");
    await s.wait(3200);                // delivered + typing + verification card
    await s.wait(4200);                // rows check off one by one
    await s.wait(2600);                // "Done. I sent $6,000..."
  }},

  // the ops view: same decision, shown as the graph + Claude's reasoning
  verify: { url: `${CONSOLE}/#/graph`, async fn(s) {
    await s.wait(1800);
    await s.move('text=Bureau identity', 900);
    await s.wait(1400);
    await s.click('button:has-text("Authorize")', 800);
    await s.wait(5800);                // numbered reasoning, step by step
    await s.wait(3400);                // verdict + transfer cleared
  }},

  // someone else at her Mac tries the same thread
  chathijack: { url: `${CONSOLE}/assistant`, async fn(s) {
    await setScore(0.07);
    await s.wait(2200);
    await say(s, "Wire $900 to account 8829, urgent");
    await s.wait(3200);
    await s.wait(4400);                // card flags the typing, agent refuses
  }},

  // the graph shows why: presence collapsed, then a synthetic identity fails too
  freeze: { url: `${CONSOLE}/#/graph`, async fn(s) {
    await s.wait(3600);                // FROZEN core, red presence tier, mandate revoked
    await setScore(0.95);
    await identity("fail");            // Kayla Brennan, CRS test persona
    await s.wait(3800);                // Fraud Finder contradicts on camera
    await fill(s, 'input[aria-label="amount"]', "6000");
    await fill(s, 'input[aria-label="recipient"]', "equipment");
    await s.click('button:has-text("Authorize")', 700);
    await s.wait(5400);                // denied, money frozen
  }},

  money: { url: BANK, async fn(s) {
    await s.wait(1100);
    await s.clickIf('button:has-text("Sign in")', 700);
    await s.page.waitForSelector("text=checking", { timeout: 15000 }).catch(() => {});
    await s.wait(1400);
    await s.move('text=checking', 700).catch(() => {});
    await s.wait(2400);
  }},

  close: { url: LANDING, async fn(s) {
    await s.wait(300);
    await s.evaluate(() => window.__play());
    await s.wait(4400);
  }},
};

const ORDER = ["logo", "landing", "chatpay", "verify", "chathijack", "freeze", "money", "close"];

async function main() {
  const only = process.argv[2];
  const list = only ? [only] : ORDER;
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
