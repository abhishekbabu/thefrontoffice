import { parseProse, type Span } from "@/lib/prose";
import { cn } from "@/lib/utils";

/** A model's answer, laid out: its paragraphs, headings and lists, in the app's own type. */
export function Prose({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {parseProse(text).map((block, i) =>
        block.kind === "heading" ? (
          <p key={i} className="font-semibold [&:not(:first-child)]:mt-1">
            <Spans spans={block.spans} />
          </p>
        ) : block.kind === "list" ? (
          (() => {
            const List = block.ordered ? "ol" : "ul";
            return (
              <List key={i} className={cn("flex flex-col gap-1 pl-5", block.ordered ? "list-decimal" : "list-disc")}>
                {block.items.map((item, j) => (
                  <li key={j} className="pl-0.5 marker:text-muted-foreground">
                    <Spans spans={item} />
                  </li>
                ))}
              </List>
            );
          })()
        ) : (
          <p key={i}>
            <Spans spans={block.spans} />
          </p>
        ),
      )}
    </div>
  );
}

function Spans({ spans }: { spans: Span[] }) {
  return spans.map((span, i) =>
    span.code ? (
      <code key={i} className="rounded-sm bg-muted px-1 font-mono text-[0.92em]">
        {span.text}
      </code>
    ) : (
      <span key={i} className={cn(span.bold && "font-semibold", span.italic && "italic")}>
        {span.text}
      </span>
    ),
  );
}
