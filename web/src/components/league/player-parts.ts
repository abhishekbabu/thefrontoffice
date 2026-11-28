/**
 * What a player's drawer is made of, and what a comparison borrows from it:
 * his facts, his tables and headlines, his club, his face and his chips.
 */
import { Subscription, UiSchema } from "@effect/ui";
import { Html, HtmlImages } from "@effect/ui/html";
import { Schema, Stream } from "effect";
import { Badge } from "@/components/ui/badge";
import { Meta } from "@/components/ui/label";
import { Hint } from "@/components/ui/overlays/hint";
import { Linked } from "@/components/ui/stat";
import { Table, Td, Th } from "@/components/ui/table";
import { toneText } from "@/lib/tone";
import type { PlayerDetail, Stat, StatTable } from "@/lib/types";
import { cn } from "@/lib/utils";

/** What labels his ranking at his position, wherever it is shown. */
const RANK = "Pos rank";

/** What labels whose roster he is on, wherever it is shown. */
const OWNER = "Owner";

/**
 * His key facts under his name, as the matchup page sets its own: each its
 * label over its value. The figure he is judged on leads, then his rank at
 * his position, then whose roster he is on — whichever of the three he has.
 *
 * The figure is never tinted by his status: the status badge above says that
 * in words, and a gold number read as a different number.
 */
export function facts(detail: PlayerDetail): Stat[] {
  const fact = (label: string, value: string): Stat => ({
    label,
    value,
    tone: "neutral",
    url: "",
    better: null,
    hint: "",
  });

  return [
    ...(detail.headline ? [fact(detail.headline_label || "Value", detail.headline)] : []),
    ...(detail.rank ? [fact(RANK, detail.rank)] : []),
    ...(detail.owner ? [fact(OWNER, detail.owner)] : []),
  ];
}

/**
 * Figures on a grid, read across: the same measures over several seasons, or
 * a season's games over the box score.
 *
 * The figures are the point, so they are right-aligned and tabular and the
 * column headings sit above them; the label column is the only thing on the
 * left. Scrolls inside itself rather than widening the drawer — a
 * quarterback's game log is the widest, and a phone is narrower still.
 */
export function TableOfStats<M>(h: Html.H<M>, table: StatTable) {
  // The shared table, boxed and a step denser: the drawer is narrower than a page.
  return h.div.class("overflow-hidden rounded-md border border-border").children(
    Table(h).children(
      h.thead.children(
        h.tr.children(
          // The row labels need no heading; the seasons do.
          Th(h, "px-3"),
          table.columns.map((column, i) =>
            Th(
              h,
              cn(
                "px-3 text-right tabular-nums",
                // The first column is the subject — the season in progress,
                // or the points a game scored — so it reads as that rather
                // than as another column.
                i === 0 && "text-foreground",
              ),
            )
              .key(column)
              .children(column),
          ),
        ),
      ),
      h.tbody.children(
        table.rows.map((row) =>
          h.tr
            .key(row.label)
            .class("[&:last-child>td]:border-b-0")
            .children(
              Td(h, "whitespace-nowrap px-3 py-1.5 text-muted-foreground").children(row.label),
              row.values.map((value, i) =>
                Td(
                  h,
                  cn(
                    "whitespace-nowrap px-3 py-1.5 text-right font-mono text-[12.5px]",
                    // Nothing to report reads as absence, not as a figure.
                    value === table.absent && "text-muted-foreground/50",
                    toneText(row.tone),
                  ),
                )
                  .key(`${row.label}-${i}`)
                  .children(value),
              ),
            ),
        ),
      ),
    ),
  );
}

/** Articles, each its headline linked and its date under it: prose, so not set as a figure. */
export function Headlines<M>(h: Html.H<M>, stats: Stat[]) {
  return h.ul.class("flex flex-col").children(
    stats.map((stat) =>
      h.li
        .key(stat.url)
        .class("border-b border-border/45 py-2 last:border-b-0")
        .children(
          Linked(h, { url: stat.url, children: [h.span.class("text-[13.5px] leading-snug").children(stat.value)] }),
          Meta(h, { as: "div", class: "mt-0.5" }).children(stat.label),
        ),
    ),
  );
}

const LoadedImageMessage = UiSchema.TaggedEnum({ Loaded: { src: Schema.String }, Failed: {} });

/**
 * An image the platforms may not have, drawn only once it has loaded.
 *
 * A CDN answers for most players and 404s for the rest, and an `<img>` put on
 * the page to find out shows its empty frame until the failure comes back.
 * Asking first, off-screen, means a missing image is never drawn at all,
 * rather than drawn and then taken away. Compared against the `src` that
 * loaded rather than reset on change, so a different player's photo is never
 * shown under the next one's name. `frame` is a box drawn around it, if any.
 */
