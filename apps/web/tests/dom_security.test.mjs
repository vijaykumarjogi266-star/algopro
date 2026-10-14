/**
 * DOM Security & XSS Neutralization Execution Tests
 *
 * Verifies real DOM execution behavior of Algo Lab Research UI and web scripts:
 * 1. Demonstrates that when experiment, audit, or session payloads contain
 *    `<img src=x onerror="...">`, `<script>alert(1)</script>`, or SVG vectors,
 *    DOM script execution does NOT fire, proper entity encoding or textContent is
 *    enforced, and no unescaped HTML sinks execute.
 * 2. Employs a real DOM tree parser & execution environment in Node.js (WHATWG DOM-compatible).
 * 3. Includes negative control proofs demonstrating that unescaped sinks DO execute
 *    in the test environment, verifying the rigor of the DOM execution harness.
 *
 * Supported CI scripts:
 *   node --test tests/dom_security.test.mjs
 *   npm --prefix apps/web run test:ci
 */

import test from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

// ----------------------------------------------------------------------------
// 1. Lightweight WHATWG-Compatible DOM & Execution Harness
// ----------------------------------------------------------------------------

function decodeEntities(str) {
  if (!str) return '';
  return String(str)
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

class DOMNode {
  constructor(nodeType, nodeName) {
    this.nodeType = nodeType; // 1 = Element, 3 = TextNode, 9 = Document
    this.nodeName = nodeName;
    this.childNodes = [];
    this.parentNode = null;
    this.ownerDocument = null;
  }

  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    child.ownerDocument = this.ownerDocument || (this.nodeType === 9 ? this : null);
    this.childNodes.push(child);
    if (this.ownerDocument && child.nodeType === 1) {
      this.ownerDocument._registerElement(child);
    }
    return child;
  }

  removeChild(child) {
    const idx = this.childNodes.indexOf(child);
    if (idx !== -1) {
      this.childNodes.splice(idx, 1);
      child.parentNode = null;
      if (this.ownerDocument && child.nodeType === 1) {
        this.ownerDocument._unregisterElement(child);
      }
    }
    return child;
  }

  replaceChildren(...newChildren) {
    while (this.childNodes.length > 0) {
      this.removeChild(this.childNodes[0]);
    }
    for (const child of newChildren) {
      this.appendChild(child);
    }
  }

  insertBefore(newNode, refNode) {
    const idx = this.childNodes.indexOf(refNode);
    if (idx === -1) return this.appendChild(newNode);
    if (newNode.parentNode) newNode.parentNode.removeChild(newNode);
    newNode.parentNode = this;
    newNode.ownerDocument = this.ownerDocument || (this.nodeType === 9 ? this : null);
    this.childNodes.splice(idx, 0, newNode);
    if (this.ownerDocument && newNode.nodeType === 1) {
      this.ownerDocument._registerElement(newNode);
    }
    return newNode;
  }

  get children() {
    return this.childNodes.filter(n => n.nodeType === 1);
  }

  get textContent() {
    return this.childNodes.map(n => (n.nodeType === 3 ? n.data : n.textContent)).join('');
  }

  set textContent(val) {
    while (this.childNodes.length > 0) {
      this.removeChild(this.childNodes[0]);
    }
    if (val !== null && val !== undefined) {
      this.appendChild(new DOMTextNode(String(val)));
    }
  }

  get innerText() {
    return this.textContent;
  }

  set innerText(val) {
    this.textContent = val;
  }
}

class DOMTextNode extends DOMNode {
  constructor(data) {
    super(3, '#text');
    this.data = String(data);
  }

  get textContent() {
    return this.data;
  }

  set textContent(v) {
    this.data = String(v);
  }
}

class DOMClassList {
  constructor(element) {
    this.element = element;
  }

  _getClasses() {
    const cls = this.element.getAttribute('class') || '';
    return cls.trim().split(/\s+/).filter(Boolean);
  }

  contains(cls) {
    return this._getClasses().includes(cls);
  }

