const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

const source = readFileSync(join(__dirname, '../../web/signal_browser.js'), 'utf8');
const config = JSON.stringify({apiKey: 'test', organizations: []});
const noop = () => {};
const flush = async () => {for (let i = 0; i < 12; i++) await Promise.resolve();};

// Exercise the real browser adapter with deterministic DOM/SDK lifecycle events.
// No browser, network request or external map service is used by these tests.
function harness({connected = false, width = 0, height = 0, sdkReady = true} = {}) {
  const observers = new Set(), frames = new Map(), layers = [];
  let nextFrame = 0, script;
  const element = {
    isConnected: connected, width, height,
    getBoundingClientRect() {return {width: this.width, height: this.height};},
  };
  const api = {
    ready: callback => callback(),
    Map: class {
      constructor(container) {
        assert.equal(container.isConnected, true);
        assert.ok(container.width > 0 && container.height > 0);
        this.fits = 0; this.destroyed = false;
        this.container = {fitToViewport: () => this.fits++};
        this.events = {add: noop};
        this.geoObjects = {getBounds: () => null};
        layers.push(this);
      }
      destroy() {this.destroyed = true;}
    },
  };
  const window = {addEventListener: noop, ymaps: api};
  const document = {
    addEventListener: noop,
    createElement: () => ({remove: noop}),
    head: {append(value) {script = value; if (sdkReady) value.onload();}},
  };
  const ResizeObserver = class {
    constructor(callback) {this.callback = callback;}
    observe(target) {assert.equal(target, element); observers.add(this);}
    disconnect() {observers.delete(this);}
  };
  runInNewContext(source, {
    window, document, ResizeObserver, AbortController, DOMException,
    setTimeout, clearTimeout, URLSearchParams,
    requestAnimationFrame(callback) {const id = ++nextFrame; frames.set(id, callback); return id;},
    cancelAnimationFrame(id) {frames.delete(id);},
  });
  const tick = async () => {
    await flush();
    const callbacks = [...frames.values()]; frames.clear();
    for (const callback of callbacks) callback();
    await flush();
  };
  return {
    adapter: window.signalBrowser, element, layers, observers,
    tick,
    async resize() {for (const observer of [...observers]) observer.callback(); await tick();},
    releaseSdk() {script.onload();},
  };
}

test('map waits for Flutter to attach and size its container', async () => {
  const h = harness();
  let outcome = 'pending';
  const result = h.adapter.createMap(h.element, config, noop, noop);
  result.then(() => {outcome = 'ready';}, () => {outcome = 'failed';});
  await h.tick();
  assert.equal(outcome, 'pending');
  h.element.isConnected = true;
  await h.resize();
  assert.equal(outcome, 'pending', 'an attached zero-size container is not ready');
  Object.assign(h.element, {width: 358, height: 240});
  await h.resize();
  const id = await result;
  assert.equal(outcome, 'ready');
  assert.equal(h.layers.length, 1);
  h.adapter.destroyMap(id);
  assert.equal(h.observers.size, 0);
});

test('scrolling out and back resizes the same map without losing its state', async () => {
  const h = harness({connected: true, width: 358, height: 240});
  const result = h.adapter.createMap(h.element, config, noop, noop);
  await h.tick();
  const id = await result;
  for (let i = 0; i < 10; i++) {
    Object.assign(h.element, {isConnected: false, width: 0, height: 0});
    await h.resize();
    assert.equal(h.layers[0].fits, i);
    Object.assign(h.element, {isConnected: true, width: 358, height: 240});
    await h.resize();
    assert.equal(h.layers[0].fits, i + 1);
  }
  assert.equal(h.layers.length, 1);
  h.adapter.destroyMap(id);
  assert.equal(h.layers[0].destroyed, true);
  assert.equal(h.observers.size, 0);
  await h.resize();
  assert.equal(h.layers[0].fits, 10);
});

test('closing a map cancels the pending attachment without leaving observers', async () => {
  const h = harness();
  const result = h.adapter.createMap(h.element, config, noop, noop);
  const cancelled = assert.rejects(result, {name: 'AbortError'});
  await h.tick();
  h.adapter.cancelMap(h.element);
  await cancelled;
  assert.equal(h.observers.size, 0);
  assert.equal(h.layers.length, 0);
});

test('late SDK completion cannot create a map that has already been closed', async () => {
  const h = harness({connected: true, width: 358, height: 240, sdkReady: false});
  const result = h.adapter.createMap(h.element, config, noop, noop);
  const cancelled = assert.rejects(result, {name: 'AbortError'});
  h.adapter.cancelMap(h.element);
  h.releaseSdk();
  await h.tick();
  await cancelled;
  assert.equal(h.layers.length, 0);
  assert.equal(h.observers.size, 0);
});
