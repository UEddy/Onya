// Fail the build if a public env variable name could expose a secret.
// Only names are inspected, never values.
const banned = /(TOKEN|KEY|SECRET)/;
const offenders = Object.keys(process.env).filter(
  (name) => name.startsWith("NEXT_PUBLIC_") && banned.test(name),
);
if (process.env.NEXT_PUBLIC_API_BASE) offenders.push("NEXT_PUBLIC_API_BASE");
if (offenders.length > 0) {
  console.error(
    `Public env names must not contain TOKEN, KEY or SECRET: ${offenders.join(", ")}`,
  );
  process.exit(1);
}
