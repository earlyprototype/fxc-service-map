import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(new URL("../scripts/check-catalogue.mjs", import.meta.url));
const published = new URL("../_data/entities.json", import.meta.url);
const fixture = {
  partners: [{ id: "partner" }],
  categories: [{ id: "category" }],
  pillars: [{ id: "pillar" }],
  services: [{ id: "service", partner: "partner", category: "category", soft: null, pillar: "pillar" }],
  roles: [{ partner: "partner", target: "service" }],
};

function runCheck(...args) {
  const result = spawnSync(process.execPath, [script, ...args], { encoding: "utf8" });
  if (result.error) throw result.error;
  return result;
}

test("the default command validates the published catalogue without writing to it", () => {
  const before = statSync(published, { bigint: true }).mtimeNs;
  const result = runCheck();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(statSync(published, { bigint: true }).mtimeNs, before);
});

for (const [name, mutate, error] of [
  ["duplicate service ID", d => d.services.push(d.services[0]), /duplicate.*service/i],
  ["ID shared by two collections", d => { d.pillars[0].id = "category"; }, /duplicate.*category/i],
  ["unresolved partner", d => { d.services[0].partner = "missing"; }, /partner.*missing/i],
  ["category of the wrong type", d => { d.services[0].category = "partner"; }, /category.*partner/i],
  ["unresolved soft category", d => { d.services[0].soft = "missing"; }, /soft.*missing/i],
  ["unresolved pillar", d => { d.services[0].pillar = "missing"; }, /pillar.*missing/i],
  ["unresolved role partner", d => { d.roles[0].partner = "missing"; }, /partner.*missing/i],
  ["unresolved role target", d => { d.roles[0].target = "missing"; }, /target.*missing/i],
  ["role target outside the graph", d => { d.roles[0].target = "pillar"; }, /target.*pillar/i],
]) {
  test(`the command reports ${name} and leaves its input intact`, t => {
    const data = structuredClone(fixture);
    mutate(data);
    const input = new URL(`./catalogue-${randomUUID()}.json`, import.meta.url);
    const json = JSON.stringify(data);
    writeFileSync(input, json, { flag: "wx" });
    t.after(() => unlinkSync(input));
    const result = runCheck(fileURLToPath(input));
    assert.equal(result.status, 1, result.stderr);
    assert.match(result.stderr, error);
    assert.equal(readFileSync(input, "utf8"), json);
  });
}
