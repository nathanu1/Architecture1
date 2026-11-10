// Turns the town's display font (Fredoka Bold, SIL Open Font License) into the small outline
// file the 3D title uses for its extruded letters: `node scripts/make-title-font.mjs`.
// Only capital letters are kept. The output is committed, so a build does not need this script.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import opentype from "opentype.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = path.resolve(here, "../node_modules/@fontsource/fredoka/files/fredoka-latin-700-normal.woff");
const buf = fs.readFileSync(source);
const font = opentype.parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
const scale = 100000 / ((font.unitsPerEm || 2048) * 72); // the scale three.js typefaces use
const r = Math.round;
const glyphs = {};
for (const ch of "ABCDEFGHIJKLMNOPQRSTUVWXYZ ") {
  const glyph = font.charToGlyph(ch);
  let o = "";
  for (const c of glyph.path.commands) {
    const type = c.type.toLowerCase() === "c" ? "b" : c.type.toLowerCase();
    o += `${type} `;
    if (c.x !== undefined && c.y !== undefined) o += `${r(c.x * scale)} ${r(c.y * scale)} `;
    if (c.x1 !== undefined && c.y1 !== undefined) o += `${r(c.x1 * scale)} ${r(c.y1 * scale)} `;
    if (c.x2 !== undefined && c.y2 !== undefined) o += `${r(c.x2 * scale)} ${r(c.y2 * scale)} `;
  }
  glyphs[ch] = { ha: r(glyph.advanceWidth * scale), x_min: r((glyph.xMin ?? 0) * scale), x_max: r((glyph.xMax ?? 0) * scale), o };
}
const out = {
  glyphs,
  familyName: "Fredoka Bold (capitals)",
  license: "SIL Open Font License 1.1, The Fredoka Project Authors",
  ascender: r(font.ascender * scale),
  descender: r(font.descender * scale),
  underlinePosition: font.tables.post.underlinePosition,
  underlineThickness: font.tables.post.underlineThickness,
  boundingBox: { xMin: font.tables.head.xMin, xMax: font.tables.head.xMax, yMin: font.tables.head.yMin, yMax: font.tables.head.yMax },
  resolution: 1000,
};
const target = path.resolve(here, "../src/tab/title-font.json");
fs.writeFileSync(target, JSON.stringify(out));
console.log(`wrote ${path.relative(process.cwd(), target)}: ${Object.keys(glyphs).length} glyphs, ${(fs.statSync(target).size / 1024).toFixed(1)} kB`);
