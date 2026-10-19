const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {MediaEventDecoder} = require('../static/media_stream');
const payload = 'data: {"status":"Εικόνα 🎬"}\n\ndata: {"done":true}\n\n';
const bytes = new TextEncoder().encode(payload);
for (let split = 1; split < bytes.length; split++) {
    const decoder = new MediaEventDecoder();
    const frames = [...decoder.decode(bytes.slice(0, split)), ...decoder.decode(bytes.slice(split))];
    assert.equal(frames.length, 2);
    assert.equal(JSON.parse(frames[0].slice(6)).status, 'Εικόνα 🎬');
    assert.equal(JSON.parse(frames[1].slice(6)).done, true);
}
const html = fs.readFileSync('templates/index.html', 'utf8');
new vm.Script(fs.readFileSync('static/reference_prep.js', 'utf8'));
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
    if (match[1].trim()) new vm.Script(match[1]);
}
console.log('SSE split-boundary/UTF-8 checks and inline JavaScript syntax passed.');
