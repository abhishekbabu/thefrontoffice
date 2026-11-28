/**
 * Figures as the server sends them — a label, a value already written, and
 * whether it should pull the eye — in the three shapes a page lays them out.
 *
 * Every figure is computed by the provider from live league state, never
 * written by the model, so these can be read as fact.
 */
import type { View } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { LABEL, Label } from "@/components/ui/label";
import { toneText } from "@/lib/tone";
import type { Stat } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The strip under a page title: where the team stands, before any reading. */
export function StatStrip<M>(h: Html.H<M>, stats: Stat[]) {
  if (!stats.length) return null;

  // A band under the header, so it spans the column like the header does,
  // its rule reaching the edge while the figures keep to the page's width.
  return h.div
    .attrs({ "data-bleed": "", class: "border-b border-border" })
    .children(StatCells(h, { stats, class: "mx-auto max-w-(--page-max)" }));
}

/**
 * Figures side by side, each its label over its value and a rule between:
 * the strip under a page title, and the facts under a player's name.
 *
 * Each figure's divider is on its left, and the row is pulled a pixel left
 * under a clip: whichever figure starts a line — the first, or the first
 * after a wrap on a phone — has its divider cut off, and no line ends on a
 * divider with nothing after it. A value longer than its line (a manager's
 * team name) is cut short rather than widening the row.
 *
 * A figure that changes — a week stepped, a score updated — fades the new
 * value in rather than being swapped in a frame, and without rolling digits:
 * the new value is to be read, not watched arriving.
 */
export function StatCells<M>(h: Html.H<M>, { stats, class: extra }: { stats: Stat[]; class?: string | undefined }) {
  return h.div.attr("class", cn("overflow-hidden", extra)).children(
    // A list of terms: each value is read out with what it is.
    h.dl.class("-ml-px flex flex-wrap").children(
      stats.map((stat) =>
        h.div
          .key(stat.label)
          .class("min-w-[7rem] max-w-full border-l border-border px-5 py-2.5")
          .children(
            h.dt.attr("class", cn(LABEL, "truncate")).children(stat.label),
            h.dd
              .attr(
                "class",
                cn(
                  "relative mt-0.5 truncate font-display text-[19px] font-semibold tracking-tight tabular-nums",
                  toneText(stat.tone),
                ),
              )
              .children(
                h.span.key(stat.value).class("inline-block max-w-full animate-fade truncate align-top").children(stat.value),
              ),
          ),
      ),
    ),
  );
}

/**
 * Parallel answers to one question, on a grid: reading down a column beats
 * hunting along a strip when there are several of the same kind.
 */
export function StatGrid<M>(h: Html.H<M>, stats: Stat[]) {
  return h.div.class("grid grid-cols-2 gap-x-4 px-4 py-1 sm:grid-cols-4").children(
    stats.map((stat) =>
      h.div
        .key(stat.label)
        .class("flex flex-col gap-0.5 py-2.5")
        .children(
          Label(h, { class: "truncate" }).children(stat.label),
          h.span
            .attr(
              "class",
              cn(
                "truncate text-[13px]",
                stat.tone === "good" && "font-medium",
                toneText(stat.tone, "text-muted-foreground"),
              ),
            )
            .children(stat.value),
        ),
    ),
  );
}

/** Figures as label-and-value lines, read down: a player's season, a week's warnings. */
export function StatList<M>(h: Html.H<M>, { stats, class: extra }: { stats: Stat[]; class?: string | undefined }) {
  return h.dl.attr("class", extra).children(
    stats.map((stat) =>
      h.div
        .key(stat.label)
        .class("flex items-baseline justify-between gap-3 border-b border-border/45 py-1.5 last:border-b-0")
        .children(
          h.dt.class("text-[13px] text-muted-foreground").children(stat.label),
          h.dd
            .attr("class", cn("text-right font-mono text-[13px] tabular-nums", toneText(stat.tone)))
            .children(Linked(h, { url: stat.url, children: [stat.value] })),
        ),
    ),
  );
}

/** `children`, linked to `url` in a new tab where there is one: a headline opens its article. */
export function Linked<M, C extends View.Children<M>>(h: Html.H<M>, { url, children }: { url?: string | undefined; children: C }) {
  if (!url) return h.span.class("contents").children(children);

  return h.a
    .attrs({
      href: url,
      target: "_blank",
      rel: "noopener noreferrer",
      class: "underline decoration-border underline-offset-2 hover:text-foreground hover:decoration-foreground",
    })
    // Its own click, so a row that opens on a click does not open as well.
    .on("click", () => undefined)
    .children(children);
}
