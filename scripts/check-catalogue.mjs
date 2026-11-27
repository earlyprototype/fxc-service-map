import { readFileSync } from "node:fs";

function checkCatalogue(data) {
  const entities = ["categories", "partners", "pillars", "services"];
  for (const group of [...entities, "roles"]) {
    if (!Array.isArray(data?.[group])) throw new Error(`Expected an array at ${group}`);
  }

  const groupById = new Map();
  for (const group of entities) {
    for (const [index, record] of data[group].entries()) {
      const id = record?.id;
      if (typeof id !== "string" || !id.trim()) throw new Error(`Missing ID at ${group}[${index}]`);
      if (groupById.has(id)) throw new Error(`Duplicate ID "${id}" in ${group} (first seen in ${groupById.get(id)})`);
      groupById.set(id, group);
    }
  }

  function requireReference(field, id, ...groups) {
    if (!groups.includes(groupById.get(id))) {
      throw new Error(`${field} references "${id}". Expected an ID from ${groups.join(", ")}.`);
    }
  }

  for (const service of data.services) {
    requireReference(`${service.id}.partner`, service.partner, "partners");
    requireReference(`${service.id}.category`, service.category, "categories");
    if (service.soft != null) requireReference(`${service.id}.soft`, service.soft, "categories");
    requireReference(`${service.id}.pillar`, service.pillar, "pillars");
  }
  for (const [index, role] of data.roles.entries()) {
    requireReference(`roles[${index}].partner`, role?.partner, "partners");
    requireReference(`roles[${index}].target`, role?.target, "services", "categories", "partners");
  }
}

try {
  const source = process.argv[2] ?? new URL("../_data/entities.json", import.meta.url);
  const data = JSON.parse(readFileSync(source, "utf8"));
  checkCatalogue(data);
  console.log(`Catalogue OK. Checked IDs and references for ${data.services.length} services, ${data.partners.length} partners, ${data.categories.length} categories, ${data.pillars.length} pillars and ${data.roles.length} roles.`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
