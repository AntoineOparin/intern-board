"""Word (.docx) files for tailored resumes and cover letters, built with the standard library.

The layout mirrors the printable page (frontend/src/styles/features/doc-page.css): the same
element sizes and spacing (in pt, scaled by the fit check's `sp`), plus the user's formatting
from `content.format` and the inline runs in each line. See documents.py for the content shape.
"""

import io
import time
import zipfile
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
LETTER_W, LETTER_H = 12240, 15840  # twips
DEFAULT_MARGINS = {"top": 0.5, "right": 0.5, "bottom": 0.5, "left": 0.5}
DEFAULT_FONT = "Source Serif 4"
HEADINGS = {"education": "Education", "experience": "Experience", "projects": "Projects", "skills": "Skills"}
JC = {"left": "left", "center": "center", "right": "right", "justify": "both"}
RESUME_LINE, LETTER_LINE = 1.22, 1.38  # line heights on the page
WORD_SINGLE = 1.17  # roughly what Word calls single spacing, as a multiple of the font size


def _attr(s: str) -> str:
    return escape(s, {'"': "&quot;"})


def runs_of(line) -> list[dict]:
    """A line as runs: a plain string is one run."""
    if isinstance(line, list):
        return [r for r in line if isinstance(r, dict) and r.get("t")]
    return [{"t": str(line)}] if line else []


def plain(line) -> str:
    return "".join(r["t"] for r in runs_of(line))