const LoadedImage = Html.component({
  name: "LoadedImage",
  props: Schema.Struct({ src: Schema.String, class: Schema.String, frame: Schema.optional(Schema.String) }),
  model: Schema.Struct({ loaded: Schema.NullOr(Schema.String) }),
  message: LoadedImageMessage,
  restore: false,
}).make({
  init: () => ({ loaded: null }),
  update: {
    Loaded: ($, { src }) => $.evolve({ loaded: src }),
    Failed: ($) => $.model,
  },
  subscriptions: ($) =>
    $.props.src === "" || $.model.loaded === $.props.src
      ? []
      : [
          Subscription.make("image", $.props.src, (src) =>
            Stream.fromEffect(HtmlImages.Images.use((images) => images.load({ src }))).pipe(
              Stream.map((status) =>
                status === "loaded" ? LoadedImageMessage.Loaded({ src }) : LoadedImageMessage.Failed(),
              ),
            ),
          ),
        ],
  view: (h, model) => {
    const { src, frame } = h.props;

    // A view draws something: until it loads, an empty box that takes no room.
    if (src === "" || model.loaded !== src) return h.span.class("contents");

    const image = h.img.key(src).attrs({ src, alt: "", "aria-hidden": "true", class: h.props.class });

    return frame === undefined ? image : h.div.key(src).class(frame).children(image);
  },
});

/**
 * Position and club, with the crest where there is one.
 *
 * The club in full rather than the three letters a table shows: there is room
 * here, and "Detroit Lions" is what somebody would have said out loud. Kept on
 * one line with the position so it reads as one fact about the player rather
 * than a second heading.
 *
 * Not uppercased, unlike the rest of this mono line — a club name in caps
 * reads as shouting, and the abbreviation it replaces was only in caps
 * because that is how abbreviations come.
 */
export function TeamLine<M>(h: Html.H<M>, detail: PlayerDetail) {
  const club = detail.team_name || detail.team;

  if (!detail.position && !club) return null;

  return Meta(h, { as: "p", class: "mt-1 flex items-center gap-1.5" }).children(
    detail.position && h.span.class("uppercase tracking-[0.06em]").children(detail.position),
    detail.position && club && h.span.attr("aria-hidden", "true").children("·"),
    club &&
      h.span.class("flex min-w-0 items-center gap-1.5").children(
        // Only once loaded, like the portrait: an empty frame beside a club
        // name, gone a moment later, reads as a broken app.
        LoadedImage(h, {
          key: "crest",
          props: { src: detail.team_logo_url, class: "size-4 shrink-0 animate-fade object-contain" },
        }),
        h.span.class("truncate text-[12px]").children(club),
      ),
  );
}

/**
 * Whose roster he is on, and where he ranks at his position, as compact chips
 * for a comparison's narrow column; each names what it is on hover and focus.
 */
export function Chips<M>(h: Html.H<M>, { detail, class: extra }: { detail: PlayerDetail; class?: string | undefined }) {
  if (!detail.owner && !detail.rank) return null;

  return h.div.attr("class", cn("flex flex-wrap items-center gap-1.5", extra)).children(
    detail.rank &&
      Hint(h, {
        key: `rank-${detail.player_id}`,
        props: { label: RANK, name: `${RANK} ${detail.rank}` },
        slots: { content: Badge(h, { variant: "info", appearance: "label", class: "tabular-nums" }).children(detail.rank) },
      }),
    // Truncated rather than overflowing: a manager's team name is as long as he likes.
    detail.owner &&
      Hint(h, {
        key: `owner-${detail.player_id}`,
        props: { label: OWNER, name: `${OWNER} ${detail.owner}`, class: "min-w-0 max-w-full" },
        slots: {
          content: Badge(h, { variant: "muted", appearance: "label", class: "block max-w-full truncate leading-5" }).children(
            detail.owner,
          ),
        },
      }),
  );
}

/**
 * A player's face, where the platform has one.
 *
 * Shown only once it has loaded: the CDNs answer for most players and 404 for
 * the rest, and a photo frame that appears and is then taken away reads as
 * something breaking rather than as a photo that does not exist.
 *
 * Square and centre-cropped, which suits both: FPL ships a 500px square
 * cut-out, Sleeper a 350x254 studio card whose only loss to a square is white
 * margin. 64px: beside a name and one meta line, not towering over the facts
 * under them, and well inside the 96px the smaller source stays sharp at 2x.
 */
export function Portrait<M>(h: Html.H<M>, { key, src, class: extra }: { key: string; src: string; class?: string | undefined }) {
  return LoadedImage(h, {
    key,
    props: {
      src,
      frame: "shrink-0 animate-portrait overflow-hidden rounded-lg",
      class: cn("size-16 max-w-none bg-photo object-cover", extra),
    },
  });
}
