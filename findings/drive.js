// Drive the findings pages in a real DOM and assert what a reader gets.
//
// These pages are linked from GitHub issues, so they are read by people who
// have never seen this site and will not report a broken one -- they will just
// close the tab. That makes the usual excuse for not checking ("I looked at
// it once") worth less here than anywhere else on the repository.
//
//     node findings/drive.js
//
// Exits 0 when everything holds, 1 when it does not, 2 when jsdom is missing,
// which check.py reports as skipped rather than as a failure.

let JSDOM;
try {
  ({ JSDOM } = require('jsdom'));
} catch (err) {
  console.log('jsdom is not installed; run `npm install jsdom` to drive the pages');
  process.exit(2);
}

const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const UPPERCASING = uppercasingSelectors(
  fs.readFileSync(path.join(__dirname, 'style.css'), 'utf8'));
// The landing page is driven too. It has no figures and no buttons, so most
// of what follows is vacuous for it -- but the skeleton, the links and the
// private-path scan are not, and that page is the one a trimmed URL lands on.
const PAGES = ['.'].concat(
  fs.readdirSync(HERE)
    .filter(name => fs.existsSync(path.join(HERE, name, 'index.html')))
    .sort());

const passed = [], failed = [];
const check = (name, ok, detail) =>
  (ok ? passed : failed).push(name + (detail ? ' — ' + detail : ''));