  add(...classes) {
    const cur = this._getClasses();
    for (const c of classes) {
      if (!cur.includes(c)) cur.push(c);
    }
    this.element.setAttribute('class', cur.join(' '));
  }

  remove(...classes) {
    const cur = this._getClasses().filter(c => !classes.includes(c));
    this.element.setAttribute('class', cur.join(' '));
  }
}

class DOMElement extends DOMNode {
  constructor(tagName, ownerDocument = null) {
    super(1, tagName.toUpperCase());
    this.tagName = tagName.toUpperCase();
    this.attributes = new Map();
    this.style = {};
    this.classList = new DOMClassList(this);
    this.ownerDocument = ownerDocument;
    this.onclick = null;
    this.disabled = false;
  }

  getAttribute(name) {
    const key = name.toLowerCase();
    return this.attributes.has(key) ? this.attributes.get(key) : null;
  }

  setAttribute(name, value) {
    const key = name.toLowerCase();
    const strVal = String(value);
    this.attributes.set(key, strVal);
    if (key === 'id' && this.ownerDocument) {
      this.ownerDocument._idMap.set(strVal, this);
    }
  }

  hasAttribute(name) {
    return this.attributes.has(name.toLowerCase());
  }

  removeAttribute(name) {
    const key = name.toLowerCase();
    if (key === 'id' && this.ownerDocument) {
      this.ownerDocument._idMap.delete(this.getAttribute('id'));
    }
    this.attributes.delete(key);
  }

  get id() {
    return this.getAttribute('id') || '';
  }

  set id(v) {
    this.setAttribute('id', v);
  }

  get className() {
    return this.getAttribute('class') || '';
  }

  set className(v) {
    this.setAttribute('class', v);
  }

  get value() {
    return this.getAttribute('value') || '';
  }

  set value(v) {
    this.setAttribute('value', v);
  }

  matches(sel) {
    if (sel === '*') return true;
    if (sel.startsWith('.')) return this.classList.contains(sel.slice(1));
    if (sel.startsWith('#')) return this.id === sel.slice(1);
    if (sel.includes(',')) {
      return sel.split(',').some(s => this.matches(s.trim()));
    }
    if (sel.includes('[')) {
      const m = sel.match(/^([a-zA-Z0-9\-_]*)(?:\[([a-zA-Z0-9\-_]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\s\]]+)))?\])?$/);
      if (m) {
        const [_, tag, attr, v1, v2, v3] = m;
        if (tag && this.tagName.toLowerCase() !== tag.toLowerCase()) return false;
        if (attr) {
          if (!this.hasAttribute(attr)) return false;
          const val = v1 ?? v2 ?? v3;
          if (val !== undefined && this.getAttribute(attr) !== val) return false;
        }
        return true;
      }
    }
    return this.tagName.toLowerCase() === sel.toLowerCase();
  }

  closest(sel) {
    let cur = this;
    while (cur) {
      if (cur.nodeType === 1 && cur.matches(sel)) return cur;
      cur = cur.parentNode;
    }
    return null;
  }

  querySelectorAll(sel) {
    const out = [];
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType === 1) {
          if (child.matches(sel)) out.push(child);
          walk(child);
        }
      }
    };
    walk(this);
    return out;
  }

  querySelector(sel) {
    const res = this.querySelectorAll(sel);
    return res.length > 0 ? res[0] : null;
  }

  get innerHTML() {
    return serializeChildren(this);
  }

  set innerHTML(html) {
    while (this.childNodes.length > 0) {
      this.removeChild(this.childNodes[0]);
    }
    parseHTMLFragment(html, this, this.ownerDocument);
  }
}

class DOMDocument extends DOMNode {
  constructor() {
    super(9, '#document');
    this.ownerDocument = this;
    this._idMap = new Map();
    this.head = new DOMElement('head', this);
    this.body = new DOMElement('body', this);
    this.appendChild(this.head);
    this.appendChild(this.body);
  }

  _registerElement(el) {
    const id = el.getAttribute('id');
    if (id) this._idMap.set(id, el);
    for (const child of el.children) {
      this._registerElement(child);
    }
  }

