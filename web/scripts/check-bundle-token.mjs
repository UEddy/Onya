// Fail if the ONYA_DEMO_TOKEN value appears anywhere in the client
// bundle (.next/static). Run after a build made with a dummy token:
//   ONYA_DEMO_TOKEN=dummy-token-for-bundle-test npm run build
//   ONYA_DEMO_TOKEN=dummy-token-for-bundle-test node scripts/check-bundle-token.mjs
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const values = [process.env.ONYA_DEMO_TOKEN || ""].filter(Boolean);
if (values.length === 0) {
  console.error("No dummy secret value set; nothing to check for.");
  process.exit(1);
}

const root = join(process.cwd(), ".next", "static");
const hits = [];
function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      walk(path);
      continue;
    }
    const text = readFileSync(path, "utf8");
    if (values.some((v) => text.includes(v))) hits.push(path);
  }
}
walk(root);

if (hits.length > 0) {
  console.error(`Demo token value found in client bundle:\n${hits.join("\n")}`);
  process.exit(1);
}
console.log("Client bundle contains no demo token value.");
