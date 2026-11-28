import type { Html } from "@effect/ui/html";
import { Card, CardHeader } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Table, Td, Th } from "@/components/ui/table";
import { percent } from "@/lib/format";
import type { CategoryLine } from "@/lib/types";
import { cn } from "@/lib/utils";

const LEAD: Record<NonNullable<CategoryLine["lead"]>, { word: string; tone: string }> = {
  mine: { word: "You", tone: "text-ok" },
  theirs: { word: "Them", tone: "text-warn" },
  even: { word: "Level", tone: "text-muted-foreground" },
};

/** A chance of winning a category, toned as the header's win chance is; the figure itself carries it. */
function chanceTone(win: number): string {
  return win >= 0.6 ? "text-ok" : win <= 0.4 ? "text-warn" : "text-muted-foreground";
}

/**
 * A category week, read across: each category, both figures, who leads it,
 * and — where the week is forecast — your chance of winning it.
 *
 * The leader is said in words as well as weight and color, since a category
 * week is won by the count of those words. `title` names what is totalled
 * where a page shows more than one: the week, and a day of it.
 */
export function Categories<M>(
  h: Html.H<M>,
  { lines, title = "Categories" }: { lines: readonly CategoryLine[]; title?: string | undefined },
) {
  const forecast = lines.some((line) => line.win != null);

  return Card(h).children(
    CardHeader(h).children(h.span(title), h.span(`${lines.length} scored`)),
    Table(h).children(
      h.thead(
        h.tr(
          Th(h, "w-16").children("Cat"),
          Th(h, "w-20 text-right").children("You"),
          // Not the opponent's name, which truncates: the lineup cards below name both teams.
          Th(h, "w-20 text-right").children("Them"),
          Th(h, "text-right").children("Leads"),
          forecast && Th(h, "w-12 text-right").children("Win"),
        ),
      ),
      h.tbody(
        lines.map((line) => {
          const lead = line.lead ? LEAD[line.lead] : null;

          return h.tr
            .key(line.name)
            .class("font-mono text-[12.5px] [&:last-child>td]:border-b-0")
            .children(
              Td(h).children(Label(h).children(line.name)),
              Td(h, cn("text-right", line.lead === "mine" && "font-semibold")).children(line.mine || "—"),
              Td(h, cn("text-right", line.lead === "theirs" && "font-semibold")).children(line.theirs || "—"),
              Td(h, cn("text-right text-[11px]", lead?.tone ?? "text-muted-foreground")).children(lead?.word ?? "—"),
              forecast &&
                Td(h, cn("text-right", line.win != null ? chanceTone(line.win) : "text-muted-foreground")).children(
                  line.win != null ? percent(line.win) : "—",
                ),
            );
        }),
      ),
    ),
  );
}
