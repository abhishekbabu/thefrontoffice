/**
 * A model's answer as blocks a page can lay out.
 *
 * The models answer in Markdown whether asked to or not — a bold line for a
 * heading, a dash per point — and shown as text that is a wall of asterisks
 * with its line breaks collapsed. This reads the part of Markdown they use and
 * nothing more: paragraphs, headings, lists, and bold, italic and code inside
 * a line. Anything else stays the text it was, which is the safe failure: no
 * markup is ever interpreted as HTML.
 */

export type Span = { text: string; bold?: boolean; italic?: boolean; code?: boolean };

export type Block =
  | { kind: "paragraph"; spans: Span[] }
  | { kind: "heading"; spans: Span[] }
  | { kind: "list"; ordered: boolean; items: Span[][] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;
/** A line that is nothing but bold reads as a heading, which is how it is meant. */
const BOLD_LINE = /^\s*\*\*([^*]+)\*\*:?\s*$/;

export function parseProse(text: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];

  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", spans: parseSpans(paragraph.join(" ")) });
    paragraph = [];
  };

  for (const line of text.split(/\r?\n/)) {
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    const heading = HEADING.exec(line) ?? BOLD_LINE.exec(line);
    if (bullet || numbered) {
      flush();
      const ordered = Boolean(numbered);
      const item = parseSpans((bullet ?? numbered)?.[1] ?? "");
      const last = blocks.at(-1);
      if (last?.kind === "list" && last.ordered === ordered) last.items.push(item);
      else blocks.push({ kind: "list", ordered, items: [item] });
    } else if (heading) {
      flush();
      blocks.push({ kind: "heading", spans: parseSpans(heading[1] ?? "") });
    } else if (line.trim() === "") {
      flush();
    } else {
      paragraph.push(line.trim());
    }
  }
  flush();
  return blocks;
}

/** `**bold**`, `*italic*` and `` `code` `` inside one line; underscores are left alone, being in names. */
const INLINE = /\*\*([^*]+)\*\*|`([^`]+)`|\*([^*\s][^*]*?)\*/g;

export function parseSpans(line: string): Span[] {
  const spans: Span[] = [];
  let at = 0;
  for (const match of line.matchAll(INLINE)) {
    if (match.index > at) spans.push({ text: line.slice(at, match.index) });
    const [, bold, code, italic] = match;
    if (bold !== undefined) spans.push({ text: bold, bold: true });
    else if (code !== undefined) spans.push({ text: code, code: true });
    else spans.push({ text: italic ?? "", italic: true });
    at = match.index + match[0].length;
  }
  if (at < line.length) spans.push({ text: line.slice(at) });
  return spans;
}
