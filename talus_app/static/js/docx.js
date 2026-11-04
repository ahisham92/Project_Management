// A small Word (.docx) writer: headings, paragraphs, tables, PNG images and page
// breaks, packed into a stored (uncompressed) zip. No libraries, so it runs offline
// and inside the site as it is.

const enc = new TextEncoder();

const CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();
export function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** A zip with every entry stored. files: [{ name, data: Uint8Array | string }]. */
export function zip(files) {
  const parts = [], central = [];
  let offset = 0;
  const u16 = (v) => [v & 0xff, (v >>> 8) & 0xff];
  const u32 = (v) => [v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff];
  for (const f of files) {
    const name = enc.encode(f.name);
    const data = typeof f.data === "string" ? enc.encode(f.data) : f.data;
    const crc = crc32(data);
    // version 20, UTF-8 names (bit 11), stored, fixed 1980 date
    const head = [...u16(20), ...u16(0x0800), ...u16(0), ...u16(0), ...u16(0x21), ...u32(crc), ...u32(data.length), ...u32(data.length), ...u16(name.length), ...u16(0)];
    const local = new Uint8Array([...u32(0x04034b50), ...head]);
    parts.push(local, name, data);
    central.push(new Uint8Array([...u32(0x02014b50), ...u16(20), ...head, ...u16(0), ...u16(0), ...u16(0), ...u32(0), ...u32(offset)]), name);
    offset += local.length + name.length + data.length;
  }
  const size = central.reduce((a, b) => a + b.length, 0);
  const end = new Uint8Array([...u32(0x06054b50), ...u16(0), ...u16(0), ...u16(files.length), ...u16(files.length), ...u32(size), ...u32(offset), ...u16(0)]);
  return new Blob([...parts, ...central, end], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
}

const x = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")
  // characters XML 1.0 does not allow
  .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "");

const run = (text, rp = "") => `<w:r>${rp ? `<w:rPr>${rp}</w:rPr>` : ""}<w:t xml:space="preserve">${x(text)}</w:t></w:r>`;

/** Runs from a string, where **bold** spans are bold. */
const runs = (text, rp = "") => String(text ?? "").split(/(\*\*[^*]+\*\*)/).filter(Boolean)
  .map((s) => (s.startsWith("**") ? run(s.slice(2, -2), `<w:b/>${rp}`) : run(s, rp))).join("");

const para = (text, { style, align, rp = "", keep } = {}) =>
  `<w:p><w:pPr>${style ? `<w:pStyle w:val="${style}"/>` : ""}${keep ? "<w:keepNext/>" : ""}${align ? `<w:jc w:val="${align}"/>` : ""}</w:pPr>${runs(text, rp)}</w:p>`;

const TW = 9638; // text width in twips: A4 with 2 cm margins

function table(b) {
  const n = b.widths?.length || Math.max(1, b.head?.length || 0, ...b.rows.map((r) => (Array.isArray(r) ? r.length : 0)));
  const w = b.widths ? b.widths.map((f) => Math.round(f * TW)) : Array(n).fill(Math.round(TW / n));
  const cell = (v, i, head, span) => `<w:tc><w:tcPr><w:tcW w:w="${span ? TW : w[i]}" w:type="dxa"/>${span ? `<w:gridSpan w:val="${n}"/>` : ""}${head ? '<w:shd w:val="clear" w:color="auto" w:fill="EFEEEA"/>' : ""}</w:tcPr>
    <w:p><w:pPr><w:spacing w:before="20" w:after="20"/>${typeof v === "number" || /^[-−]?[\d.,]+$/.test(String(v)) ? '<w:jc w:val="right"/>' : ""}</w:pPr>${runs(v, `${head ? "<w:b/>" : ""}<w:sz w:val="${b.small ? 15 : 18}"/>`)}</w:p></w:tc>`;
  const rows = [];
  if (b.head) rows.push(`<w:tr><w:trPr><w:tblHeader/></w:trPr>${b.head.map((v, i) => cell(v, i, true)).join("")}</w:tr>`);
  for (const r of b.rows) {
    if (r.group) rows.push(`<w:tr>${cell(r.group, 0, true, true)}</w:tr>`);
    else rows.push(`<w:tr><w:trPr><w:cantSplit/></w:trPr>${r.map((v, i) => cell(v, i, false)).join("")}</w:tr>`);
  }
  const border = (s) => `<w:${s} w:val="single" w:sz="4" w:space="0" w:color="C9C8C2"/>`;
  return `<w:tbl><w:tblPr><w:tblW w:w="${TW}" w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblBorders>${["top", "left", "bottom", "right", "insideH", "insideV"].map(border).join("")}</w:tblBorders><w:tblCellMar><w:left w:w="70" w:type="dxa"/><w:right w:w="70" w:type="dxa"/></w:tblCellMar></w:tblPr>
    <w:tblGrid>${w.map((v) => `<w:gridCol w:w="${v}"/>`).join("")}</w:tblGrid>${rows.join("")}</w:tbl>${para("")}`;
}

