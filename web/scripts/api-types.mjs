/**
 * Generate the API's types from the server's own OpenAPI schema.
 *
 * The response models are the domain models, so the schema FastAPI derives
 * from them is the contract; writing it out again by hand in TypeScript is a
 * second copy that drifts silently. `src/lib/schema.ts` is generated and
 * committed, and `--check` fails when it no longer matches the server, which
 * is how `just check-web` catches a Python change the client was not told of.
 *
 * Usage: pnpm api-types [--check]
 */
import openapiTS, { astToString } from "openapi-typescript";
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const TARGET = path.join(ROOT, "web/src/lib/schema.ts");
const HEADER =
  "/**\n * Generated from the API's OpenAPI schema by `just api-types`. Do not edit:\n" +
  " * change the Python models, then regenerate. `just check-web` fails on drift.\n */\n\n";

const schema = JSON.parse(
  execFileSync("uv", ["run", "python", "scripts/openapi.py"], { cwd: ROOT, encoding: "utf-8", maxBuffer: 1 << 26 }),
);
/** Every schema reachable from `node` through a `$ref`. */
function reachable(node, schemas, seen = new Set()) {
  if (Array.isArray(node)) node.forEach((item) => reachable(item, schemas, seen));
  else if (node && typeof node === "object") {
    const ref = typeof node.$ref === "string" ? node.$ref.split("/").pop() : undefined;
    if (ref && !seen.has(ref)) {
      seen.add(ref);
      reachable(schemas[ref], schemas, seen);
    }
    Object.values(node).forEach((value) => reachable(value, schemas, seen));
  }
  return seen;
}

// A response carries every field, defaults included — the server serializes
// the whole model — so a response model's fields are all required here, and
// the client never guards against an absence that cannot happen. What the
// client sends keeps its defaults optional: those it may leave out.
const schemas = schema.components.schemas;
const sent = reachable(
  Object.values(schema.paths).flatMap((path) => Object.values(path).map((operation) => operation.requestBody)),
  schemas,
);
for (const [name, model] of Object.entries(schemas)) {
  if (!sent.has(name) && model.properties) model.required = Object.keys(model.properties);
}
const generated = HEADER + astToString(await openapiTS(schema, { defaultNonNullable: false }));

if (process.argv.includes("--check")) {
  const current = await readFile(TARGET, "utf-8").catch(() => "");
  if (current !== generated) {
    console.error("src/lib/schema.ts is out of date with the API. Run `just api-types` and commit the result.");
    process.exit(1);
  }
  console.log("src/lib/schema.ts matches the API.");
} else {
  await writeFile(TARGET, generated);
  console.log(`Wrote ${path.relative(ROOT, TARGET)}`);
}
