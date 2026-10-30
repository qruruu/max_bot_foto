const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

function harness() {
  const handlers = new Map();
  class FakeImage {
    naturalWidth = 960; naturalHeight = 720;
    set src(value) {queueMicrotask(() => this.onload());}
  }
  class FakeFileReader {
    readAsDataURL(blob) {
      blob.arrayBuffer().then(bytes => {
        this.result = 'data:image/jpeg;base64,' + Buffer.from(bytes).toString('base64');
        this.onload();
      });
    }
  }
  const document = {
    addEventListener(name, callback) {handlers.set(name, callback);},
    createElement(tag) {
      assert.equal(tag, 'canvas');
      return {getContext: () => ({fillRect() {}, drawImage() {}}),
        toBlob(callback) {callback(new Blob(['normalized-photo'], {type: 'image/jpeg'}));}};
    },
  };
  const window = {addEventListener() {}};
  runInNewContext(readFileSync(join(__dirname, '../../web/signal_browser.js'), 'utf8'), {
    window, document, Image: FakeImage, FileReader: FakeFileReader, Blob,
    URL: {createObjectURL: () => 'blob:local-test', revokeObjectURL() {}},
    crypto: {randomUUID: () => 'photo-id'}, setTimeout, clearTimeout, URLSearchParams,
  });
  const event = (files, x = 30, y = 50) => ({
    clientX: x, clientY: y, prevented: false, stopped: false,
    dataTransfer: {files, types: ['Files']},
    preventDefault() {this.prevented = true;}, stopPropagation() {this.stopped = true;},
  });
  const file = Object.assign(new Blob(['source-photo'], {type: 'image/jpeg'}), {name: 'test.jpg'});
  return {adapter: window.signalBrowser, handlers, event, file};
}

test('photo drop only handles files in the visible target and delivers normalized photos', async () => {
  const h = harness();
  let started = 0, received, error;
  h.adapter.registerDropTarget(() => JSON.stringify({left: 10, top: 20, right: 100, bottom: 150, remaining: 3}),
    () => started++, value => {received = JSON.parse(value);}, value => {error = value;});
  const outside = h.event([h.file], 200, 50);
  await h.handlers.get('drop')(outside);
  assert.equal(outside.prevented, false);
  assert.equal(started, 0);
  const over = h.event([h.file]);
  h.handlers.get('dragover')(over);
  assert.equal(over.prevented, true);
  assert.equal(over.dataTransfer.dropEffect, 'copy');
  const dropped = h.event([h.file]);
  await h.handlers.get('drop')(dropped);
  assert.equal(dropped.prevented, true);
  assert.equal(dropped.stopped, true);
  assert.equal(started, 1);
  assert.equal(error, undefined);
  assert.equal(received.length, 1);
  assert.equal(received[0].mime, 'image/jpeg');
  assert.equal(Buffer.from(received[0].data, 'base64').toString(), 'normalized-photo');
});

test('photo drop respects remaining slots and unregisters when the form is closed', async () => {
  const h = harness();
  let started = 0, received = 0, error;
  const id = h.adapter.registerDropTarget(() => JSON.stringify({left: 10, top: 20, right: 100, bottom: 150, remaining: 1}),
    () => started++, () => received++, value => {error = value;});
  await h.handlers.get('drop')(h.event([h.file, h.file]));
  assert.equal(started, 1);
  assert.equal(received, 0);
  assert.match(error, /трёх фотографий/);
  h.adapter.unregisterDropTarget(id);
  const dropped = h.event([h.file]);
  await h.handlers.get('drop')(dropped);
  assert.equal(dropped.prevented, false);
  assert.equal(started, 1);
});
