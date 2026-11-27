import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const catalogue = readFileSync(new URL("../_data/entities.json", import.meta.url), "utf8");
const firstService = JSON.parse(catalogue).services[0];
const graphControls = ["reset", "search", "toggleSecondary", "askAi", "copyCtx", "panelClose", "chatSend"];

// Only the DOM and vis APIs used by startup, selection, Reset and chat are needed here.
class Element {
  children = [];
  listeners = {};
  classes = new Set();
  classList = {
    add: name => this.classes.add(name),
    remove: name => this.classes.delete(name),
    contains: name => this.classes.has(name),
  };
  value = "";
  textContent = "";
  appendChild(child) { this.children.push(child); }
  append(...children) { this.children.push(...children); }
  querySelector(selector) {
    assert.equal(selector, "input");
    return new Element();
  }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  click() { if (!this.disabled) this.onclick?.(); }
}

function openPage({
  loadCatalogue = () => new Response(catalogue), worker, graphAvailable = true,
  createElement = () => new Element(),
} = {}) {
  const elements = {};
  for (const [tag, id] of html.matchAll(/<[^<>]+\bid="([^"]+)"[^<>]*>/g)) {
    elements[id] = Object.assign(new Element(), {
      disabled: /\sdisabled\b/.test(tag),
      hidden: /\shidden\b/.test(tag),
    });
  }
  const requests = [];
  let fits = 0;
  let canvas;
  const vis = {
    DataSet: class {
      constructor(items) { this.ids = items.map(item => item.id); }
      getIds() { return this.ids; }
      update() {}
    },
    Network: class {
      constructor(container) {
        canvas = new Element();
        container.appendChild(canvas);
      }
      once() {}
      on(type, listener) {
        if (type === "click") canvas.onclick = () => listener({ nodes: [firstService.id] });
      }
      getConnectedNodes() { return []; }
      getConnectedEdges() { return []; }
      selectNodes() {}
      fit() { fits++; }
      destroy() {
        canvas.onclick = null;
        elements.graph.children.length = 0;
      }
    },
  };
  runInNewContext(script, {
    document: {
      getElementById: id => elements[id],
      createElement,
      querySelectorAll: selector => selector === "#panel a.node-link" ? [] :
        selector.split(", ").map(id => elements[id.slice(1)]),
    },
    vis: graphAvailable ? vis : undefined,
    fetch: async (url, options) => {
      if (url === "_data/entities.json") return loadCatalogue();
      assert.match(url, /^https:\/\/[^/]+\.workers\.dev\/?$/);
      const payload = JSON.parse(options.body);
      requests.push(payload);
      return worker(payload);
    },
  });
  return {
    elements, requests, fits: () => fits,
    get canvas() { return canvas; },
    send(question) {
      elements.chatInput.value = question;
      return elements.chatForm.listeners.submit({ preventDefault() {} });
    },
  };
}

const settled = () => new Promise(resolve => setImmediate(resolve));

test("the graph script uses a pinned release", () => {
  const source = html.match(/<script src="([^"]*vis-network[^"]*)"/)[1];
  assert.match(source, /vis-network@\d+\.\d+\.\d+\/standalone\/umd\/vis-network\.min\.js$/);
});

test("graph controls become usable after the catalogue and graph are ready", async () => {
  let finishLoad;
  const page = openPage({ loadCatalogue: () => new Promise(resolve => { finishLoad = resolve; }) });
  for (const id of graphControls) assert.equal(page.elements[id].disabled, true, id);
  page.elements.reset.click();
  assert.equal(page.fits(), 0);
  finishLoad(new Response(catalogue));
  await settled();
  for (const id of graphControls) assert.equal(page.elements[id].disabled, false, id);
  assert.equal(page.elements.mapStatus.hidden, true);
  assert.ok(page.elements.pillars.children.length > 0);
  page.elements.reset.click();
  assert.equal(page.fits(), 1);
});

test("a catalogue without metadata opens service details with a blank subtitle", async () => {
  const data = JSON.parse(catalogue);
  delete data.meta;
  const page = openPage({ loadCatalogue: () => Response.json(data) });
  await settled();
  assert.equal(page.elements.mapStatus.hidden, true);
  assert.equal(page.elements.subtitle.textContent, "");
  page.canvas.click();
  assert.equal(page.elements.panel.classList.contains("open"), true);
  assert.ok(page.elements.panelBody.innerHTML.includes(firstService.label));
  assert.equal(page.elements.panelClose.disabled, false);
});

