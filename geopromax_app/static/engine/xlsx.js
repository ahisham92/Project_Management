// A small reader for Excel workbooks (.xlsx), enough to take the tables that
// SAFE exports: every sheet as rows of text cells. No dependencies; it runs in
// the browser and in Node (both have DecompressionStream).

const u16 = (v, o) => v.getUint16(o, true), u32 = (v, o) => v.getUint32(o, true);

async function inflate(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** The files inside a zip: { name: Uint8Array }. Only the ones `want` accepts. */
export async function unzip(buffer, want = () => true) {
  const bytes = new Uint8Array(buffer), v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let end = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 66000); i--) if (u32(v, i) === 0x06054b50) { end = i; break; }
  if (end < 0) throw new Error("this is not an Excel workbook (.xlsx)");
  const count = u16(v, end + 10);
  let p = u32(v, end + 16);
  const out = {};
  for (let i = 0; i < count && u32(v, p) === 0x02014b50; i++) {
    const method = u16(v, p + 10), size = u32(v, p + 20), nameLen = u16(v, p + 28), extra = u16(v, p + 30), comment = u16(v, p + 32), local = u32(v, p + 42);
    const name = new TextDecoder().decode(bytes.subarray(p + 46, p + 46 + nameLen));
    p += 46 + nameLen + extra + comment;
    if (!want(name)) continue;
    const start = local + 30 + u16(v, local + 26) + u16(v, local + 28);
    const data = bytes.subarray(start, start + size);
    out[name] = method === 0 ? data : await inflate(data);
  }
  return out;
}

const ENT = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
const text = (s) => s.replace(/&(#x?[0-9a-f]+|\w+);/gi, (m, e) => (e[0] === "#" ? String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : +e.slice(1)) : ENT[e] ?? m));
const tValues = (xml) => [...xml.matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)].map((m) => text(m[1])).join("");
const colIndex = (ref) => { let n = 0; for (const ch of ref) { if (ch < "A" || ch > "Z") break; n = n * 26 + ch.charCodeAt(0) - 64; } return n - 1; };

/** Every sheet of a workbook: [{ name, rows: [[text, ...], ...] }]. */
export async function readXlsx(buffer) {
  const files = await unzip(buffer, (n) => /^xl\/(workbook\.xml|_rels\/workbook\.xml\.rels|sharedStrings\.xml|worksheets\/[^/]+\.xml)$/.test(n));
  const str = (n) => (files[n] ? new TextDecoder().decode(files[n]) : "");
  const wb = str("xl/workbook.xml");
  if (!wb) throw new Error("this is not an Excel workbook (.xlsx)");
  const shared = [...str("xl/sharedStrings.xml").matchAll(/<si>([\s\S]*?)<\/si>/g)].map((m) => tValues(m[1]));
  const rels = Object.fromEntries([...str("xl/_rels/workbook.xml.rels").matchAll(/<Relationship\b[^>]*>/g)].map((m) => [/\bId="([^"]+)"/.exec(m[0])?.[1], /\bTarget="([^"]+)"/.exec(m[0])?.[1]]));
  const sheets = [];
  for (const m of wb.matchAll(/<sheet\b[^>]*>/g)) {
    const name = text(/\bname="([^"]*)"/.exec(m[0])?.[1] || ""), rid = /\br:id="([^"]+)"/.exec(m[0])?.[1];
    const target = (rels[rid] || "").replace(/^\/?(xl\/)?/, "xl/");
    const xml = str(target);
    const rows = [];
    for (const r of xml.matchAll(/<row\b[^>]*>([\s\S]*?)<\/row>/g)) {
      const row = [];
      for (const c of r[1].matchAll(/<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
        const ref = /\br="([A-Z]+)\d+"/.exec(c[1])?.[1], type = /\bt="([^"]+)"/.exec(c[1])?.[1], body = c[2] || "";
        const raw = /<v>([\s\S]*?)<\/v>/.exec(body)?.[1];
        const value = type === "s" ? shared[+raw] ?? "" : type === "inlineStr" ? tValues(body) : raw === undefined ? "" : text(raw);
        row[ref ? colIndex(ref) : row.length] = value;
      }
      rows.push(Array.from(row, (x) => x ?? ""));
    }
    sheets.push({ name, rows });
  }
  return sheets;
}
