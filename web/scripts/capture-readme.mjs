// Recapture the README screenshots from the site at 1440x900, light theme.
// Usage: node scripts/capture-readme.mjs [outDir]
// Env: BASE_URL (default https://onya-g8f4.vercel.app),
//      HTTPS_PROXY/https_proxy (used for the browser when set).
// The agent shot runs one live check through the site; it can take minutes.
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(here, "..");

const base = process.env.BASE_URL ?? "https://onya-g8f4.vercel.app";
const outDir = resolve(process.argv[2] ?? resolve(webRoot, "..", "docs", "img"));
mkdirSync(outDir, { recursive: true });

const proxyServer = process.env.HTTPS_PROXY ?? process.env.https_proxy;
const browser = await chromium.launch(
  proxyServer ? { proxy: { server: proxyServer } } : {},
);
const page = await browser.newPage({
  viewport: { width: 1440, height: 900 },
  colorScheme: "light",
});

async function shot(name, url, setup) {
  await page.goto(url, { waitUntil: "networkidle", timeout: 90000 });
  await page.waitForTimeout(1200);
  if (setup) await setup();
  await page.waitForTimeout(800);
  await page.screenshot({ path: resolve(outDir, name) });
  console.log("saved", name);
}

await shot("landing-hero.png", `${base}/`);

await shot("case-evidence.png", `${base}/app/company/SNBR`, async () => {
  const fig = page.getByTitle("Show the evidence for this figure").first();
  await fig.scrollIntoViewIfNeeded();
  await fig.click();
});

await shot("agent-memo.png", `${base}/app/agent`, async () => {
  await page.getByRole("button", { name: /run the check/i }).click();
  await page.getByText(/recommended actions/i).first().waitFor({
    timeout: 280000,
  });
  await page.getByText(/recommended actions/i).first().scrollIntoViewIfNeeded();
});

await browser.close();
console.log("done", outDir);
