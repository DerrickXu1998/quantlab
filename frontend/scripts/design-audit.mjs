#!/usr/bin/env node
/**
 * The design system, as a check rather than a convention.
 *
 * The palette, the type tiers, the 4px radius cap, the icon geometry and the
 * two permitted animations are rules this surface is built on, and a rule that
 * lives only in a review comment survives exactly as long as the reviewer's
 * attention. Everything here is mechanically checkable, so it is checked.
 *
 *   npm run design:audit
 *
 * Deliberately *not* a lint plugin: these are project rules about one product,
 * not general JavaScript style, and burying them in an eslint config would put
 * them somewhere nobody reads them.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'src');

function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

const files = walk(SRC).filter((f) => /\.(ts|tsx|css)$/.test(f));
const findings = [];

/** Strip comments and JSX-free string prose so rules match *code*, not notes. */
function code(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*(\/\/|\*).*$/gm, '');
}

function check(name, { test, files: subset = files, skip = () => false, why }) {
  for (const file of subset) {
    if (skip(file)) continue;
    const raw = readFileSync(file, 'utf8');
    code(raw)
      .split('\n')
      .forEach((line, index) => {
        if (test(line)) {
          findings.push({ name, why, file: relative(ROOT, file), line: index + 1, text: line.trim() });
        }
      });
  }
}

// --- Typography, colour, shape ---------------------------------------------

check('emoji', {
  // Pictographic ranges only. Arrows and dashes are punctuation, and a date
  // range written `2024-01-01 → 2024-12-31` is typography, not an emoji.
  test: (l) => /[\u{1F300}-\u{1FAFF}\u{1F900}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u.test(l),
  why: 'ZERO emojis anywhere.',
});

check('hard-coded colour', {
  test: (l) => /#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b/.test(l),
  skip: (f) => f.endsWith('styles.css'),
  why: 'One palette. Colours come from the tokens in styles.css, never inline.',
});

check('radius above 4px', {
  test: (l) => /\brounded-(?:lg|xl|2xl|3xl|full)\b/.test(l),
  why: 'Max border-radius 4px; no rounded-card cliches.',
});

check('shadow', {
  test: (l) => /\bshadow-(?!none)\w+/.test(l),
  why: 'Structure comes from 1px hairlines, never drop shadows.',
});

check('glassmorphism', {
  test: (l) => /\bbackdrop-(?:blur|filter)\b/.test(l),
  why: 'No glassmorphism.',
});

check('gradient', {
  test: (l) => /\bbg-gradient-|linear-gradient|radial-gradient/.test(l),
  skip: (f) => f.endsWith('draw.ts'),
  why: 'No gradients. (draw.ts is exempt: canvas fills under a plotted series.)',
});

check('off-palette hue', {
  test: (l) => /\b(?:purple|violet|indigo|fuchsia|blue|sky|cyan|teal)-\d{2,3}\b/.test(l),
  why: 'One accent (lime) and one semantic (red). No purple, no blue.',
});

// --- Icons -----------------------------------------------------------------

check('icon stroke not 1.5', {
  test: (l) => /strokeWidth=\{?(?!1\.5)[\d.]+\}?/.test(l),
  why: 'All icons render at 1.5px stroke.',
});

check('icon size not 16 or 20', {
  // `size` on a Lucide icon, not on <select size={5}>, which is a row count.
  test: (l) => /<[A-Z]\w*[^>]*\bsize=\{(?!16\}|20\})\d+\}/.test(l),
  why: 'Icons are 16px inline, 20px in the nav.',
});

// --- Motion ----------------------------------------------------------------

check('extra animation', {
  // Two are allowed: the entrance cascade, and the tick flash (a transition,
  // not a keyframe). Anything else is a third.
  test: (l) => /\banimate-(?!panel-in\b)[\w-]+/.test(l),
  why: 'One entrance (panel-in) and one continuous animation (the 400ms tick flash).',
});

check('motion on hover', {
  // `transition-colors` is deliberately allowed: nothing animates at rest, and
  // a colour shift on hover/focus is the affordance that tells you a control
  // is a control. What the brief bans is hover *bloat* — movement, scaling,
  // glow — so that is what is checked.
  test: (l) => /\bhover:(?:scale|translate|rotate|shadow|blur)|group-hover:(?:scale|translate)/.test(l),
  why: 'No hover bloat: no scaling, movement or glow on hover.',
});

// --- Fitting ---------------------------------------------------------------

check('scroll container that cannot shrink', {
  // The exact defect behind every mid-row clip on this surface: a flex child
  // that both grows and scrolls, but has no `min-h-0`. A flex item will not
  // shrink below its content by default, so the box never gets shorter than
  // the rows inside it, the scrollbar never engages, and the overflow is cut
  // off by the parent instead — leaving half a number as the last thing on
  // screen. `ScrollRegion` and `<Panel fill scroll>` exist so this does not
  // have to be remembered.
  test: (l) =>
    /\bflex-1\b/.test(l) && /\boverflow-(?:y-)?auto\b/.test(l) && !/\bmin-h-0\b/.test(l),
  why: 'A scrolling flex child needs min-h-0, or it clips instead of scrolling. Use ScrollRegion or <Panel fill scroll>.',
});

// --- Report ----------------------------------------------------------------

const byRule = new Map();
for (const f of findings) {
  if (!byRule.has(f.name)) byRule.set(f.name, []);
  byRule.get(f.name).push(f);
}

if (findings.length === 0) {
  console.log(`design audit: ${files.length} files, no violations`);
  process.exit(0);
}

for (const [name, hits] of byRule) {
  console.error(`\n${name} (${hits.length}) — ${hits[0].why}`);
  for (const hit of hits.slice(0, 20)) {
    console.error(`  ${hit.file}:${hit.line}  ${hit.text.slice(0, 100)}`);
  }
  if (hits.length > 20) console.error(`  ... and ${hits.length - 20} more`);
}
console.error(`\ndesign audit: ${findings.length} violations across ${byRule.size} rules`);
process.exit(1);
