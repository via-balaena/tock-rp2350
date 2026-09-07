// Drive the published course the way drive.js drives the work map.
//
// The chapters' own gate runs their figures under a shim; it knows nothing
// about the chrome added at publish time, which is where the rail, the search
// and the key bindings live. Nothing else looks at those at all.
//
//     node drive-read.js read/index.html read/ch*/index.html
//
// Exits 0 clean, 1 on a failure, 2 when jsdom is not installed.

let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch (err) { console.log('jsdom is not installed'); process.exit(2); }

const fs = require('fs'), path = require('path');
const files = process.argv.slice(2);
const passed = [], failed = [];
const check = (name, ok, detail) =>
  (ok ? passed : failed).push(name + (detail ? ' — ' + detail : ''));

(async () => {
  for (const file of files) {
    const where = path.basename(path.dirname(file));
    const errors = [];
    const dom = new JSDOM(fs.readFileSync(file, 'utf8'),
      { runScripts: 'dangerously', pretendToBeVisual: true, url: 'https://x/' + file });
    dom.virtualConsole.on('jsdomError', e => errors.push(e.message.split('\n')[0]));
    const { window } = dom, doc = window.document;
    window.Element.prototype.scrollIntoView = function () {};
    await new Promise(r => setTimeout(r, 120));

    check(where + ': runs without throwing', errors.length === 0, errors[0]);
    check(where + ': is in standards mode', doc.compatMode === 'CSS1Compat');
    check(where + ': carries one rail', doc.querySelectorAll('.dc-rail').length === 1);
    check(where + ': the rail lists every chapter',
          doc.querySelectorAll('.dc-ch').length === 9,
          doc.querySelectorAll('.dc-ch').length + ' listed');

    const secs = [...doc.querySelectorAll('.dc-sec')];
    check(where + ': every section link resolves',
          secs.every(a => doc.getElementById(a.getAttribute('href').slice(1))),
          secs.length + ' sections');

    const isChapter = where.startsWith('ch');
    check(where + ': marks the chapter you are in',
          doc.querySelectorAll('.dc-ch.dc-here').length === (isChapter ? 1 : 0));
    if (isChapter) {
      check(where + ': has sections to navigate', secs.length > 5, secs.length + '');
    }

    // search
    const sheet = doc.getElementById('dc-search');
    const keys = doc.getElementById('dc-keysheet');
    const press = k => doc.dispatchEvent(new window.KeyboardEvent('keydown', { key: k, bubbles: true }));
    check(where + ': search starts closed', sheet.hidden);
    press('/');
    check(where + ': slash opens search', !sheet.hidden);
    const q = doc.getElementById('dc-q');
    q.value = 'memory';
    q.dispatchEvent(new window.Event('input', { bubbles: true }));
    const hits = [...doc.querySelectorAll('#dc-hits li')];
    check(where + ': search returns results', hits.length > 0, hits.length + ' hits');
    const from = new Set([...doc.querySelectorAll('#dc-hits .dc-where')].map(e => e.textContent));
    check(where + ': search reaches more than the page you are on',
          from.size > 1, [...from].slice(0, 3).join(' / '));
    q.value = 'grant';
    q.dispatchEvent(new window.Event('input', { bubbles: true }));
    const defs = [...doc.querySelectorAll('#dc-hits .dc-def')];
    check(where + ': search answers with definitions, not just links',
          defs.length > 0 && defs[0].textContent.length > 15,
          defs.length ? defs[0].textContent.slice(0, 40) : 'none');
    press('Escape');
    check(where + ': escape closes search', sheet.hidden);

    // every term this page defines is anchored, so search can reach it
    const terms = [...doc.querySelectorAll('dt[id]')];
    check(where + ': defined terms carry anchors',
          terms.every(t => doc.getElementById(t.id)),
          terms.length + ' terms');
    press('?');
    check(where + ': question mark opens the keys', !keys.hidden);
    press('Escape');
    check(where + ': escape closes the keys', keys.hidden);

    dom.window.close();
  }

  if (failed.length) {
    failed.forEach(f => console.log('  FAIL ' + f));
    process.exit(1);
  }
  console.log(passed.length + ' interactions verified across ' + files.length + ' pages.');
})();
