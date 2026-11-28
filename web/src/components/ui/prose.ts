import type { Html } from "@effect/ui/html";
import { parseProse, type Span } from "@/lib/prose";
import { cn } from "@/lib/utils";

function Spans<M>(h: Html.H<M>, spans: Span[]) {
  return spans.map((span, i) =>
    span.code
      ? h.code.key(String(i)).class("rounded-sm bg-muted px-1 font-mono text-[0.92em]").children(span.text)
      : h.span
          .key(String(i))
          .attr("class", cn(span.bold && "font-semibold", span.italic && "italic") || undefined)
          .children(span.text),
  );
}

/** A model's answer, laid out: its paragraphs, headings and lists, in the app's own type. */
export function Prose<M>(h: Html.H<M>, { text, class: extra }: { text: string; class?: string | undefined }) {
  return h.div.attr("class", cn("flex flex-col gap-2", extra)).children(
    parseProse(text).map((block, i) => {
      if (block.kind === "heading")
        return h.p.key(String(i)).class("font-semibold [&:not(:first-child)]:mt-1").children(Spans(h, block.spans));

      if (block.kind === "list")
        return (block.ordered ? h.ol : h.ul)
          .key(String(i))
          .attr("class", cn("flex flex-col gap-1 pl-5", block.ordered ? "list-decimal" : "list-disc"))
          .children(
            block.items.map((item, j) =>
              h.li.key(String(j)).class("pl-0.5 marker:text-muted-foreground").children(Spans(h, item)),
            ),
          );

      return h.p.key(String(i)).children(Spans(h, block.spans));
    }),
  );
}
