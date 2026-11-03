import { readFileSync } from "node:fs";
import { join } from "node:path";

// Site copy must not use the words "know" or "every" (whole words,
// case-insensitive): landing page, marketing header and footer, metadata,
// the app pages, and the case view. A dot before the word (as in the
// `.every()` array method) does not count.
const files = [
  "app/page.tsx",
  "components/marketing.tsx",
  "app/layout.tsx",
  "app/accuracy/page.tsx",
  "app/app/accuracy/page.tsx",
  "app/app/agent/page.tsx",
  "app/app/agent/recorded/page.tsx",
  "app/app/private/page.tsx",
  "app/app/company/[ticker]/page.tsx",
  "app/app/layout.tsx",
  "app/app/watchlist/page.tsx",
  "app/not-found.tsx",
  "components/case-view.tsx",
];
const banned = /(?<![.\w])(know|every)\b/i;
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
