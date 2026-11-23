import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useKept } from "@/lib/useKept";
import { GitCompareArrows, X } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { fade, list, listItem, portrait } from "@/lib/motion";
import { useLoadedImage } from "@/lib/useLoadedImage";
import { IconButton } from "@/components/ui/icon-button";
import { ExternalLink } from "@/components/ui/external-link";
import { Empty, QueryState } from "@/components/ui/state";
import { BackLink, SlideOver, type Back } from "@/components/ui/dialog";
import { useShown } from "@/lib/screen";
import { api, type ActivityRow, type PlayerDetail, type Stat, type StatTable } from "@/lib/api";
import { keys } from "@/lib/queries";
import { MAX_COMPARED, useCompared } from "@/lib/compare";
import { toneText } from "@/lib/tone";
import { Badge } from "@/components/ui/badge";
import { Linked, StatCells, StatList } from "@/components/ui/stat";
import { Hint } from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { Label, Meta } from "@/components/ui/label";
import { Table, Td, Th } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { MoveDrawer, MoveRow, backTo } from "@/components/league/move";
import { ListCard } from "@/components/ui/list";

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
function facts(detail: PlayerDetail): Stat[] {
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
function TableOfStats({ table }: { table: StatTable }) {
  return (
    // The shared table, boxed and a step denser: the drawer is narrower than a page.
    <div className="overflow-hidden rounded-md border border-border">
      <Table>
        <thead>
          <tr>
            {/* The row labels need no heading; the seasons do. */}
            <Th className="px-3" />
            {table.columns.map((column, i) => (
              <Th
                key={column}
                className={cn(
                  "px-3 text-right tabular-nums",
                  // The first column is the subject — the season in progress,
                  // or the points a game scored — so it reads as that rather
                  // than as another column.
                  i === 0 && "text-foreground",
                )}
              >
                {column}
              </Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row) => (
            <tr key={row.label} className="[&:last-child>td]:border-b-0">
              <Td className="whitespace-nowrap px-3 py-1.5 text-muted-foreground">{row.label}</Td>
              {row.values.map((value, i) => (
                <Td
                  key={`${row.label}-${i}`}
                  className={cn(
                    "whitespace-nowrap px-3 py-1.5 text-right font-mono text-[12.5px]",
                    // Nothing to report reads as absence, not as a figure.
                    value === table.absent && "text-muted-foreground/50",
                    toneText(row.tone),
                  )}
                >
                  {value}
                </Td>
              ))}
            </tr>
          ))}
        </tbody>
      </Table>
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
          <Meta as="div" className="mt-0.5">{stat.label}</Meta>
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
    <Meta as="p" className="mt-1 flex items-center gap-1.5">
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
    </Meta>
  );
}

/**
 * Whose roster he is on, and where he ranks at his position, as compact chips
 * for a comparison's narrow column; each names what it is on hover and focus.
 */
export function Chips({ detail, className }: { detail: PlayerDetail; className?: string }) {
  if (!detail.owner && !detail.rank) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {detail.rank && (
        <Hint label={RANK} name={`${RANK} ${detail.rank}`}>
          <Badge variant="info" appearance="label" className="tabular-nums">
            {detail.rank}
          </Badge>
        </Hint>
      )}
      {/* Truncated rather than overflowing: a manager's team name is as long as he likes. */}
      {detail.owner && (
        <Hint label={OWNER} name={`${OWNER} ${detail.owner}`} className="min-w-0 max-w-full">
          <Badge variant="muted" appearance="label" className="block max-w-full truncate leading-5">
            {detail.owner}
          </Badge>
        </Hint>
      )}
    </div>
  );
}

/**
 * A player's face, where the platform has one.
 *
 * Shown only once it has loaded: the CDNs answer for most players and 404 for
 * the rest, and a photo frame that appears and is then taken away reads as
 * something breaking rather than as a photo that does not exist.
 */