class Builder:
    def __init__(self, content: dict, fs: float, sp: float, line: float):
        fmt = content.get("format") or {}
        page = fmt.get("page") or {}
        self.styles = fmt.get("styles") or {}
        self.margins = {**DEFAULT_MARGINS, **(page.get("margins") or {})}
        self.font = page.get("font") or DEFAULT_FONT
        self.lh = float(page.get("lineHeight") or 1)
        self.fs, self.sp = fs, sp
        self.line_pt = fs * line * self.lh  # one line, for spacing given in lines
        self.width = round((8.5 - self.margins["left"] - self.margins["right"]) * 1440)
        self.body: list[str] = []

    # ---------- runs ----------
    def size(self, key: str, default: float = 1) -> int:
        """Half-points for an element: the user's multiple of the base size, or the page's default."""
        k = (self.styles.get(key) or {}).get("size") or default
        return max(2, round(self.fs * k * 2))

    def runs(self, line, key: str = "", default_size: float = 1, b=False, i=False, caps=False) -> str:
        sz = self.size(key, default_size)
        out = []
        for r in runs_of(line):
            props = []
            # A run can turn off what the element has by default (an unbolded word in a school name).
            if r.get("b", b):
                props.append("<w:b/>")
            if r.get("i", i):
                props.append("<w:i/>")
            if caps:
                props.append("<w:caps/>")
            if r.get("c"):
                props.append(f'<w:color w:val="{_attr(r["c"].lstrip("#").upper())}"/>')
            props.append(f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>')  # the schema's order: b, i, caps, color, sz, u
            if r.get("u"):
                props.append('<w:u w:val="single"/>')
            rpr = f"<w:rPr>{''.join(props)}</w:rPr>"
            for n, part in enumerate(r["t"].split("\n")):
                if n:
                    out.append(f"<w:r>{rpr}<w:br/></w:r>")
                if part:
                    out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
        return "".join(out)

    @staticmethod
    def tab() -> str:
        return "<w:r><w:tab/></w:r>"

    # ---------- paragraphs ----------
    def para(self, runs: str, block: str = "", before: float = 0, after: float = 0, align: str | None = None,
             line: float = RESUME_LINE, tab_right=False, border=False, bullet=False, keep_next=False):
        style = self.styles.get(block) or {}
        before += (style.get("before") or 0) * self.line_pt
        after += (style.get("after") or 0) * self.line_pt
        align = style.get("align") or align
        ppr = []
        if keep_next:
            ppr.append("<w:keepNext/>")
        if bullet:
            ppr.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
        if border:
            ppr.append('<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="000000"/></w:pBdr>')
        if tab_right:
            ppr.append(f'<w:tabs><w:tab w:val="right" w:pos="{self.width}"/></w:tabs>')
        ppr.append(f'<w:spacing w:before="{round(before * 20)}" w:after="{round(after * 20)}" '
                   f'w:line="{round(240 * line * self.lh / WORD_SINGLE)}" w:lineRule="auto"/>')
        if align:
            ppr.append(f'<w:jc w:val="{JC[align]}"/>')
        self.body.append(f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{runs}</w:p>")

    # ---------- shared pieces ----------
    def header(self, h: dict, name_size: float):
        self.para(self.runs(h.get("name", ""), "header.name", name_size, b=True), "header.name", align="center",
                  line=1.1)
        parts = [self.runs(c, f"header.contact.{i}", 0.95) for i, c in enumerate(h.get("contact") or [])]
        parts += [self.runs(l.get("url", ""), f"header.links.{i}.url", 0.95)
                  for i, l in enumerate(h.get("links") or [])]
        sep = self.runs(" | ", "header.contact", 0.95)
        if parts:
            self.para(sep.join(parts), "header.contact", before=3 * self.sp, align="center")

    def document(self) -> str:
        m = {k: round(v * 1440) for k, v in self.margins.items()}
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{W}"><w:body>'
                + "".join(self.body)
                + f'<w:sectPr><w:pgSz w:w="{LETTER_W}" w:h="{LETTER_H}"/><w:pgMar w:top="{m["top"]}" '
                  f'w:right="{m["right"]}" w:bottom="{m["bottom"]}" w:left="{m["left"]}" w:header="360" '
                  f'w:footer="360" w:gutter="0"/></w:sectPr></w:body></w:document>')


# ---------- resume ----------

def _resume(b: Builder, c: dict):
    b.header(c.get("header") or {}, 2)
    headings = c.get("headings") or {}
    sp = b.sp

    def heading(section: str):
        key = f"heading.{section}"
        b.para(b.runs(headings.get(section) or HEADINGS[section], key, 1.05, b=True, caps=True), key,
               before=9 * sp, after=4 * sp, border=True, keep_next=True)

    def row(left: str, right: str, before: float = 0):
        b.para(left + (b.tab() + right if right else ""), before=before, tab_right=True, keep_next=True)

    def gap(block: str, n: int) -> float:
        """Space above an entry: the page's gap between entries plus the entry's own "space before"."""
        return (6 * sp if n else 0) + ((b.styles.get(block) or {}).get("before") or 0) * b.line_pt

    def bullets(x: dict, prefix: str):
        for i, s in enumerate(x.get("bullets") or []):
            key = f"{prefix}.bullets.{i}"
            b.para(b.runs(s, key), key, before=2 * sp if i == 0 else 0, after=1.5 * sp, bullet=True)

    if c.get("education"):
        heading("education")
        for n, e in enumerate(c["education"]):
            p = f"education.{n}"
            row(b.runs(e.get("school"), f"{p}.school", b=True), b.runs(e.get("location"), f"{p}.location"), gap(p, n))
            row(b.runs(e.get("degree"), f"{p}.degree", i=True), b.runs(e.get("dates"), f"{p}.dates"))
            for i, d in enumerate(e.get("details") or []):
                key = f"{p}.details.{i}"
                b.para(b.runs(d, key), key, before=1 * sp)
            if n == 0 and c.get("awards"):
                b.para(b.runs("Awards: ", "awards", b=True) + b.runs("; ".join(c["awards"]), "awards"), "awards",
                       before=1 * sp)
            _entry_after(b, p)

    for section in ("experience", "projects"):
        if not c.get(section):
            continue
        heading(section)
        for n, x in enumerate(c[section]):
            p = f"{section}.{n}"
            if section == "experience":
                row(b.runs(x.get("organization"), f"{p}.organization", b=True),
                    b.runs(x.get("location"), f"{p}.location"), gap(p, n))
                row(b.runs(x.get("role"), f"{p}.role", i=True), b.runs(x.get("dates"), f"{p}.dates"))
            else:
                left = b.runs(x.get("name"), f"{p}.name", b=True)
                if x.get("tech"):
                    left += b.runs(" | ", f"{p}.name") + b.runs(x["tech"], f"{p}.tech", i=True)
                if x.get("link"):
                    left += b.runs(" | ", f"{p}.name") + b.runs(x["link"], f"{p}.link")
                row(left, b.runs(x.get("dates"), f"{p}.dates"), gap(p, n))
            bullets(x, p)
            _entry_after(b, p)

    if c.get("skills"):
        heading("skills")
        for n, g in enumerate(c["skills"]):
            key = f"skills.{n}"
            b.para(b.runs(g.get("label"), f"{key}.label", b=True) + b.runs(": ", f"{key}.label", b=True)
                   + b.runs(", ".join(g.get("items") or []), f"{key}.items"), key, before=1.5 * sp if n else 0)


def _entry_after(b: Builder, block: str):
    """An entry's own "space after" goes below its last paragraph."""
    after = ((b.styles.get(block) or {}).get("after") or 0) * b.line_pt
    if after and b.body:
        b.body.append(f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="{max(1, round(after * 20))}" '
                      f'w:lineRule="exact"/></w:pPr></w:p>')


# ---------- cover letter ----------

def _letter(b: Builder, c: dict):
    sp = b.sp
    b.header(c.get("header") or {}, 1.8)
    b.para(b.runs(c.get("date"), "date"), "date", before=22 * sp)
    b.para(b.runs(c.get("recipient"), "recipient"), "recipient", before=2)
    b.para(b.runs(c.get("greeting"), "greeting"), "greeting", before=16 * sp, line=LETTER_LINE)
    for i, p in enumerate(c.get("paragraphs") or []):
        key = f"paragraphs.{i}"
        b.para(b.runs(p, key), key, before=9 * sp, line=LETTER_LINE)
    b.para(b.runs(c.get("closing"), "closing"), "closing", before=14 * sp, line=LETTER_LINE)
    b.para(b.runs(c.get("signature"), "signature"), "signature", before=20 * sp, line=LETTER_LINE)


# ---------- package ----------

def _styles(font: str, fs: float) -> str:
    f = _attr(font)
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:styles xmlns:w="{W}">'
            f'<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:eastAsia="{f}" w:cs="{f}"/>'
            f'<w:sz w:val="{round(fs * 2)}"/><w:szCs w:val="{round(fs * 2)}"/><w:lang w:val="en-US"/></w:rPr>'
            '</w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr></w:pPrDefault>'
            '</w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>'
            '</w:style></w:styles>')


