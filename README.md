# FactoryXChange 2.0 Service Map

Interactive pathfinding map with chat provided by a Cloudflare Worker.

## Check the catalogue

Run this read-only check from the repository root.

```sh
node scripts/check-catalogue.mjs
```

The command reads `_data/entities.json` and exits nonzero on the first duplicate ID or unresolved reference. It checks each service's partner, primary category, optional secondary category and pillar. It also checks that each role links a partner to a graph node.

Run the offline regression tests with `node --test`.
