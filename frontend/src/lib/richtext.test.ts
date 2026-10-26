import { describe, expect, it } from "vitest";
import { compact, fromDom, hex, pageOf, plain, pruned, rangeAt, shiftKeys, textOffsets, toDom, withoutFormatting } from "./richtext";
import type { Line } from "./types";

const el = (html: string) => {
  const div = document.createElement("div");
  div.innerHTML = html; // test input only
  return div;
};

describe("plain and hex", () => {
  it("reads a line's text", () => {
    expect(plain("a")).toBe("a");
    expect(plain([{ t: "a", b: true }, { t: "b" }])).toBe("ab");
    expect(plain(undefined)).toBe("");
  });

  it("normalizes colours", () => {
    expect(hex("rgb(31, 58, 95)")).toBe("#1f3a5f");
    expect(hex("#1F3A5F")).toBe("#1f3a5f");
    expect(hex("#abc")).toBe("#aabbcc");
    expect(hex("red")).toBeUndefined();
  });
});

describe("fromDom", () => {
  it("returns a plain string when nothing is formatted", () => {
    expect(fromDom(el("  Built a   thing. "))).toBe("Built a thing.");
    expect(fromDom(el("Built <span>a</span> thing."))).toBe("Built a thing.");
  });

  it("reads bold, italic, underline and colour, merging equal runs", () => {
    expect(fromDom(el('Cut <b>report</b><strong> time</strong> <i>by</i> <u>half</u> <font color="#1F3A5F">now</font>'))).toEqual([
      { t: "Cut " }, { t: "report time", b: true }, { t: " " }, { t: "by", i: true }, { t: " " }, { t: "half", u: true },
      { t: " " }, { t: "now", c: "#1f3a5f" },
    ]);
  });

  it("reads nested marks and inline styles", () => {
    expect(fromDom(el('<b><em>both</em></b> <span style="color: rgb(122, 31, 43); font-weight: 700">red</span>'))).toEqual([
      { t: "both", b: true, i: true }, { t: " " }, { t: "red", b: true, c: "#7a1f2b" },
    ]);
  });

  it("keeps line breaks and trims around them", () => {
    expect(fromDom(el("one <br> two<br>"))).toBe("one\ntwo");
    expect(fromDom(el("one<div>two</div>"))).toBe("one\ntwo");
  });

  it("drops marks the element has anyway, and keeps an explicit unbold", () => {
    expect(fromDom(el("<b>School</b>"), { b: true })).toBe("School");
    expect(fromDom(el('Big <span style="font-weight: normal">small</span>'), { b: true })).toEqual([
      { t: "Big " }, { t: "small", b: false },
    ]);
    expect(fromDom(el('<span style="color: #000000">black</span>'))).toBe("black");
  });
});

describe("toDom", () => {
  it("round-trips formatted lines", () => {
    const lines: Line[] = [
      "Plain & <simple>",
      [{ t: "Cut " }, { t: "report time", b: true, u: true }, { t: "\nby half", i: true, c: "#0f5e5a" }],
    ];
    for (const line of lines) {
      const node = document.createElement("div");
      toDom(line, node);
      expect(fromDom(node)).toEqual(line);
    }
  });

  it("never parses markup in the text", () => {
    const node = document.createElement("div");
    toDom('<img src=x onerror="alert(1)">', node);
    expect(node.querySelector("img")).toBeNull();
    expect(node.textContent).toBe('<img src=x onerror="alert(1)">');
  });

  it("writes an explicit unbold so it survives a default-bold field", () => {
    const node = document.createElement("strong");
    toDom([{ t: "a" }, { t: "b", b: false }], node);
    expect(node.querySelector("span")?.style.fontWeight).toBe("normal");
    expect(fromDom(node, { b: true })).toEqual([{ t: "a" }, { t: "b", b: false }]);
  });
});

describe("compact", () => {
  it("collapses spaces across runs", () => {
    expect(compact([{ t: " a " }, { t: " b", b: true }, { t: "  " }])).toEqual([{ t: "a " }, { t: "b", b: true }]);
    expect(compact([{ t: "" }])).toBe("");
  });
});

describe("shiftKeys", () => {
  it("drops the styles of removed items and renumbers the rest", () => {
    const styles = {
      "experience.0.bullets.0": { align: "center" as const },
      "experience.0.bullets.1": { after: 1 },
      "experience.0.bullets.2": { size: 1.2 },
      "experience.0.bullets.2.x": { before: 1 },
      "experience.1.bullets.1": { after: 2 },
      "header.name": { size: 2.2 },
    };
    expect(shiftKeys(styles, "experience.0.bullets", [true, false, true])).toEqual({
      "experience.0.bullets.0": { align: "center" },
      "experience.0.bullets.1": { size: 1.2 },
      "experience.0.bullets.1.x": { before: 1 },
      "experience.1.bullets.1": { after: 2 },
      "header.name": { size: 2.2 },
    });
  });
});

describe("pruned and pageOf", () => {
  it("drops empty values", () => {
    expect(pruned({ align: undefined, before: 0, after: 1 })).toEqual({ after: 1 });
    expect(pruned({})).toBeNull();
  });

  it("fills in the default page", () => {
    expect(pageOf({ page: { margins: { top: 1, right: 0.5, bottom: 1, left: 0.5 } } })).toEqual({
      margins: { top: 1, right: 0.5, bottom: 1, left: 0.5 }, size: "auto", lineHeight: 1, font: "Source Serif 4",
    });
    expect(pageOf(undefined).margins.top).toBe(0.5);
  });
});

describe("withoutFormatting", () => {
  it("turns runs back into strings and leaves everything else", () => {
    const content = { header: { name: [{ t: "Sam", b: true }], contact: ["a", [{ t: "b", i: true }]] }, refs: [{ point_id: "p", phrasing: 0 }], notes: { gaps: ["x"] } };
    expect(withoutFormatting(content)).toEqual({ header: { name: "Sam", contact: ["a", "b"] }, refs: [{ point_id: "p", phrasing: 0 }], notes: { gaps: ["x"] } });
  });
});

describe("textOffsets and rangeAt", () => {
  it("survive a redraw of the field", () => {
    const node = document.createElement("div");
    toDom([{ t: "one " }, { t: "two", b: true }, { t: "\nthree" }], node);
    const r = rangeAt(node, 4, 9);
    expect(r.toString()).toBe("twot"); // the line break has no text
    expect(textOffsets(node, r)).toEqual([4, 9]);
    toDom("one two\nthree", node);
    expect(rangeAt(node, 4, 7).toString()).toBe("two");
    expect(textOffsets(node, rangeAt(node, 99, 99))).toEqual([13, 13]);
  });
});