test("a canvas click after failed legend setup leaves the panel closed and controls disabled", async () => {
  let labels = 0;
  const page = openPage({ createElement(tag) {
    if (tag === "label" && ++labels === 2) throw new Error("Pillar control creation failed");
    return new Element();
  } });
  await settled();
  assert.match(page.elements.mapStatus.textContent, /could not load/i);
  assert.equal(page.elements.mapStatus.hidden, false);
  page.canvas.click();
  assert.equal(page.elements.panel.classList.contains("open"), false);
  assert.equal(page.elements.graph.children.length, 0);
  assert.equal(page.elements.pillars.children.length, 0);
  for (const id of graphControls) assert.equal(page.elements[id].disabled, true, id);
  page.elements.reset.click();
  assert.equal(page.fits(), 0);
});

for (const [name, options] of [
  ["missing catalogue", { loadCatalogue: () => new Response(catalogue, { status: 404 }) }],
  ["network failure", { loadCatalogue: () => { throw new TypeError("offline"); } }],
  ["invalid catalogue JSON", { loadCatalogue: () => new Response("{") }],
  ["missing graph library", { graphAvailable: false }],
]) {
  test(`startup shows a persistent load error for ${name}`, async () => {
    const page = openPage(options);
    await settled();
    assert.match(page.elements.mapStatus.textContent, /could not load/i);
    assert.equal(page.elements.mapStatus.hidden, false);
    for (const id of graphControls) assert.equal(page.elements[id].disabled, true, id);
    assert.equal(page.elements.pillars.children.length, 0);
    page.elements.reset.click();
    assert.equal(page.fits(), 0);
  });
}

for (const [name, failure, message] of [
  ["network failure", () => { throw new TypeError("offline"); }, /try again/i],
  ["invalid JSON", () => new Response("{"), /try again/i],
  ["Worker error", () => Response.json({ error: "Busy" }, { status: 429 }), /Busy/],
  ["malformed reply", () => Response.json({ reply: 42 }), /try again/i],
]) {
  test(`chat retry after ${name} includes only completed turns and the new question`, async () => {
    const page = openPage({ worker: ({ messages }) => {
      if (messages.at(-1).text === "Failed question") return failure();
      return Response.json({ reply: "First answer" });
    } });
    await settled();
    await page.send("First question");
    await page.send("Failed question");
    const error = page.elements.chatMsgs.children.at(-1).textContent;
    assert.match(error, message);
    assert.doesNotMatch(error, /chat_server|python/i);
    await page.send("New question");
    assert.deepEqual(page.requests[2].messages, [
      { role: "user", text: "First question" },
      { role: "assistant", text: "First answer" },
      { role: "user", text: "New question" },
    ]);
    assert.deepEqual(page.requests[2].focus, JSON.parse(catalogue).services.map(s => s.id));
  });
}

test("chat displays a limited Worker reply and retries the same question once", async () => {
  const notice = "Chat is busy. Please try again.";
  const replies = [
    { reply: "First answer", limited: false },
    { reply: notice, limited: true },
    { reply: "Second answer" },
  ];
  const page = openPage({ worker: () => Response.json(replies.shift()) });
  await settled();
  await page.send("First question");
  await page.send("Second question");
  assert.equal(page.elements.chatMsgs.children.at(-1).innerHTML, notice);

  await page.send("Second question");
  assert.deepEqual(page.requests[2], {
    messages: [
      { role: "user", text: "First question" },
      { role: "assistant", text: "First answer" },
      { role: "user", text: "Second question" },
    ],
    focus: JSON.parse(catalogue).services.map(s => s.id),
  });
});

test("a second submit while waiting sends once and preserves the next draft", async () => {
  let finishReply;
  const page = openPage({ worker: () => new Promise(resolve => { finishReply = resolve; }) });
  await settled();
  const pending = page.send("First question");
  page.send("Next draft");
  assert.equal(page.requests.length, 1);
  assert.equal(page.elements.chatInput.value, "Next draft");
  finishReply(Response.json({ reply: "Answer" }));
  await pending;
  assert.equal(page.elements.chatSend.disabled, false);
});

test("chat keeps the Worker's eight-message request limit", async () => {
  const page = openPage({ worker: () => Response.json({ reply: "Answer" }) });
  await settled();
  for (let i = 1; i <= 6; i++) await page.send(`Question ${i}`);
  assert.equal(page.requests.at(-1).messages.length, 8);
  assert.deepEqual(page.requests.at(-1).messages.at(-1), { role: "user", text: "Question 6" });
});
