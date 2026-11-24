import type { CategoryLine } from "@/lib/types";
import { percent } from "@/lib/format";
import { Card, CardHeader } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Table, Td, Th } from "@/components/ui/table";
import { cn } from "@/lib/utils";

const LEAD: Record<
  NonNullable<CategoryLine["lead"]>,
  { word: string; tone: string }
> = {
  mine: { word: "You", tone: "text-ok" },
  theirs: { word: "Them", tone: "text-warn" },
  even: { word: "Level", tone: "text-muted-foreground" },
};

/** A chance of winning a category, toned as the header's win chance is; the figure itself carries it. */
function chanceTone(win: number): string {
  return win >= 0.6
    ? "text-ok"
    : win <= 0.4
      ? "text-warn"
      : "text-muted-foreground";
}

/**
 * A category week, read across: each category, both figures, who leads it,
 * and — where the week is forecast — your chance of winning it.
 *
 * The leader is said in words as well as weight and color, since a category
 * week is won by the count of those words. `title` names what is totalled
 * where a page shows more than one: the week, and a day of it.
 */
export function Categories({ lines, title = "Categories" }: { lines: CategoryLine[]; title?: string }) {
  const forecast = lines.some((line) => line.win != null);

  return (
    <Card>
      <CardHeader>
        <span>{title}</span>
        <span>{lines.length} scored</span>
      </CardHeader>
      <Table>
        <thead>
          <tr>
            <Th className="w-16">Cat</Th>
            <Th className="w-20 text-right">You</Th>
            {/* Not the opponent's name, which truncates: the lineup cards below name both teams. */}
            <Th className="w-20 text-right">Them</Th>
            <Th className="text-right">Leads</Th>
            {forecast && <Th className="w-12 text-right">Win</Th>}
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const lead = line.lead ? LEAD[line.lead] : null;

            return (
              <tr
                key={line.name}
                className="font-mono text-[12.5px] [&:last-child>td]:border-b-0"
              >
                <Td>
                  <Label>{line.name}</Label>
                </Td>
                <Td
                  className={cn(
                    "text-right",
                    line.lead === "mine" && "font-semibold",
                  )}
                >
                  {line.mine || "—"}
                </Td>
                <Td
                  className={cn(
                    "text-right",
                    line.lead === "theirs" && "font-semibold",
                  )}
                >
                  {line.theirs || "—"}
                </Td>
                <Td
                  className={cn(
                    "text-right text-[11px]",
                    lead?.tone ?? "text-muted-foreground",
                  )}
                >
                  {lead?.word ?? "—"}
                </Td>
                {forecast && (
                  <Td
                    className={cn(
                      "text-right",
                      line.win != null
                        ? chanceTone(line.win)
                        : "text-muted-foreground",
                    )}
                  >
                    {line.win != null ? percent(line.win) : "—"}
                  </Td>
                )}
              </tr>
            );
          })}
        </tbody>
      </Table>
    </Card>
  );
}
