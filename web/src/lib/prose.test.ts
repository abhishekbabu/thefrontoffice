import { describe, expect, it } from "vitest";
import { parseProse, parseSpans } from "@/lib/prose";

describe("reading a model's answer", () => {
  it("splits paragraphs at a blank line", () => {
    expect(parseProse("One.\n\nTwo.").map((block) => block.kind)).toEqual(["paragraph", "paragraph"]);
  });

  it("joins lines with no blank between them into one paragraph", () => {
    expect(parseProse("One\ntwo")).toEqual([{ kind: "paragraph", spans: [{ text: "One two" }] }]);
  });

  it("gathers consecutive dashed lines into one list", () => {
    expect(parseProse("- a\n- b\n- c")).toMatchObject([{ kind: "list", items: [[{ text: "a" }], [{ text: "b" }], [{ text: "c" }]] }]);
  });

  it("tells a numbered list from a bulleted one", () => {
    expect(parseProse("1. a\n2. b")).toMatchObject([{ kind: "list", ordered: true }]);
  });

  it("reads a line that is only bold as a heading", () => {
    expect(parseProse("**Pros**\n- a")[0]).toEqual({ kind: "heading", spans: [{ text: "Pros" }] });
  });

  it("reads a hash heading as a heading", () => {
    expect(parseProse("## Verdict")).toMatchObject([{ kind: "heading" }]);
  });

  it("keeps bold inside a line as bold, with the text around it", () => {
    expect(parseSpans("a **b** c")).toEqual([{ text: "a " }, { text: "b", bold: true }, { text: " c" }]);
  });

  it("reads single asterisks as italic", () => {
    expect(parseSpans("*maybe*")).toEqual([{ text: "maybe", italic: true }]);
  });

  it("reads backticks as code", () => {
    expect(parseSpans("`WR1`")).toEqual([{ text: "WR1", code: true }]);
  });

  it("leaves underscores alone, since they appear in names", () => {
    expect(parseSpans("snap_share and _x_")).toEqual([{ text: "snap_share and _x_" }]);
  });

  it("leaves a lone asterisk as text", () => {
    expect(parseSpans("5 * 3")).toEqual([{ text: "5 * 3" }]);
  });
});
