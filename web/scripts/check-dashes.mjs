import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const banned = ["\u2014", "\u2013"];
const roots = ["app", "components"];
const failures = [];

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      walk(path);
      continue;
    }
    const text = readFileSync(path, "utf8");
    const lines = text.split("\n");
    lines.forEach((line, index) => {
      if (banned.some((char) => line.includes(char))) {
        failures.push(`${path}:${index + 1}`);
      }
    });
  }
}

for (const root of roots) walk(join(process.cwd(), root));

if (failures.length > 0) {
  console.error(`Em dash or en dash found:\n${failures.join("\n")}`);
  process.exit(1);
}
