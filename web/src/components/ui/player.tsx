import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { GitCompareArrows, X } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { fade, list, listItem, portrait } from "@/lib/motion";
import { useLoadedImage } from "@/lib/useLoadedImage";
import { IconButton } from "@/components/ui/icon-button";
import { ExternalLink } from "@/components/ui/external-link";
import { QueryState } from "@/components/ui/state";
import { SlideOver } from "@/components/ui/dialog";
import { useShown } from "@/lib/screen";
import { api, type Competition, type League, type PlayerDetail, type Stat, type StatTable } from "@/lib/api";
import { keys } from "@/lib/queries";
import { MAX_COMPARED, useCompared } from "@/lib/compare";
import { toneText } from "@/lib/tone";
import { Badge } from "@/components/ui/badge";
import { Linked, StatList } from "@/components/ui/stat";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { LABEL, Label } from "@/components/ui/label";
import { Tabs } from "@/components/ui/tabs";

/**
 * The one figure this player is judged on, beside their name.
 *
 * A figure gets display type; the absence of one gets a sentence. Setting
 * "no projection" at that size renders a missing number as though it were
 * the number.
 */
function Headline({ detail }: { detail: PlayerDetail }) {
  if (!detail.headline) {
    return detail.headline_label ? (
      <p className="mt-1.5 text-[13px] leading-snug text-muted-foreground">{detail.headline_label}</p>
    ) : null;
  }
  return (
    <div className="mt-1.5 flex items-baseline gap-2">
      <span
        className={cn(
          "font-display text-[28px] font-semibold leading-none tracking-tight tabular-nums",
          detail.tone === "warning" && "text-warn",
        )}
      >
        {detail.headline}
      </span>
      {detail.headline_label && (
        <span className="min-w-0 font-mono text-[11px] leading-snug text-muted-foreground">
          {detail.headline_label}
        </span>
      )}
    </div>
  );
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
function TableOfStats({ table }: { table: StatTable }) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-border">
            <th className={cn(LABEL, "px-3 py-2 text-left")}>
              {/* The row labels need no heading; the seasons do. */}
            </th>
            {table.columns.map((column, i) => (
              <th
                key={column}
                className={cn(
                  "px-3 py-2 text-right font-mono text-[11px] font-semibold tabular-nums",
                  // The first column is the subject — the season in progress,
                  // or the points a game scored — so it reads as that rather
                  // than as another column.
                  i === 0 ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row) => (
            <tr key={row.label} className="border-b border-border/45 last:border-b-0">
              <th
                scope="row"
                className="whitespace-nowrap px-3 py-1.5 text-left text-[13px] font-normal text-muted-foreground"
              >
                {row.label}
              </th>
              {row.values.map((value, i) => (
                <td
                  key={`${row.label}-${i}`}
                  className={cn(
                    "whitespace-nowrap px-3 py-1.5 text-right font-mono text-[12.5px] tabular-nums",
                    // Nothing to report reads as absence, not as a figure.
                    value === table.absent && "text-muted-foreground/50",
                    toneText(row.tone),
                  )}
                >
                  {value}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Articles, each its headline linked and its date under it: prose, so not set as a figure. */
function Headlines({ stats }: { stats: Stat[] }) {
  return (
    <ul className="flex flex-col">
      {stats.map((stat) => (
        <li key={stat.url} className="border-b border-border/45 py-2 last:border-b-0">
          <Linked url={stat.url}>
            <span className="text-[13.5px] leading-snug">{stat.value}</span>
          </Linked>
          <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">{stat.label}</div>
        </li>
      ))}
    </ul>
  );
}

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
function TeamLine({ detail }: { detail: PlayerDetail }) {
  const crest = useLoadedImage(detail.team_logo_url);
  const club = detail.team_name || detail.team;
  if (!detail.position && !club) return null;
  return (
    <p className="mt-1 flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
      {detail.position && <span className="uppercase tracking-[0.06em]">{detail.position}</span>}
      {detail.position && club && <span aria-hidden>·</span>}
      {club && (
        <span className="flex min-w-0 items-center gap-1.5">
          {/* Only once loaded, like the portrait: an empty frame beside a
              club name, gone a moment later, reads as a broken app. */}
          {crest && (
            <m.img
              src={detail.team_logo_url}
              alt=""
              aria-hidden
              variants={fade}
              initial="hidden"
              animate="shown"
              className="size-4 shrink-0 object-contain"
            />
          )}
          <span className="truncate text-[12px]">{club}</span>
        </span>
      )}
    </p>
  );
}

/**
 * A player's face, where the platform has one.
 *
 * Shown only once it has loaded: the CDNs answer for most players and 404 for
 * the rest, and a photo frame that appears and is then taken away reads as
 * something breaking rather than as a photo that does not exist.
 */
function Portrait({ src }: { src: string }) {
  const loaded = useLoadedImage(src);
  return (
    <AnimatePresence initial={false}>
      {loaded && (
        <m.div
          key={src}
          variants={portrait}
          initial="hidden"
          animate="shown"
          className="shrink-0 overflow-hidden rounded-lg"
        >
          {/* Square and centre-cropped, which suits both: FPL ships a 500px
              square cut-out, Sleeper a 350x254 studio card whose only loss to
              a square is white margin. 96px is as large as the smaller of the
              two stays sharp at 2x, so this is the size the sources actually
              support rather than the size that would look boldest. */}
          <img src={src} alt="" aria-hidden className="size-24 max-w-none bg-photo object-cover" />
        </m.div>
      )}
    </AnimatePresence>
  );
}

/**
 * One player, opened from wherever their name appears.
 *
 * A panel rather than a page: you open it to settle a question about a row you
 * are already looking at, and closing it should put you back exactly there.
 * `playerId` of null is the closed state.
 */
function PlayerPanel({
  competition,
  league,
  playerId,
  onClose,
}: {
  competition: string;
  league: string;
  playerId: string | null;
  onClose: () => void;
}) {
  // Held so the panel still has someone to show on the way out. Reading
  // `playerId` directly would blank the contents for the length of the slide.
  const last = useRef("");
  if (playerId) last.current = playerId;
  const shown = playerId ?? last.current;

  const compared = useCompared(competition, league);
  const player = useQuery<PlayerDetail, Error>({
    queryKey: keys.player(competition, league, shown),
    queryFn: () => api.league(competition, league).player(shown),
    enabled: Boolean(shown),
  });
  // Each section in its tab: one with none of its own sits in the first. A
  // tab with nothing in it is not offered, and with one tab there is no bar.
  const [tab, setTab] = useState("");
  const detail = player.data;
  const tabOf = (section: { tab: string }) => section.tab || detail?.tabs[0] || "";
  const filled = detail ? detail.groups.filter((group) => group.stats.length > 0) : [];
  const present = (detail?.tabs ?? []).filter(
    (t) => filled.some((g) => tabOf(g) === t) || detail?.tables.some((x) => tabOf(x) === t),
  );
  const current = present.includes(tab) ? tab : present[0];
  const shownHere = (section: { tab: string }) => present.length <= 1 || tabOf(section) === current;
  const tables = (detail?.tables ?? []).filter(shownHere);
  const groups = filled.filter(shownHere);

  // On screen while open, so a question to the assistant docked over the
  // drawer is about him.
  useShown(
    playerId && player.data ? { subject: { kind: "player", key: player.data.player_id }, label: player.data.name } : null,
  );

  return (
    <SlideOver
      open={Boolean(playerId)}
      onClose={onClose}
      label={player.data?.name ?? "Player"}
      // Wide enough that a season table fits without scrolling inside
      // itself — three columns of "£14.0m → £14.7m" is what sets the
      // floor. Still capped, and still full width on a narrow screen.
      className="max-w-2xl border-l border-border"
    >
      {/* Everything that says who this is, pinned. On a long stat table
          the name and the one figure they are judged on are exactly what
          you stop being able to see, and they are what every row below is
          about. */}
      <div className="sticky top-0 z-10 border-b border-border bg-popover">
      <div className="flex items-start gap-4 px-5 py-4">
        {player.data && <Portrait src={player.data.image_url} />}

        <div className="min-w-0 flex-1 pt-0.5">
          {player.data ? (
            <>
              <h2 className="font-display text-[22px] font-semibold leading-tight tracking-tight">
                {player.data.name}
              </h2>
              <TeamLine detail={player.data} />
              {player.data.owner && (
                <Badge variant="muted" appearance="label" className="mt-1.5">
                  {player.data.owner}
                </Badge>
              )}
              <Headline detail={player.data} />
              {player.data.note && (
                <Badge variant="warn" appearance="status" className="mt-2">
                  {player.data.note}
                </Badge>
              )}
            </>
          ) : (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-6 w-44" />
              <Skeleton className="h-3 w-24" />
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center">
          {player.data && (
            <IconButton
              label={
                compared.has(shown)
                  ? "Remove from compare"
                  : compared.full
                    ? `Compare holds ${MAX_COMPARED}`
                    : "Add to compare"
              }
              icon={<GitCompareArrows />}
              aria-pressed={compared.has(shown)}
              disabled={!compared.has(shown) && compared.full}
              onClick={() => (compared.has(shown) ? compared.remove(shown) : compared.add(shown))}
            />
          )}
          {player.data?.url && (
            <ExternalLink href={player.data.url} label={`Open ${player.data.name} on the platform`} />
          )}
          <IconButton label="Close" side="left" icon={<X />} onClick={onClose} />
        </div>
      </div>
      {present.length > 1 && (
        <Tabs
          tabs={present.map((t) => ({ id: t, label: t }))}
          current={current}
          onPick={setTab}
          className="px-5 pb-2"
        />
      )}
      </div>

      <QueryState query={player} lines={4} />

      {player.data && (
        // Room at the foot for the assistant's button, which sits over the drawer.
        <m.div
          key={`${player.data.player_id}-${current}`}
          variants={list}
          initial="hidden"
          animate="shown"
          className="flex flex-col gap-5 px-5 pt-4 pb-20"
        >
          {tables.map((table) => (
            <m.section key={table.title} variants={listItem}>
              <Label as="h3" className="mb-1.5 block">
                {table.title}
              </Label>
              <TableOfStats table={table} />
            </m.section>
          ))}

          {/* A group with nothing in it is a heading that says nothing —
              a kicker has no passing line, and "Projected line" over empty
              space reads as a figure that failed to arrive. */}
          {groups.map((group) => (
            <m.section key={group.title} variants={listItem}>
              <Label as="h3" className="mb-1 block">
                {group.title}
              </Label>
              {group.stats.every((stat) => stat.url) ? (
                <Headlines stats={group.stats} />
              ) : (
                <StatList stats={group.stats} />
              )}
            </m.section>
          ))}
        </m.div>
      )}

    </SlideOver>
  );
}

/**
 * The drawer, and the one piece of state that opens it.
 *
 * Every table in the app opens a player, and each panel was wiring the same
 * three things by hand: a nullable id, the callback that sets it, and a
 * `<PlayerPanel>` whose four props were identical everywhere. Forgetting the
 * `onClose` half leaves a drawer that opens and never shuts, which is exactly
 * the kind of mistake a repeated block invites.
 *
 * Returns the opener to hand to a table's `onOpen`, and the drawer to render.
 */
export function usePlayerDrawer(competition: Competition, league: League) {
  const [playerId, setPlayerId] = useState<string | null>(null);
  return {
    openPlayer: setPlayerId,
    drawer: (
      <PlayerPanel
        competition={competition.key}
        league={league.league_id}
        playerId={playerId}
        onClose={() => setPlayerId(null)}
      />
    ),
  };
}
