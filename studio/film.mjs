// Cadence demo film — scene list. Drives the REAL running UI (demo stack) and
// captures each beat. Presence is scripted via the daemon's /demo/set.
// Run:  node film.mjs            (all scenes)
//       node film.mjs console    (one scene, for iterating)
import { pathToFileURL } from "node:url";
import { join } from "node:path";
import { captureScene, W, H, DSF, chromium } from "./capture.mjs";

const CONSOLE = "http://127.0.0.1:7800";
const BANK = "http://127.0.0.1:7900";
const DAEMON = "http://127.0.0.1:7777";
const LOGO = pathToFileURL(join(process.cwd(), "props", "logo.html")).href;

const setScore = (s) => fetch(`${DAEMON}/demo/set?score=${s}`, { method: "POST" }).catch(() => {});
const login = () => fetch(`${BANK}/login`, { method: "POST" }).catch(() => {});

// ---- scenes ----
const SCENES = {
  logo: { url: LOGO, async fn(s) {
    await s.wait(300);
    await s.evaluate(() => window.__play());
    await s.wait(2100);
  }},

  onboard: { url: `${BANK}/#/welcome`, async fn(s) {
    await s.wait(1700);                          // step 1: verify identity (CRS)
    await s.click('button:has-text("Verify identity")', 800);
    await s.wait(2600);                          // -> auto-advances to step 2
    await s.click('button:has-text("Connect Capital One")', 800);
    await s.wait(2700);                          // -> step 3
    await s.click('button:has-text("Start enrollment")', 800);
    await s.wait(2900);                          // training bar -> step 4
    await s.wait(1400);                          // "You're protected"
  }},

  pay: { url: BANK, async fn(s) {
    await setScore(0.95);
    await s.wait(900);
    await s.clickIf('button:has-text("Sign in")', 700);
    await s.wait(1600);                          // accounts home
    await s.click('button:has-text("Send money")', 800);
    await s.wait(1100);
    await s.type('input[placeholder*="what"]', "rent — november", 12);
    await s.wait(500);
    await s.click('button:has-text("Send")', 800);
    await s.wait(3400);                          // verify + approved
    await s.move('text=Presence', 800);
    await s.wait(1500);
  }},

  monitor: { url: DAEMON, async fn(s) {
    await setScore(0.93);
    await s.wait(2300);                          // "You" — recognized
    await s.scroll("window", 300, 1100);
    await s.wait(2200);                          // the signals the model reads
    await setScore(0.07);                        // someone else takes over
    await s.scroll("window", 0, 900);
    await s.wait(3000);                          // gauge collapses -> not you
  }},

  console: { url: `${CONSOLE}/#/overview`, async fn(s) {
    await s.wait(1900);
    await s.move('text=Trust over time', 900);
    await s.wait(1900);
    await s.scroll("window", 360, 1200);
    await s.wait(2600);          // watch the live stream flow
    await s.scroll("window", 0, 900);
    await s.wait(900);
  }},

  sessions: { url: `${CONSOLE}/#/sessions`, async fn(s) {
    await s.wait(2000);
    await s.move('text=Behavioral sessions', 700);
    await s.wait(1600);
    await s.scroll("window", 160, 1000);
    await s.wait(3200);          // verified sessions + the flagged takeover curve
    await s.scroll("window", 0, 800);
    await s.wait(800);
  }},

  integrations: { url: `${CONSOLE}/#/integrations`, async fn(s) {
    await s.wait(2000);
    await s.move('text=Capital One', 800);
    await s.wait(2400);          // the regulated data it runs on
  }},

  fraud: { url: BANK, async fn(s) {
    await login();
    await setScore(0.06);        // someone else at the keyboard
    await s.wait(900);
    await s.clickIf('button:has-text("Sign in")', 700);
    await s.wait(1500);
    await s.click('button:has-text("Send money")', 800);
    await s.wait(1000);
    await s.type('input[placeholder*="what"]', "wire transfer", 12);
    await s.wait(500);
    await s.click('button:has-text("Send")', 800);
    await s.wait(4000);          // blocked + recovery
    await s.move('text=Presence', 800);
    await s.wait(1600);
  }},

  crs: { url: BANK, async fn(s) {
    await login();
    await setScore(0.95);
    await s.wait(900);
    await s.clickIf('button:has-text("Sign in")', 700);
    await s.wait(1400);
    await s.click('button:has-text("Send money")', 800);
    await s.wait(900);
    await s.evaluate(() => { const i = document.querySelector('input[inputmode="decimal"]'); if (i) { const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set; set.call(i, '6000'); i.dispatchEvent(new Event('input', { bubbles: true })); } });
    await s.wait(600);
    await s.type('input[placeholder*="what"]', "equipment", 12);
    await s.click('button:has-text("Send")', 800);
    await s.wait(3200);          // CRS KYC panel opens
    await s.click('text=demo: synthetic identity', 800);
    await s.wait(900);
    await s.click('button:has-text("Verify identity")', 700);
    await s.wait(3000);          // TransUnion rejects synthetic
    await s.click('text=reset', 700);
    await s.wait(900);
    await s.click('button:has-text("Verify identity")', 700);
    await s.wait(3200);          // real identity verifies -> approved
  }},

  close: { url: `${CONSOLE}/#/sessions`, async fn(s) {
    await s.wait(1800);
    await s.scroll("window", 100, 900);
    await s.wait(2600);
  }},
};

const ORDER = ["logo", "onboard", "pay", "monitor", "console", "sessions", "integrations", "fraud", "crs", "close"];

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
  console.log("durations:", JSON.stringify(durations));
}
main();