// ---------------------------------------------------------------- selectors
// Every class the stylesheet styles, and every class the markup uses. A class
// in one and not the other is either a rule that does nothing or an element
// that was meant to look like something and does not. Both have shipped on
// this site before, which is why the work map checks the same thing.
function classesInCss(css) {
  const found = new Set();
  css.replace(/\/\*[\s\S]*?\*\//g, '')
     .replace(/([^{}]+)\{/g, (all, prelude) => {
       if (prelude.trim().startsWith('@')) return all;
       prelude.replace(/\.(-?[_a-zA-Z][_a-zA-Z0-9-]*)/g,
                       (m, name) => { found.add(name); return m; });
       return all;
     });
  return found;
}

// Selectors whose rules uppercase their content, read from the stylesheet
// rather than listed here, so a new one is covered the day it is written.
// These are kept as whole selectors on purpose: an earlier version pulled the
// class names out of them, so `.readout dt` was checked as `.readout` and
// every hex value in a readout body came back a false positive.
function uppercasingSelectors(css) {
  const found = new Set();
  css.replace(/\/\*[\s\S]*?\*\//g, '')
     .replace(/([^{}]+)\{([^{}]*)\}/g, (all, prelude, body) => {
       if (/text-transform\s*:\s*uppercase/.test(body)) {
         prelude.split(',').forEach(sel => {
           sel = sel.trim();
           if (sel && !sel.startsWith('@')) found.add(sel);
         });
       }
       return all;
     });
  return found;
}

function classesInMarkup(doc) {
  const found = new Set();
  doc.querySelectorAll('[class]').forEach(el =>
    el.classList.forEach(name => found.add(name)));
  return found;
}

// ------------------------------------------------------------------- drive
function drivePage(name) {
  const file = path.join(HERE, name, 'index.html');
  const html = fs.readFileSync(file, 'utf8');
  const errors = [];
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true });
  dom.virtualConsole.on('jsdomError', e => errors.push('threw: ' + e.message));
  const { window } = dom;
  const doc = window.document;
  const click = el => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  const at = what => (name === '.' ? 'index' : name) + ': ' + what;

  check(at('the script runs without throwing'), errors.length === 0, errors.join('; '));

  // The skeleton a browser needs. These pages are standalone, unlike the
  // chapters under learning/, so a missing charset here is nobody else's job.
  check(at('declares a doctype'), /^<!doctype html>/i.test(html.trim()));
  check(at('declares a charset'), !!doc.querySelector('meta[charset]'));
  check(at('declares a viewport'), !!doc.querySelector('meta[name=viewport]'));
  check(at('has a title'), !!(doc.title && doc.title.length > 12), doc.title);
  check(at('has a description'), !!doc.querySelector('meta[name=description]'));
  check(at('has exactly one h1'), doc.querySelectorAll('h1').length === 1);

  // Buttons must say what they control, and the thing must exist.
  const buttons = [...doc.querySelectorAll('button[aria-controls]')];
  check(at('every button has aria-pressed'),
        buttons.every(b => b.hasAttribute('aria-pressed')));
  const dangling = buttons.filter(b => !doc.getElementById(b.getAttribute('aria-controls')));
  check(at('every aria-controls names something'), dangling.length === 0,
        dangling.map(b => b.id).join(','));

  // One panel showing at rest in each group, which is also the whole of what
  // a reader with no JavaScript is given.
  // Group by the element the buttons sit in rather than by their names. An
  // earlier version keyed on the id with trailing digits stripped, which put
  // `b-before` and `b-after` in two groups of one and then reported both as
  // broken -- the markup was right and the check was wrong.
  const groups = new Map();
  buttons.forEach(b => {
    const box = b.closest('[role=group]') || b.parentElement;
    if (!groups.has(box)) groups.set(box, []);
    groups.get(box).push(b);
  });
  groups.forEach((members, box) => {
    const key = box.getAttribute('aria-label') || box.className;
    const pressed = members.filter(b => b.getAttribute('aria-pressed') === 'true');
    check(at('group ' + key + ' has one button pressed at rest'),
          pressed.length === 1, pressed.length + ' pressed');
    const panels = members.map(b => doc.getElementById(b.getAttribute('aria-controls')));
    const shown = panels.filter(p => p && !p.hidden);
    check(at('group ' + key + ' shows one panel at rest'),
          shown.length === 1, shown.length + ' showing');
  });

  // Then click every button and assert it selects itself and nothing else.
  groups.forEach((members) => {
    members.forEach(target => {
      click(target);
      const pressed = members.filter(b => b.getAttribute('aria-pressed') === 'true');
      const ok = pressed.length === 1 && pressed[0] === target;
      check(at('clicking ' + target.id + ' presses only itself'), ok,
            pressed.map(b => b.id).join(','));
      const shown = members
        .map(b => doc.getElementById(b.getAttribute('aria-controls')))
        .filter(p => p && !p.hidden);
      check(at('clicking ' + target.id + ' shows only its panel'),
            shown.length === 1 && shown[0].id === target.getAttribute('aria-controls'),
            shown.map(p => p.id).join(','));
    });
  });

  // Figures carry their number in the caption and an id to link to.
  const figures = [...doc.querySelectorAll('figure')];
  check(at('every figure has an id'), figures.every(f => f.id),
        figures.filter(f => !f.id).length + ' without');
  check(at('every figure has a caption'),
        figures.every(f => f.querySelector('figcaption')));
  figures.forEach((f, i) => {
    const cap = f.querySelector('figcaption');
    const label = 'Figure ' + (i + 1) + '.';
    check(at('figure ' + (i + 1) + ' is captioned in order'),
          !!cap && cap.textContent.trim().startsWith(label),
          cap ? cap.textContent.trim().slice(0, 22) : 'no caption');
  });

  // Links. A findings page is mostly citations, so a dead one is the failure
  // that matters most: every in-page anchor must exist, and every relative
  // link must be a file that is really there.
  [...doc.querySelectorAll('a[href]')].forEach(a => {
    const href = a.getAttribute('href');
    if (href.startsWith('#')) {
      check(at('anchor ' + href + ' resolves'), !!doc.getElementById(href.slice(1)));
    } else if (!/^(https?:|mailto:)/.test(href)) {
      const target = path.resolve(HERE, name, href);
      const ok = fs.existsSync(target) ||
                 fs.existsSync(path.join(target, 'index.html'));
      check(at('link ' + href + ' points at something'), ok, target);
    }
  });

  // A class that uppercases its content must not be given a hex number.
  // `0x10040000` renders as `0X10040000`, which this project has shipped
  // before -- in the chapter explaining what `0x` means. Neither the markup
  // nor the stylesheet looks wrong on its own, which is why it needs a check.
  UPPERCASING.forEach(sel => {
    let matches;
    try { matches = [...doc.querySelectorAll(sel)]; } catch (e) { return; }
    matches.forEach(el => {
      const hex = el.textContent.match(/0x[0-9a-f]+/i);
      check(at(sel + ' is uppercased, so it carries no hex'), !hex,
            hex ? hex[0] + ' in "' + el.textContent.trim().slice(0, 34) + '"' : '');
    });
  });

  // Nothing about the bench, and no path off this machine.
  const leak = html.match(/192\.168|10\.\d+\.\d+\.\d+|[0-9a-f]{2}(:[0-9a-f]{2}){5}|ttyACM|\/home\/|\/Users\//i);
  check(at('no private path or address'), !leak, leak && leak[0]);

  return { doc, html };
}

const seen = new Set();
PAGES.forEach(name => {
  const { doc } = drivePage(name);
  classesInMarkup(doc).forEach(c => seen.add(c));
});

const css = fs.readFileSync(path.join(HERE, 'style.css'), 'utf8');
const styled = classesInCss(css);
const unstyled = [...seen].filter(c => !styled.has(c)).sort();
const unused = [...styled].filter(c => !seen.has(c)).sort();
check('every class in the markup has a rule', unstyled.length === 0, unstyled.join(' '));
check('every rule in the stylesheet is used', unused.length === 0, unused.join(' '));

check('there is at least one findings page', PAGES.length > 0, PAGES.join(', '));

failed.forEach(f => console.log('  FAIL  ' + f));
console.log(PAGES.length + ' page(s), ' + passed.length + ' passed, ' +
            failed.length + ' failed');
process.exit(failed.length ? 1 : 0);
