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

  enroll: { url: `${DAEMON}/#/enroll`, async fn(s) {
    await s.wait(1700);
    await s.move('text=Begin', 900);
    await s.wait(1200);
  }},

  monitor: { url: DAEMON, async fn(s) {
    await setScore(0.93);
    await s.wait(2400);          // the trust gauge + "You"
    await s.scroll("window", 300, 1200);
    await s.wait(2800);          // the live signals the model reads
  }},

  pay: { url: BANK, async fn(s) {
    await setScore(0.95);
    await s.wait(800);
    await s.click('text=Enter', 700);
    await s.wait(1600);
    await s.type('input[placeholder*="what\'s this"]', "rent — november", 12);
    await s.wait(600);
    await s.click('button:has-text("Send")', 800);
    await s.wait(3600);          // verification sequence + approval
    await s.move('text=Presence', 900);   // draw the eye to the four signals
    await s.wait(1600);
    await s.move('text=Identity', 800);
    await s.wait(1700);
  }},

  console: { url: `${CONSOLE}/#/overview`, async fn(s) {
    await s.wait(1900);
    await s.move('text=Trust over time', 900);
    await s.wait(2000);          // take in the timeline + four lanes
    await s.scroll("window", 360, 1200);
    await s.wait(3200);          // watch the live stream flow
    await s.scroll("window", 0, 1000);
    await s.wait(1100);
  }},

  identities: { url: `${CONSOLE}/#/identities`, async fn(s) {
    await s.wait(2000);
    await s.move('text=Margaret Okafor', 800);
    await s.wait(1600);
    await s.move('text=Kayla Brennan', 1000);
    await s.wait(3000);          // linger on the synthetic-identity card
  }},

  fraud: { url: BANK, async fn(s) {
    await login();
    await setScore(0.05);        // someone else at the keyboard
    await s.wait(900);
    await s.click('text=Enter', 700);
    await s.wait(1500);
    await s.type('input[placeholder*="what\'s this"]', "wire transfer", 12);
    await s.wait(500);
    await s.click('button:has-text("Send")', 800);
    await s.wait(4200);          // denial + recovery panel
    await s.move('text=Presence', 800);
    await s.wait(1600);
  }},

  crs: { url: BANK, async fn(s) {
    await login();
    await setScore(0.95);
    await s.wait(900);
    await s.click('text=Enter', 700);
    await s.wait(1200);
    await s.evaluate(() => { const i = document.querySelector('input[inputmode="decimal"]'); if (i) { const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set; set.call(i, '6000'); i.dispatchEvent(new Event('input', { bubbles: true })); } });
    await s.wait(600);
    await s.type('input[placeholder*="what\'s this"]', "equipment", 12);
    await s.click('button:has-text("Send")', 800);
    await s.wait(3200);          // CRS KYC panel opens
    await s.click('text=demo: synthetic identity', 800);
    await s.wait(900);
    await s.click('button:has-text("Verify identity")', 700);
    await s.wait(3000);          // TransUnion rejects synthetic
    await s.click('text=reset', 700);
    await s.wait(900);
    await s.click('button:has-text("Verify identity")', 700);
    await s.wait(3400);          // real identity verifies -> approved
  }},

  close: { url: `${CONSOLE}/#/overview`, async fn(s) {
    await s.wait(2000);
    await s.scroll("window", 120, 1000);
    await s.wait(3000);
  }},
};

const ORDER = ["logo", "enroll", "monitor", "pay", "console", "identities", "fraud", "crs", "close"];

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
