'use strict';
// Exercise the actual form handlers with textarea line-ending normalization.
// Browser upload/render verification remains a separate check.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const inputHandlers = app.slice(app.indexOf('let editingSource = null;'), app.indexOf("$('extract-evidence').addEventListener"));
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    let value = '';
    elements.set(id, {
      handlers: {}, files: [], textContent: '',
      get value() { return value; },
      set value(next) { value = id === 'source-content-input' ? next.replace(/\r\n?/g, '\n') : next; },
      addEventListener(event, handler) { this.handlers[event] = handler; },
      focus() {},
      reset() { for (const field of ['source-label', 'source-content-input', 'source-file']) element(field).value = ''; },
    });
  }
  return elements.get(id);
}
let pending, saved;
const context = vm.createContext({
  $: element, TextDecoder, RFQ: 'RFQ-SYN-001', state: {principal: {role: 'buyer'}},
  run(task) { pending = task(); return pending; }, notice() {},
  async loadHistory() {}, async openEvidence() {},
  async api(_path, body) { saved = body; return {offer: {id: 'INPUT-TEST'}}; },
});
vm.runInContext(inputHandlers, context);
async function trigger(id, event) {
  element(id).handlers[event]({preventDefault() {}});
  await pending;
}
async function upload(bytes) {
  element('source-file').files = [{name: 'quote.txt', size: bytes.length, async arrayBuffer() {return bytes;}}];
  await trigger('source-file', 'change');
}
async function main() {
  const raw = 'RFQ item: AX-DEMO-BRACKET-01\r\nSupplier: NEW-TEST\r\nLead time condition: 검토 메모 🧾\r\n';
  await upload(Buffer.from(raw, 'utf8'));
  assert.equal(element('source-content-input').value, raw.replace(/\r\n/g, '\n'));
  element('source-label').value = 'Changed display label';
  await trigger('source-form', 'submit');
  assert.equal(saved.content, raw, 'unchanged file preserves CRLF despite textarea normalization and label edits');

  await upload(Buffer.from(raw, 'utf8'));
  element('source-content-input').value += 'Currency: KRW\n';
  await trigger('source-content-input', 'input');
  assert.match(element('source-identity-note').textContent, /원본 파일의 지문이 아닙니다/);
  const edited = element('source-content-input').value;
  await trigger('source-form', 'submit');
  assert.equal(saved.content, edited, 'a real input edit submits the edited textarea');

  await upload(Buffer.from(raw, 'utf8'));
  await trigger('source-example', 'click');
  const sample = element('source-content-input').value;
  await trigger('source-form', 'submit');
  assert.equal(saved.content, sample, 'sample discards uploaded buffer');

  await upload(Buffer.from(raw, 'utf8'));
  await trigger('source-reset', 'click');
  element('source-content-input').value = 'fresh pasted text';
  await trigger('source-form', 'submit');
  assert.equal(saved.content, 'fresh pasted text', 'reset discards uploaded buffer');

  context.offer = {id: 'INPUT-TEST', source_hash: 'hash', document_revision: 2, content: raw, supplier_label: 'test', supplier_id: 'NEW-TEST'};
  vm.runInContext('editSource(offer)', context);
  await trigger('source-form', 'submit');
  assert.equal(saved.content, raw, 'unmodified saved-source revision preserves CRLF');
  assert.equal(saved.expected_document_revision, 2);

  await upload(Buffer.from(raw, 'utf8'));
  await assert.rejects(upload(Buffer.from([0xc3, 0x28])), /UTF-8/);
  assert.equal(element('source-content-input').value, '', 'invalid UTF-8 clears stale visible source');
  element('source-content-input').value = 'replacement after invalid file';
  await trigger('source-form', 'submit');
  assert.equal(saved.content, 'replacement after invalid file', 'invalid upload retains no older raw buffer');
  console.log('PASS: CRLF/label preservation, edit, sample, reset, revision, invalid UTF-8 (6 source-buffer scenarios)');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