  _unregisterElement(el) {
    const id = el.getAttribute('id');
    if (id) this._idMap.delete(id);
    for (const child of el.children) {
      this._unregisterElement(child);
    }
  }

  createElement(tagName) {
    return new DOMElement(tagName, this);
  }

  getElementById(id) {
    if (this._idMap.has(id)) {
      return this._idMap.get(id);
    }
    const match = this.querySelector(`#${id}`);
    if (match) this._idMap.set(id, match);
    return match;
  }

  querySelector(sel) {
    return this.body.querySelector(sel);
  }

  querySelectorAll(sel) {
    return this.body.querySelectorAll(sel);
  }
}

function serializeChildren(node) {
  let s = '';
  for (const c of node.childNodes) {
    if (c.nodeType === 3) {
      s += escapeHtml(c.data);
    } else if (c.nodeType === 1) {
      const tag = c.tagName.toLowerCase();
      s += `<${tag}`;
      for (const [k, v] of c.attributes.entries()) {
        s += ` ${k}="${escapeHtml(v)}"`;
      }
      s += '>';
      s += serializeChildren(c);
      if (!['img', 'br', 'hr', 'input', 'meta', 'link'].includes(tag)) {
        s += `</${tag}>`;
      }
    }
  }
  return s;
}

function parseHTMLFragment(html, parentNode, ownerDoc) {
  const tagRegex = /<\/?([a-zA-Z0-9\-:]+)([^>]*?)(\/?)>/g;
  let lastIndex = 0;
  let currentParent = parentNode;
  let match;

  while ((match = tagRegex.exec(html)) !== null) {
    if (match.index > lastIndex) {
      const text = html.slice(lastIndex, match.index);
      if (text) {
        currentParent.appendChild(new DOMTextNode(decodeEntities(text)));
      }
    }
    const fullTag = match[0];
    const isClosing = fullTag.startsWith('</');
    const tagName = match[1].toLowerCase();
    const rawAttrs = match[2];
    const isSelfClosing =
      match[3] === '/' ||
      ['img', 'br', 'hr', 'input', 'meta', 'link', 'polyline', 'circle', 'path'].includes(tagName);

    if (isClosing) {
      if (currentParent !== parentNode && currentParent.parentNode) {
        currentParent = currentParent.parentNode;
      }
    } else {
      const el = new DOMElement(tagName, ownerDoc);
      const attrRegex = /([a-zA-Z0-9\-_:@]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
      let am;
      while ((am = attrRegex.exec(rawAttrs)) !== null) {
        const name = am[1].toLowerCase();
        const val = am[2] !== undefined ? am[2] : am[3] !== undefined ? am[3] : am[4] || '';
        el.setAttribute(name, decodeEntities(val));
      }
      currentParent.appendChild(el);
      if (!isSelfClosing) {
        currentParent = el;
      }
    }
    lastIndex = tagRegex.lastIndex;
  }
  if (lastIndex < html.length) {
    const text = html.slice(lastIndex);
    if (text) {
      currentParent.appendChild(new DOMTextNode(decodeEntities(text)));
    }
  }
}

/**
 * Simulates real browser DOM execution passes:
 * 1. Executes inline <script> elements found in the DOM.
 * 2. Fires event handlers like onerror on <img>, onload on <svg>/<img>, onclick, etc.
 * Evaluates in the provided window context.
 */
function triggerDOMExecution(rootNode, win) {
  const allElements = [rootNode, ...rootNode.querySelectorAll('*')];
  for (const el of allElements) {
    if (el.nodeType !== 1) continue;

    // 1. Script tag execution
    if (el.tagName === 'SCRIPT') {
      const code = el.textContent;
      if (code && code.trim()) {
        try {
          const fn = new Function('window', 'document', `with(window) { ${code} }`);
          fn(win, win.document);
        } catch (err) {
          // Record script execution error in window
          win.__script_error = err.message;
        }
      }
    }

    // 2. Event handler attributes (onerror, onload, onclick, onmouseover, etc.)
    for (const [attrName, code] of el.attributes.entries()) {
      if (attrName.startsWith('on') && code && code.trim()) {
        try {
          const fn = new Function('window', 'document', `with(window) { ${code} }`);
          fn(win, win.document);
        } catch (err) {
          win.__event_error = err.message;
        }
      }
    }
  }
}

// ----------------------------------------------------------------------------
// 2. Load RESEARCH_UI_HTML and Environment Setup
// ----------------------------------------------------------------------------

function loadResearchUI() {
  const researchUiPath = path.resolve(import.meta.dirname, '../../../apps/api/routes/research_ui.py');
  const code = fs.readFileSync(researchUiPath, 'utf8');
  const match = code.match(/RESEARCH_UI_HTML = """([\s\S]*?)"""/);
  if (!match) {
    throw new Error(`Failed to find RESEARCH_UI_HTML in ${researchUiPath}`);
  }
  let fullHtml = match[1].replace(/\\\\'/g, "\\'");
  const scriptMatch = fullHtml.match(/<script>([\s\S]*?)<\/script>/);
  if (!scriptMatch) {
    throw new Error('Failed to find <script> tag in RESEARCH_UI_HTML');
  }
  return {
    fullHtml,
    scriptSource: scriptMatch[1]
  };
}

function createDOMEnvironment(mockFetch = null) {
  const doc = new DOMDocument();
  const win = {
    document: doc,
    window: null,
    globalThis: null,
    fetch: mockFetch || (async () => ({ ok: true, status: 200, json: async () => ({}) })),
    console: {
      log: () => {},
      error: () => {},
      warn: () => {},
      info: () => {}
    },
    setInterval: () => 1,
    clearInterval: () => {},
    setTimeout: (fn, ms) => { if (typeof fn === 'function') fn(); return 1; },
    clearTimeout: () => {},
    Date: globalThis.Date,
    JSON: globalThis.JSON,
    Number: globalThis.Number,
    String: globalThis.String,
    Array: globalThis.Array,
    Object: globalThis.Object,
    Math: globalThis.Math,
    alert: () => {},
    confirm: () => true
  };
  win.window = win;
  win.globalThis = win;
  vm.createContext(win);
  return { doc, win };
}

// ----------------------------------------------------------------------------
// 3. Tests: DOM Execution Proofs & XSS Neutralization
// ----------------------------------------------------------------------------

test('Negative Control: Unescaped HTML sinks MUST trigger script execution in DOM simulator', () => {
  const { doc, win } = createDOMEnvironment();
  const sink = doc.createElement('div');
  doc.body.appendChild(sink);

  // 1. Unescaped img onerror sink
  sink.innerHTML = '<img src=invalid onerror="window.__xss_unsafe_img = 101;">';
  assert.strictEqual(sink.querySelectorAll('img').length, 1, 'DOM must construct HTMLImageElement');
  assert.strictEqual(sink.querySelectorAll('img')[0].getAttribute('onerror'), 'window.__xss_unsafe_img = 101;');
  triggerDOMExecution(sink, win);
  assert.strictEqual(win.__xss_unsafe_img, 101, 'Unescaped img onerror handler must execute in window context');

  // 2. Unescaped script tag sink
  sink.innerHTML = '<script>window.__xss_unsafe_script = 202;</script>';
  assert.strictEqual(sink.querySelectorAll('script').length, 1, 'DOM must construct HTMLScriptElement');
  triggerDOMExecution(sink, win);
  assert.strictEqual(win.__xss_unsafe_script, 202, 'Unescaped script element must execute in window context');

  // 3. Unescaped SVG onload sink
  sink.innerHTML = '<svg onload="window.__xss_unsafe_svg = 303;"></svg>';
  assert.strictEqual(sink.querySelectorAll('svg').length, 1, 'DOM must construct SVGSVGElement');
  triggerDOMExecution(sink, win);
  assert.strictEqual(win.__xss_unsafe_svg, 303, 'Unescaped SVG onload handler must execute in window context');
});

test('Defense Proof: escapeHtml() entity-encoding neutralizes img, script, and svg vectors', () => {
  const { doc, win } = createDOMEnvironment();
  const sink = doc.createElement('div');
  doc.body.appendChild(sink);

  const vectors = [
    '<img src=x onerror="window.__xss_img = 1">',
    '<script>window.__xss_script = 2</script>',
    '<svg onload="window.__xss_svg = 3">',
    '"><script>window.__xss_breakout = 4</script>',
    '\';window.__xss_quote = 5;//'
  ];

  for (const payload of vectors) {
    sink.innerHTML = `<span>${escapeHtml(payload)}</span>`;

    // Must NOT create element nodes for the vectors
    assert.strictEqual(sink.querySelectorAll('img').length, 0, `No <img> tag allowed for ${payload}`);
    assert.strictEqual(sink.querySelectorAll('script').length, 0, `No <script> tag allowed for ${payload}`);
    assert.strictEqual(sink.querySelectorAll('svg').length, 0, `No <svg> tag allowed for ${payload}`);

    // Must preserve full literal string in text content
    assert.strictEqual(sink.textContent, payload, `Literal payload text must match for ${payload}`);

    // Trigger DOM execution pass
    triggerDOMExecution(sink, win);
  }

  assert.strictEqual(win.__xss_img, undefined, 'img vector must not execute');
  assert.strictEqual(win.__xss_script, undefined, 'script vector must not execute');
  assert.strictEqual(win.__xss_svg, undefined, 'svg vector must not execute');
  assert.strictEqual(win.__xss_breakout, undefined, 'breakout vector must not execute');
  assert.strictEqual(win.__xss_quote, undefined, 'quote vector must not execute');
});

test('Defense Proof: textContent assignment creates text node only and suppresses execution', () => {
  const { doc, win } = createDOMEnvironment();
  const el = doc.createElement('div');
  doc.body.appendChild(el);

  const payload = '<img src=x onerror="window.__xss_text = 1;"><script>window.__xss_text2 = 2;</script>';
  el.textContent = payload;

  assert.strictEqual(el.querySelectorAll('*').length, 0, 'textContent must not parse HTML elements');
  assert.strictEqual(el.childNodes.length, 1, 'Must have single text child node');
  assert.strictEqual(el.childNodes[0].nodeType, 3, 'Child node must be DOMTextNode');
  assert.strictEqual(el.textContent, payload, 'Preserves exact raw payload characters');

  triggerDOMExecution(el, win);
  assert.strictEqual(win.__xss_text, undefined);
  assert.strictEqual(win.__xss_text2, undefined);
});

test('RESEARCH_UI_HTML: Dashboard experiments table neutralizes stored XSS payloads', async () => {
  const { fullHtml, scriptSource } = loadResearchUI();

  // Payloads in experiment fields
  const maliciousExperiments = [
    {
      experiment_id: 'EXP-SAFE-01',
      name: '<img src=x onerror="window.__xss_name = 100;">',
      strategy_id: '<script>window.__xss_strat = 200;</script>',
      strategy_version: '1.0.0',
      dataset_id: '<svg onload="window.__xss_dataset = 300;">',
      status: 'RUNNING',
      fingerprint: 'a1b2c3d4e5f60000',
      created_at: '2024-01-01T00:00:00Z'
    },
    {
      experiment_id: '"><script>window.__xss_id = 400;</script>',
      name: '\';window.__xss_quote = 500;//',
      strategy_id: 'Canonical_SMA',
      strategy_version: '1.0.0',
      dataset_id: 'NSE_DAILY',
      status: 'COMPLETED',
      fingerprint: 'b2c3d4e5f6a10000',
      created_at: '2024-01-02T00:00:00Z'
    }
  ];

  const mockFetch = async (url) => {
    if (String(url).includes('/api/v1/experiments')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ experiments: maliciousExperiments })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const { doc, win } = createDOMEnvironment(mockFetch);

  // Parse RESEARCH_UI_HTML body into document
  const bodyContent = fullHtml.match(/<body>([\s\S]*?)<\/body>/)?.[1] || fullHtml;
  doc.body.innerHTML = bodyContent;

  // Execute UI script in VM context
  vm.runInContext(scriptSource, win);

  // Invoke loadDashboardExperiments
  await win.loadDashboardExperiments();

  const tbody = doc.getElementById('experiments-table-body');
  assert.ok(tbody, 'experiments-table-body element must exist');

  // Verify zero injected executable elements in the rendered table
  assert.strictEqual(tbody.querySelectorAll('img').length, 0, 'No <img> elements created in table body');
  assert.strictEqual(tbody.querySelectorAll('script').length, 0, 'No <script> elements created in table body');
  assert.strictEqual(tbody.querySelectorAll('svg').length, 0, 'No <svg> elements created in table body');

  // Verify compare and audit select options use textContent
  const baseSelect = doc.getElementById('compare-baseline-select');
  assert.ok(baseSelect, 'compare-baseline-select element must exist');
  assert.strictEqual(baseSelect.querySelectorAll('img').length, 0, 'No <img> elements in compare select options');
  assert.strictEqual(baseSelect.querySelectorAll('script').length, 0, 'No <script> elements in compare select options');

  // Trigger DOM execution pass across the entire document
  triggerDOMExecution(doc.body, win);

  assert.strictEqual(win.__xss_name, undefined, 'window.__xss_name must NOT execute');
  assert.strictEqual(win.__xss_strat, undefined, 'window.__xss_strat must NOT execute');
  assert.strictEqual(win.__xss_dataset, undefined, 'window.__xss_dataset must NOT execute');
  assert.strictEqual(win.__xss_id, undefined, 'window.__xss_id must NOT execute');
  assert.strictEqual(win.__xss_quote, undefined, 'window.__xss_quote must NOT execute');
});

test('RESEARCH_UI_HTML: Experiment detail view neutralizes script tags in name and description', async () => {
  const { fullHtml, scriptSource } = loadResearchUI();

  const maliciousExp = {
    experiment_id: 'EXP-DETAIL-XSS',
    name: '<img src=x onerror="window.__xss_detail_name = 1;">',
    description: '<script>window.__xss_detail_desc = 2;</script><svg onload="window.__xss_detail_svg = 3;">',
    strategy_id: 'Canonical_SMA',
    strategy_version: '1.0.0',
    dataset_id: 'NSE_NIFTY50_DAILY',
    dataset_checksum: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    initial_capital: 100000,
    status: 'COMPLETED',
    parameters: {
      'param_<script>alert(1)</script>': '<img src=x onerror="window.__xss_detail_param = 4;">'
    }
  };

  const mockFetch = async (url) => {
    if (String(url).includes('/api/v1/experiments/EXP-DETAIL-XSS')) {
      return { ok: true, status: 200, json: async () => maliciousExp };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const { doc, win } = createDOMEnvironment(mockFetch);
  const bodyContent = fullHtml.match(/<body>([\s\S]*?)<\/body>/)?.[1] || fullHtml;
  doc.body.innerHTML = bodyContent;

  vm.runInContext(scriptSource, win);

  await win.openExperimentDetail('EXP-DETAIL-XSS');

  const titleEl = doc.getElementById('detail-title');
  const descEl = doc.getElementById('detail-desc');
  const paramsEl = doc.getElementById('detail-params');

  assert.ok(titleEl && descEl && paramsEl, 'Detail elements must exist');

  // Verify textContent assignment prevents tag generation
  assert.strictEqual(titleEl.querySelectorAll('*').length, 0, 'detail-title must have no element children');
  assert.strictEqual(descEl.querySelectorAll('*').length, 0, 'detail-desc must have no element children');
  assert.strictEqual(paramsEl.querySelectorAll('*').length, 0, 'detail-params must have no element children');

  triggerDOMExecution(doc.body, win);

  assert.strictEqual(win.__xss_detail_name, undefined, 'Detail name XSS must not execute');
  assert.strictEqual(win.__xss_detail_desc, undefined, 'Detail description XSS must not execute');
  assert.strictEqual(win.__xss_detail_svg, undefined, 'Detail SVG XSS must not execute');
  assert.strictEqual(win.__xss_detail_param, undefined, 'Detail parameters XSS must not execute');
});

test('RESEARCH_UI_HTML: Validation error renderer neutralizes markup payloads', async () => {
  const { fullHtml, scriptSource } = loadResearchUI();

  const valErrorData = {
    is_valid: false,
    errors: [
      '<img src=x onerror="window.__xss_val1 = 1;">',
      '<script>window.__xss_val2 = 2;</script>',
      '<svg onload="window.__xss_val3 = 3;">'
    ]
  };

  const mockFetch = async (url) => {
    if (String(url).includes('/api/v1/experiments/validate')) {
      return { ok: false, status: 422, json: async () => valErrorData };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const { doc, win } = createDOMEnvironment(mockFetch);
  const bodyContent = fullHtml.match(/<body>([\s\S]*?)<\/body>/)?.[1] || fullHtml;
  doc.body.innerHTML = bodyContent;

  vm.runInContext(scriptSource, win);

  // Setup form inputs for collectFormData()
  doc.getElementById('cfg-params').value = '{}';
  doc.getElementById('cfg-name').value = 'Test';
  doc.getElementById('cfg-desc').value = 'Desc';
  doc.getElementById('cfg-strategy').value = 'SMA';
  doc.getElementById('cfg-strategy-ver').value = '1.0';
  doc.getElementById('cfg-dataset').value = 'DS';
  doc.getElementById('cfg-dataset-ver').value = '1.0';
  doc.getElementById('cfg-checksum').value = 'abc';
  doc.getElementById('cfg-universe').value = 'RELIANCE';
  doc.getElementById('cfg-timeframe').value = '1d';
  doc.getElementById('cfg-start').value = '2024-01-01';
  doc.getElementById('cfg-end').value = '2024-06-01';
  doc.getElementById('cfg-capital').value = '100000';
  doc.getElementById('cfg-seed').value = '42';

  await win.handleValidateDryRun();

  const previewContent = doc.getElementById('preview-content');
  assert.ok(previewContent, 'preview-content element must exist');

  // Verify list items were rendered via textContent
  assert.strictEqual(previewContent.querySelectorAll('img').length, 0, 'No <img> elements in validation errors');
  assert.strictEqual(previewContent.querySelectorAll('script').length, 0, 'No <script> elements in validation errors');
  assert.strictEqual(previewContent.querySelectorAll('svg').length, 0, 'No <svg> elements in validation errors');

  triggerDOMExecution(previewContent, win);

  assert.strictEqual(win.__xss_val1, undefined, 'Validation error vector 1 must not execute');
  assert.strictEqual(win.__xss_val2, undefined, 'Validation error vector 2 must not execute');
  assert.strictEqual(win.__xss_val3, undefined, 'Validation error vector 3 must not execute');
});

test('RESEARCH_UI_HTML: Audit trail and log monitor render literal JSON without innerHTML sinks', async () => {
  const { fullHtml, scriptSource } = loadResearchUI();

  const auditEvents = [
    {
      timestamp: '2024-01-01T10:00:00Z',
      event_type: 'RISK_REJECTED',
      payload: {
        note: '<script>window.__xss_audit1 = 1;</script>',
        image_vector: '<img src=x onerror="window.__xss_audit2 = 2;">',
        svg_vector: '<svg onload="window.__xss_audit3 = 3;">'
      }
    }
  ];

  const provenanceData = {
    experiment_id: 'EXP-AUDIT-01',
    fingerprint: 'fp_1234567890',
    dataset_id: 'DS_NSE',
    dataset_version: '1.0',
    dataset_checksum: 'checksum_123',
    strategy_id: 'Canonical_SMA',
    strategy_version: '1.0',
    code_revision: 'main',
    parameters: { '<img onerror=alert(1)>': 'value' }
  };

  const mockFetch = async (url) => {
    const urlStr = String(url);
    if (urlStr.includes('/provenance')) {
      return { ok: true, status: 200, json: async () => provenanceData };
    }
    if (urlStr.includes('/audit')) {
      return { ok: true, status: 200, json: async () => auditEvents };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const { doc, win } = createDOMEnvironment(mockFetch);
  const bodyContent = fullHtml.match(/<body>([\s\S]*?)<\/body>/)?.[1] || fullHtml;
  doc.body.innerHTML = bodyContent;

  vm.runInContext(scriptSource, win);

  await win.loadAuditTrail('EXP-AUDIT-01');

  const auditTbody = doc.getElementById('audit-events-tbody');
  assert.ok(auditTbody, 'audit-events-tbody must exist');

  // Verify payload code element used textContent
  assert.strictEqual(auditTbody.querySelectorAll('img').length, 0, 'No <img> in audit events table');
  assert.strictEqual(auditTbody.querySelectorAll('script').length, 0, 'No <script> in audit events table');
  assert.strictEqual(auditTbody.querySelectorAll('svg').length, 0, 'No <svg> in audit events table');

  triggerDOMExecution(doc.body, win);

  assert.strictEqual(win.__xss_audit1, undefined, 'Audit script vector must not execute');
  assert.strictEqual(win.__xss_audit2, undefined, 'Audit img vector must not execute');
  assert.strictEqual(win.__xss_audit3, undefined, 'Audit svg vector must not execute');
});

test('RESEARCH_UI_HTML: Paper sessions and broker connections render safely with escapeHtml', async () => {
  const { fullHtml, scriptSource } = loadResearchUI();

  const mockSessions = [
    {
      session_id: 'sess-<img src=x onerror="window.__xss_sess = 1;">',
      name: '<script>window.__xss_sess_name = 2;</script>',
      strategy_id: '<svg onload="window.__xss_sess_strat = 3;">',
      universe: ['<img src=x onerror="window.__xss_univ = 4;">'],
      status: 'RUNNING',
      initial_capital: 100000,
      portfolio: { cash: 100000, positions: {} }
    }
  ];

  const mockConnections = [
    {
      connection_id: 'conn-01',
      broker_name: '<img src=x onerror="window.__xss_broker = 5;">',
      environment: 'PAPER',
      api_key_masked: '***',
      api_secret_configured: true
    }
  ];

  const mockFetch = async (url) => {
    const urlStr = String(url);
    if (urlStr.includes('/paper-trading/sessions')) {
      return { ok: true, status: 200, json: async () => mockSessions };
    }
    if (urlStr.includes('/brokers/connections')) {
      return { ok: true, status: 200, json: async () => mockConnections };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const { doc, win } = createDOMEnvironment(mockFetch);
  const bodyContent = fullHtml.match(/<body>([\s\S]*?)<\/body>/)?.[1] || fullHtml;
  doc.body.innerHTML = bodyContent;

  vm.runInContext(scriptSource, win);

  await win.loadPaperSessions();
  await win.loadBrokerConnections();

  const paperTbody = doc.getElementById('paper-sessions-tbody');
  const brokerTbody = doc.getElementById('broker-connections-tbody');

  assert.strictEqual(paperTbody.querySelectorAll('img').length, 0, 'No <img> in paper sessions');
  assert.strictEqual(paperTbody.querySelectorAll('script').length, 0, 'No <script> in paper sessions');
  assert.strictEqual(paperTbody.querySelectorAll('svg').length, 0, 'No <svg> in paper sessions');

  assert.strictEqual(brokerTbody.querySelectorAll('img').length, 0, 'No <img> in broker connections');

  triggerDOMExecution(doc.body, win);

  assert.strictEqual(win.__xss_sess, undefined);
  assert.strictEqual(win.__xss_sess_name, undefined);
  assert.strictEqual(win.__xss_sess_strat, undefined);
  assert.strictEqual(win.__xss_univ, undefined);
  assert.strictEqual(win.__xss_broker, undefined);
});