export function Portrait({ src, className }: { src: string; className?: string }) {
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
              a square is white margin. 64px: beside a name and one meta line,
              not towering over the facts under them, and well inside the 96px
              the smaller source stays sharp at 2x. */}
          <img src={src} alt="" aria-hidden className={cn("size-16 max-w-none bg-photo object-cover", className)} />
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
export function PlayerPanel({
  competition,
  league,
  playerId,
  back,
  onClose,
  onPick,
  onCompare,
}: {
  competition: string;
  league: string;
  playerId: string | null;
  back?: Back;
  onClose: () => void;
  /** Open another player in this drawer: one picked from a move on his history. */
  onPick: (id: string, back?: Back) => void;
  /** Compare the players of a move on his history, in a drawer of their own. */
  onCompare: (ids: string[], back: Back) => void;
}) {
  // Held so the panel still has someone to show on the way out. Reading
  // `playerId` directly would blank the contents for the length of the slide.
  const shown = useKept(playerId) ?? "";

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
  const movesTab = detail ? detail.moves_tab || detail.tabs[0] || "" : "";
  // A deferred tab is offered before anyone knows what it holds: it is read
  // only once opened, since each costs a request the first tab does not.
  const deferred = detail?.deferred ?? [];
  const present = (detail?.tabs ?? []).filter(
    (t) =>
      deferred.includes(t) ||
      filled.some((g) => tabOf(g) === t) ||
      detail?.tables.some((x) => tabOf(x) === t) ||
      (t === movesTab && (detail?.moves.length ?? 0) > 0),
  );
  const current = present.includes(tab) ? tab : present[0];
  const opened = current && deferred.includes(current) ? current : "";
  const part = useQuery<PlayerDetail, Error>({
    queryKey: keys.playerTab(competition, league, shown, opened),
    queryFn: () => api.league(competition, league).playerTab(shown, opened),
    enabled: Boolean(shown && opened),
  });
  const source = opened ? part.data : detail;
  const shownHere = (section: { tab: string }) => present.length <= 1 || tabOf(section) === current;
  const tables = (source?.tables ?? []).filter(shownHere);
  const groups = (source?.groups ?? []).filter((group) => group.stats.length > 0).filter(shownHere);
  const moves = source && shownHere({ tab: movesTab }) ? source.moves : [];
  const nothing = Boolean(opened && part.data && !tables.length && !groups.length && !moves.length);
  const [move, setMove] = useState<ActivityRow | null>(null);
  const shownFacts = detail ? facts(detail) : [];

  // On screen while open, so a question to the assistant docked over the
  // drawer is about him.
  useShown(
    playerId && player.data ? { subject: { kind: "player", key: player.data.player_id }, label: player.data.name } : null,
  );

  return (
    <>
    <SlideOver
      // Out of the way while one of his moves is open: one drawer at a time.
      open={Boolean(playerId) && move === null}
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
      {back && (
        <div className="px-5 pt-3">
          <BackLink back={back} />
        </div>
      )}
      <div className="flex items-start gap-4 px-5 py-3.5">
        {player.data && <Portrait src={player.data.image_url} />}

        <div className="min-w-0 flex-1">
          {player.data ? (
            <>
              <h2 className="font-display text-[21px] font-semibold leading-tight tracking-tight">
                {player.data.name}
              </h2>
              <TeamLine detail={player.data} />
              {player.data.note && (
                // Wraps rather than running off the drawer: FPL's news is a sentence.
                <Badge
                  variant="warn"
                  appearance="status"
                  className="mt-1.5 h-auto min-h-5 max-w-full items-start whitespace-normal rounded-md py-[3px] leading-snug before:mt-[3.5px]"
                >
                  {player.data.note}
                </Badge>
              )}
              {/* No figure to lead with: why not, as a sentence rather than a blank cell. */}
              {!player.data.headline && player.data.headline_label && (
                <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">
                  {player.data.headline_label}
                </p>
              )}
            </>
          ) : (
            <div className="flex flex-col gap-2 pt-0.5">
              <Skeleton className="h-5 w-44" />
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
      {shownFacts.length > 0 && <StatCells stats={shownFacts} className="border-t border-border" />}
      {present.length > 1 && (
        <Tabs
          tabs={present.map((t) => ({ id: t, label: t }))}
          current={current}
          onPick={setTab}
          className={cn("px-5 pb-2", shownFacts.length > 0 && "border-t border-border pt-2")}
        />
      )}
      </div>

      <QueryState query={player} lines={4} />
      {opened && <QueryState query={part} lines={4} className="mx-5 mt-4" />}
      {nothing && <Empty title={`No ${opened.toLowerCase()} on record.`} />}

      {player.data && (
        // Room at the foot for the assistant's button, which sits over the drawer.
        <m.div
          key={`${player.data.player_id}-${current}`}
          variants={list}
          initial="hidden"
          animate="shown"
          className="flex flex-col gap-5 px-5 pt-4 pb-20"
        >
          {/* Now before then: his form, status and outlook, and only after
              them the seasons behind him. A group with nothing in it is a
              heading that says nothing — a kicker has no passing line, and
              "Projected line" over empty space reads as a figure that failed
              to arrive. */}
          {groups.map((group) => (
            <m.section key={group.title} variants={listItem}>
              <Label as="h3" className="mb-1.5 block">
                {group.title}
              </Label>
              {group.stats.every((stat) => stat.url) ? (
                <Headlines stats={group.stats} />
              ) : (
                <StatList stats={group.stats} />
              )}
            </m.section>
          ))}

          {tables.map((table) => (
            <m.section key={table.title} variants={listItem}>
              <Label as="h3" className="mb-1.5 block">
                {table.title}
              </Label>
              <TableOfStats table={table} />
            </m.section>
          ))}
          {moves.length > 0 && (
            <m.section variants={listItem}>
              {/* The league's own rows: one opens the move as Activity does. */}
              <ListCard title="Moves" count={`${moves.length}`}>
                {moves.map((row, i) => (
                  <MoveRow key={`${row.when}-${i}`} move={row} onOpen={setMove} />
                ))}
              </ListCard>
            </m.section>
          )}
        </m.div>
      )}

    </SlideOver>
    <MoveDrawer
      move={move}
      back={player.data ? { label: player.data.name, onBack: () => setMove(null) } : undefined}
      onClose={() => {
        setMove(null);
        onClose();
      }}
      onOpenPlayer={(id) => {
        const from = move!;
        setMove(null);
        onPick(id, backTo(from, () => setMove(from)));
      }}
      onCompare={(ids) => {
        const from = move!;
        setMove(null);
        onCompare(ids, backTo(from, () => setMove(from)));
      }}
    />
    </>
  );
}
