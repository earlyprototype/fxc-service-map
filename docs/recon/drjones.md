# DrJones Recon Brief: `earlyprototype/fxc-service-map`
*Scout: Lt. Stridula (Long-Range Recon Wing) | State: `near_complete` | Recorded: 2026-11-26T21:53:12Z*

## Summary
FactoryXChange helps digital strategists match a client need to a service and its delivery partner. The catalogue contains 73 services, 17 partners, 6 categories and 5 pillars. All IDs were unique and every graph reference resolved. The four files on main are index.html, _data/entities.json, .nojekyll and a two-line README. The page provides search, filters, service details, clipboard export and Worker-backed chat.

- **CI / Test Command:** `Main has no test suite, CI workflow or documented check command. The read-only JSON check `python -B -c "import json, pathlib; json.loads(pathlib.Path('_data/entities.json').read_bytes())"` passed. On the preservation branch, `python build_fxc_map.py` checks catalogue relationships and rewrites two generated files.`
- **Risks / Blockers:** The live Worker and browser rendering remain unverified. Chat retry and startup failures were reproduced in memory. No explicit TODO or FIXME markers were found. The checkout stayed clean throughout recon.

## Recommended Actions
### [tier1_deterministic_fix] Keep the local chat server’s API key outside its public directory
- **Rationale:** On the preservation branch, chat_server.py serves the repository root, reads chat_config.json from that same directory and listens on all interfaces. A configured key can therefore be served as a static file. See 599f627:chat_server.py at lines 28, 172 and 201.
- **Acceptance Criteria:** The dev server binds to loopback by default, serves only public map assets and reads credentials from outside the served directory.

### [tier1_deterministic_fix] Keep failed chat turns out of the next request
- **Rationale:** A simulated network failure left the failed question in history. The next send included both questions. The error message also directed the visitor to run chat_server.py, which is absent from main. [Chat submit handler](C:/gant-ops/readonly_refs/earlyprototype__fxc-service-map/index.html:379)
- **Acceptance Criteria:** After a network failure or invalid JSON response, retry sends the last successful conversation plus the new question once. Hosted users see a retry message appropriate to the Worker.

### [tier1_deterministic_fix] Handle catalogue and graph startup failures
- **Rationale:** When the catalogue response contained invalid JSON, initialization rejected without displaying an error. Clicking Reset then threw because the graph did not exist. The page also loads vis-network from an unversioned CDN URL. [Map initialization](C:/gant-ops/readonly_refs/earlyprototype__fxc-service-map/index.html:150)
- **Acceptance Criteria:** A missing catalogue, invalid JSON or unavailable graph library produces a visible load error. Graph controls become active only after initialization succeeds.

### [tier2_discretionary_finish] Give maintainers one read-only catalogue check
- **Rationale:** The current catalogue passed the ID and relationship checks. Main has no repeatable way to catch the next broken partner, category, pillar or role reference before publication.
- **Acceptance Criteria:** The README names one command that checks duplicate IDs and unresolved references without rewriting files. It passes on the current catalogue and exits nonzero for a dangling reference.

### [human_decision_required] Choose the source of truth for future releases
- **Rationale:** `git log -n 15 --oneline` at HEAD returned only `b06c3f2 align chat caps; graceful chat error`. Its child `599f627` on `origin/codex/preserve-fxc-source` contains the catalogue builder, service index, Worker, local server and operating notes. The frontend is identical on both branches.
- **Acceptance Criteria:** The author names the branch where maintainers edit the catalogue and Worker, and records how those changes reach the published map.

> **Field Dispatch:** Lt. Stridula to HQ: all 73 services accounted for. While the General defends democracy in Project Zomboid, I found the maintenance manual one branch over.
