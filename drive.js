// Drive the built page in a real DOM and assert that its interactions work.
//
// This exists because nothing else here can look at the page. Every other
// check reads the HTML as text; this one runs the script the way a browser
// would, clicks things, and asserts what changed. It has already earned its
// keep: the scrollspy threw on a browser without IntersectionObserver, and
// because the page ships one script, that single throw silently took the
// search, the key bindings and the whole palette down with it. Nothing that
// reads the markup could have seen that.
//
//     npm install jsdom          # once, anywhere node can resolve it from
//     node drive.js index.html
//
// Exits 0 when every interaction holds, 1 when one does not, 2 when jsdom is
// not installed -- which check.py reports as skipped rather than as a failure.

let JSDOM;
try {
  ({ JSDOM } = require('jsdom'));
} catch (err) {
  console.log('jsdom is not installed; run `npm install jsdom` to drive the page');
  process.exit(2);
}

const fs = require('fs');
const file = process.argv[2] || 'index.html';
const errors = [];
const dom = new JSDOM(fs.readFileSync(file, 'utf8'), {
  runScripts: 'dangerously',
  pretendToBeVisual: true,
});
dom.virtualConsole.on('jsdomError', e => errors.push('threw: ' + e.message));

const { window } = dom;
const doc = window.document;
// jsdom has no layout, so it has no scrollIntoView. Stubbed here rather than
// guarded in the page: the page should not carry compatibility code for a
// method every browser it targets has had for a decade.
window.Element.prototype.scrollIntoView = function () {};

const passed = [], failed = [];
const check = (name, ok, detail) =>
  (ok ? passed : failed).push(name + (detail ? ' — ' + detail : ''));
const click = el => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
const press = key => doc.dispatchEvent(new window.KeyboardEvent('keydown', { key, bubbles: true }));
const showing = () => [...doc.querySelectorAll('.trace')].filter(t => !t.hidden);

setTimeout(() => {
  check('the script runs without throwing', errors.length === 0, errors.join('; '));

  const rows = [...doc.querySelectorAll('.brow[data-block]')];
  check('the coverage grid has rows', rows.length > 0, rows.length + ' rows');
  if (!rows.length) return report();

  check('exactly one trace shows at rest', showing().length === 1,
        showing().length + ' showing');
  const selected = rows.find(r => r.classList.contains('sel'));
  check('the trace showing is the row marked selected',
        selected && showing()[0] && showing()[0].id === 'tr-' + selected.dataset.block);

  // Every row must open its own trace, and only its own.
  let wrong = 0, lighting = 0;
  for (const row of rows) {
    click(row);
    const open = showing();
    if (open.length !== 1 || open[0].id !== 'tr-' + row.dataset.block) wrong++;
    if (doc.querySelectorAll('[data-branch].rel').length) lighting++;
  }
  check('every block opens its own trace and no other', wrong === 0, wrong + ' wrong');
  check('selecting a block lights the branches doing that work',
        lighting >= 3, lighting + ' of ' + rows.length + ' light a branch');

  const before = doc.querySelector('.brow.sel').dataset.block;
  press('j');
  check('j moves to the next block', doc.querySelector('.brow.sel').dataset.block !== before);
  press('k');
  check('k moves back', doc.querySelector('.brow.sel').dataset.block === before);

  const palette = doc.getElementById('palette');
  check('the palette starts closed', palette.hidden);
  press('/');
  check('slash opens the palette', !palette.hidden);
  const q = doc.getElementById('q');
  q.value = 'uart';
  q.dispatchEvent(new window.Event('input', { bubbles: true }));
  const kinds = new Set([...doc.querySelectorAll('#presults .kind')].map(k => k.textContent));
  check('searching returns results', doc.querySelectorAll('#presults li').length > 0);
  check('search reaches more than one kind of thing', kinds.size > 1,
        [...kinds].join(', '));
  press('Escape');
  check('escape closes the palette', palette.hidden);

  const keys = doc.getElementById('keysheet');
  press('?');
  check('question mark opens the key sheet', !keys.hidden);
  press('Escape');
  check('escape closes the key sheet', keys.hidden);

  const chip = doc.querySelector('.chip[data-pr]');
  if (chip) {
    click(chip);
    check('a pull request chip filters the graph',
          doc.getElementById('graph').classList.contains('filtered'));
    check('the filter lights at least one commit',
          doc.querySelectorAll('#graph .node.on').length > 0);
    press('Escape');
    check('escape clears the filter',
          !doc.getElementById('graph').classList.contains('filtered'));
  }

  const tabs = [...doc.querySelectorAll('.ptab[data-board]')];
  const maps = () => [...doc.querySelectorAll('.pinmap')].filter(m => !m.hidden);
  if (tabs.length) {
    check('one pin map shows at rest', maps().length === 1, maps().length + ' showing');
    check('the map showing is the tab marked selected',
          maps()[0] && maps()[0].id === 'pm-' + tabs.find(t => t.classList.contains('sel')).dataset.board);
    for (const tab of tabs) {
      click(tab);
      const open = maps();
      check('the ' + tab.dataset.board + ' tab shows only its own map',
            open.length === 1 && open[0].id === 'pm-' + tab.dataset.board,
            open.map(m => m.id).join(','));
      check('the ' + tab.dataset.board + ' tab reports itself pressed',
            tab.getAttribute('aria-pressed') === 'true' &&
            tabs.filter(t => t.getAttribute('aria-pressed') === 'true').length === 1);
    }
  }

  const node = doc.querySelector('#graph .node');
  if (node) {
    click(node);
    check('clicking a commit fills the readout',
          doc.getElementById('d-title').textContent !== 'Nothing selected',
          doc.getElementById('d-title').textContent);
  }
  report();
}, 50);

function report() {
  if (failed.length) {
    failed.forEach(f => console.log('  FAIL ' + f));
    process.exit(1);
  }
  console.log(passed.length + ' interactions verified in a DOM.');
}