function image(b, id) {
  const cm = b.widthCm || 17;
  const cx = Math.round(cm * 360000), cy = Math.round(cx * b.h / b.w);
  return `<w:p><w:pPr><w:jc w:val="center"/><w:keepNext/></w:pPr><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="${cx}" cy="${cy}"/><wp:docPr id="${id}" name="Figure ${id}"/>
    <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
    <pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="${id}" name="image${id}.png"/><pic:cNvPicPr/></pic:nvPicPr>
    <pic:blipFill><a:blip r:embed="rImg${id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
    <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${cx}" cy="${cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>`;
}

const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/><w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="280" w:after="100"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:color w:val="1F1F1E"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="23"/><w:szCs w:val="23"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:jc w:val="center"/></w:pPr><w:rPr><w:i/><w:color w:val="52514E"/><w:sz w:val="17"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtle"><w:name w:val="Subtle"/><w:basedOn w:val="Normal"/><w:rPr><w:color w:val="52514E"/><w:sz w:val="18"/></w:rPr></w:style>
</w:styles>`;

/**
 * blocks: { t: "title" | "h1" | "h2" | "p" | "note" | "caption", text }
 *       | { t: "table", head?, rows: [[...] | { group }], widths?, small? }
 *       | { t: "img", png: Uint8Array, w, h, widthCm? }
 *       | { t: "break" }
 */
export function docx(blocks, { title = "Report", footer = "" } = {}) {
  const media = [];
  const body = blocks.map((b) => {
    if (b.t === "title") return para(b.text, { style: "Title" });
    if (b.t === "h1") return para(b.text, { style: "Heading1" });
    if (b.t === "h2") return para(b.text, { style: "Heading2" });
    if (b.t === "note") return para(b.text, { style: "Subtle" });
    if (b.t === "caption") return para(b.text, { style: "Caption" });
    if (b.t === "table") return table(b);
    if (b.t === "break") return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>';
    if (b.t === "img") { if (!b.png) return ""; media.push(b.png); return image(b, media.length); }
    return para(b.text);
  }).join("\n");
  const doc = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
<w:body>${body}
<w:sectPr><w:footerReference w:type="default" r:id="rFoot"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr></w:body></w:document>`;
  const foot = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:pPr><w:pStyle w:val="Subtle"/><w:tabs><w:tab w:val="right" w:pos="${TW}"/></w:tabs></w:pPr>${run(footer)}<w:r><w:tab/></w:r>${run("Page ")}<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>${run("1")}<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>`;
  const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rFoot" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
${media.map((_, i) => `<Relationship Id="rImg${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image${i + 1}.png"/>`).join("\n")}
</Relationships>`;
  const types = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>`;
  const root = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="r2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>`;
  const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");
  const core = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>${x(title)}</dc:title><dc:creator>Talus</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created></cp:coreProperties>`;
  return zip([
    { name: "[Content_Types].xml", data: types },
    { name: "_rels/.rels", data: root },
    { name: "docProps/core.xml", data: core },
    { name: "word/document.xml", data: doc },
    { name: "word/styles.xml", data: STYLES },
    { name: "word/footer1.xml", data: foot },
    { name: "word/_rels/document.xml.rels", data: rels },
    ...media.map((png, i) => ({ name: `word/media/image${i + 1}.png`, data: png })),
  ]);
}
