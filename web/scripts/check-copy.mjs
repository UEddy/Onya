import { readFileSync } from "node:fs";
import { join } from "node:path";

// Marketing copy must not use the words "know" or "every" (whole words,
// case-insensitive): landing page, marketing header and footer, metadata.
const files = ["app/page.tsx", "components/marketing.tsx", "app/layout.tsx"];
const banned = /\b(know|every)\b/i;
const failures = [];

for (const file of files) {
  const text = readFileSync(join(process.cwd(), file), "utf8");
  text.split("\n").forEach((line, index) => {
    if (banned.test(line)) {
      failures.push(`${file}:${index + 1}: ${line.trim()}`);
    }
  });
}

if (failures.length > 0) {
  console.error(`Banned marketing word found:\n${failures.join("\n")}`);
  process.exit(1);
}
