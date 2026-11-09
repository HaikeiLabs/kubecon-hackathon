// Scripted, headed walkthrough of the Friction Desk UI for screen recording.
//
//   node demo/walkthrough.mjs                       # UI at http://127.0.0.1:5173
//   UI_URL=http://localhost:8081 node demo/walkthrough.mjs
//   PACE=1.5 node demo/walkthrough.mjs              # slower (multiplies every pause)
//   SHOTS=1 node demo/walkthrough.mjs               # save a screenshot per caption to demo/out/shots/
//   VIDEO=1 node demo/walkthrough.mjs               # Playwright .webm to demo/out/ (needs: npx playwright install ffmpeg)
//
// Uses the installed Google Chrome (channel "chrome"); no browser download.
// Each run files one new report and confirms it, so the inbox grows by one.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const UI_URL = (process.env.UI_URL ?? "http://127.0.0.1:5173").replace(/\/+$/, "");
const PACE = Number(process.env.PACE ?? 1);
const OUT = join(dirname(fileURLToPath(import.meta.url)), "out");
const SIZE = { width: 1440, height: 900 };

const REPORT = {
  description: "Wi-Fi keeps dropping in Hall C during the sessions, I can't stay connected long enough to pull the demo repo",
  location: "Hall C, afternoon track",
};

let shot = 0;
const pause = (ms) => new Promise((r) => setTimeout(r, ms * PACE));

// A caption bar at the bottom of the page narrates each step for the recording.
async function caption(page, text, ms = 2200) {
  await page.evaluate((t) => {
    let el = document.getElementById("demo-caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "demo-caption";
      Object.assign(el.style, {
        position: "fixed", left: "50%", bottom: "28px", transform: "translateX(-50%)", zIndex: 99999,
        maxWidth: "80vw", padding: "14px 22px", borderRadius: "12px", font: "600 22px/1.35 system-ui, sans-serif",
        color: "#fff", background: "rgba(17, 24, 39, 0.88)", boxShadow: "0 8px 30px rgba(0,0,0,.35)", pointerEvents: "none",
      });
      document.body.appendChild(el);
    }
    el.textContent = t;
  }, text);
  console.log(`▸ ${text}`);
  await pause(ms * 0.4);
  if (process.env.SHOTS === "1") {
    mkdirSync(join(OUT, "shots"), { recursive: true });
    await page.screenshot({ path: join(OUT, "shots", `${String(++shot).padStart(2, "0")}.png`) });
  }
  await pause(ms * 0.6);
}

async function spotlight(locator, ms = 1800) {
  await locator.scrollIntoViewIfNeeded();
  await locator.evaluate((el) => {
    el.dataset.demoOutline = el.style.outline;
    el.style.outline = "4px solid #f59e0b";
    el.style.outlineOffset = "4px";
  });
  await pause(ms);
  await locator.evaluate((el) => { el.style.outline = el.dataset.demoOutline ?? ""; });
}

const browser = await chromium.launch({ channel: "chrome", headless: false, args: [`--window-size=${SIZE.width},${SIZE.height + 120}`] });
const context = await browser.newContext({
  viewport: SIZE,
  ...(process.env.VIDEO === "1" ? (mkdirSync(OUT, { recursive: true }), { recordVideo: { dir: OUT, size: SIZE } }) : {}),
});
const page = await context.newPage();

try {
  // 1. Attendee files a report.
  await page.goto(`${UI_URL}/#/report`);
  await page.getByRole("heading", { name: "Report a problem" }).waitFor();
  await caption(page, "An attendee reports a problem: no login, just what happened and where");
  await page.getByLabel(/What's the problem/).pressSequentially(REPORT.description, { delay: 28 / PACE });
  await page.getByLabel(/Where, or which session/).pressSequentially(REPORT.location, { delay: 28 / PACE });
  await pause(600);
  await page.getByRole("button", { name: "Send report" }).click();
  await page.getByRole("heading", { name: /your report was sent/ }).waitFor();
  await caption(page, "On submit, the API links the text to ontology concepts and runs triage");

  // 2. Organizer inbox: concept chips + AI proposal.
  await page.getByRole("link", { name: "Organizer" }).click();
  await page.getByRole("heading", { name: "Organizer inbox" }).waitFor();
  // Recording-only layout: keep the bucket list short and the side column pinned so
  // the Governance panel stays on screen next to the report card.
  await page.addStyleTag({
    content: `section[aria-labelledby="issues-h"] { max-height: 300px; overflow: auto; }
              .side { position: sticky; top: 12px; align-self: start; }`,
  });
  const card = page.locator("article.inbox-card", { hasText: REPORT.description.slice(0, 40) }).first();
  await card.waitFor();
  await caption(page, "The organizer inbox: the new report is waiting for review");
  await spotlight(card, 1500);

  const chips = card.getByRole("list", { name: "Ontology concepts" });
  await caption(page, "Ontology concepts: 'Wi-Fi keeps dropping' maps to a SKOS concept via synonyms + hybrid search");
  await spotlight(chips);
  await chips.locator(".chip").first().hover();
  await pause(1500);

  const ai = card.locator(".ai").first();
  await caption(page, "AI suggestion: file it under the matching bucket, with confidence and rationale");
  await spotlight(ai, 2600);

  // 3. Governance: the attendee agent may not confirm.
  const governance = page.locator("section.governance");
  await caption(page, "Governance: tool calls go through a fail-closed agentware policy");
  await spotlight(governance, 1500);
  await governance.getByLabel("Attendee agent").check();
  await caption(page, "Acting as the attendee agent, try to confirm the assignment…");
  await card.getByRole("button", { name: /^Confirm (match|new bucket)$/ }).click();
  const denied = card.getByRole("alert");
  await denied.waitFor();
  await caption(page, "Denied by policy, and nothing changed. The deny is in the audit log", 1200);
  await spotlight(denied, 1800);
  await spotlight(governance.locator("li.deny").first(), 2000);

  // 4. Organizer confirms.
  await governance.getByLabel("Organizer").check();
  await caption(page, "Switch to the organizer role and confirm");
  await card.getByRole("button", { name: /^Confirm (match|new bucket)$/ }).click();
  await card.waitFor({ state: "detached", timeout: 15000 });
  await caption(page, "Confirmed: the report left the inbox and the allow is audited", 1200);
  await spotlight(governance.locator("li.allow").first(), 2400);

  await caption(page, "Friction Desk: ontology search on Elastic + governed triage", 3000);
} finally {
  await context.close(); // flushes the optional Playwright video
  await browser.close();
}
console.log("walkthrough complete");