def _numbering(font: str, fs: float) -> str:
    left = round(1.25 * fs * 20)  # the page's 1.15em list indent plus the item's padding
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:numbering xmlns:w="{W}">'
            '<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0">'
            '<w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/>'
            f'<w:pPr><w:ind w:left="{left}" w:hanging="{round(left * 0.8)}"/></w:pPr>'
            f'<w:rPr><w:rFonts w:ascii="{_attr(font)}" w:hAnsi="{_attr(font)}"/></w:rPr></w:lvl></w:abstractNum>'
            '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/numbering.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '</Types>')
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
    'Target="docProps/core.xml"/></Relationships>')
DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" '
    'Target="numbering.xml"/></Relationships>')


def _core(title: str, author: str) -> str:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')


def build(kind: str, content: dict, fs: float = 11, sp: float = 1, title: str = "") -> bytes:
    """The .docx file for a document. `fs` and `sp` are the base size and spacing the page fitted to."""
    b = Builder(content, fs, sp, RESUME_LINE if kind == "resume" else LETTER_LINE)
    (_resume if kind == "resume" else _letter)(b, content)
    author = plain((content.get("header") or {}).get("name"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/document.xml", b.document())
        z.writestr("word/styles.xml", _styles(b.font, fs))
        z.writestr("word/numbering.xml", _numbering(b.font, fs))
        z.writestr("docProps/core.xml", _core(title, author))
    return buf.getvalue()
