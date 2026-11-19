import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Save, Undo2 } from "lucide-react";
import { api, type CaptureStatus, type Setting, type SettingsGroup } from "@/lib/api";
import { bookmarklet } from "@/lib/bookmarklet";
import { moment } from "@/lib/format";
import { keys } from "@/lib/queries";
import type { Variant } from "@/lib/tone";
import { useTheme } from "@/lib/useTheme";
import { PALETTES } from "@/themes/registry";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Disclosure } from "@/components/ui/disclosure";
import { ErrorNote } from "@/components/ui/error-note";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Label, META } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import { QueryState } from "@/components/ui/state";
import { ToggleChip, ToggleGroup } from "@/components/ui/toggle";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * The page's parts, broadest first: the accounts read, the models that judge
 * them, how the app looks, and what is rarely touched. Typed by the server's
 * own sections, so a section it adds is a type error here rather than a group
 * that never renders.
 */
const SECTIONS: Record<SettingsGroup["section"], string> = {
  platforms: "Platforms",
  ai: "AI",
  advanced: "Advanced",
};

type Drafts = Record<string, string>;

export function SettingsPanel({ onBack }: { onBack: () => void }) {
  const queryClient = useQueryClient();
  // Grouped by the server, by what each key unlocks: a key on its own means
  // nothing, and "this is the one that turns on football" is what a person is
  // actually looking for.
  const settings = useQuery<SettingsGroup[], Error>({ queryKey: keys.settings, queryFn: api.settings });
  const [drafts, setDrafts] = useState<Drafts>({});

  const save = useMutation<SettingsGroup[], Error, Drafts>({
    mutationFn: api.saveSettings,
    onSuccess: () => {
      setDrafts({});
      // Everything downstream depends on configuration: which sports appear,
      // which leagues they hold. Drop it all rather than guess what moved.
      void queryClient.invalidateQueries();
    },
  });

  const pending = Object.keys(drafts).length;
  const edit = (setting: Setting) => (value: string) =>
    setDrafts((current) => {
      const next = { ...current };
      // Typing back to the stored value is not a change.
      if (value === (setting.secret ? "" : setting.value)) delete next[setting.key];
      else next[setting.key] = value;
      return next;
    });
  const section = (id: SettingsGroup["section"]) =>
    (settings.data ?? [])
      .filter((group) => group.section === id)
      .map((group) => <GroupCard key={group.title} group={group} drafts={drafts} onEdit={edit} />);

  return (
    <>
      <PageHeader
        title="Settings"
        meta="Saved to .env, applied at once"
        leading={<IconButton label="Back" icon={<ArrowLeft />} onClick={onBack} />}
      >
        <div className="flex items-center gap-2">
          {/* Said in words beside the control, so whether anything is waiting
              to be written — or just was — reads without hovering. */}
          <span role="status" className={META}>
            {save.isPending ? "Saving…" : pending ? `${pending} unsaved` : save.isSuccess ? "Saved" : ""}
          </span>
          {pending > 0 && (
            <IconButton
              label="Discard changes"
              icon={<Undo2 />}
              disabled={save.isPending}
              onClick={() => setDrafts({})}
            />
          )}
          <IconButton
            label={
              save.isPending
                ? "Saving"
                : pending
                  ? `Save ${pending} change${pending === 1 ? "" : "s"}`
                  : "Nothing to save"
            }
            variant={pending ? "primary" : "ghost"}
            icon={pending ? <Save /> : <Check />}
            disabled={!pending || save.isPending}
            onClick={() => save.mutate(drafts)}
          />
        </div>
      </PageHeader>

      <QueryState query={settings} lines={6} />
      {save.isError && <ErrorNote error={save.error} />}

      {settings.data && (
        <div className="flex flex-col gap-8 p-5">
          <Section title={SECTIONS.platforms}>{section("platforms")}</Section>
          <Section title={SECTIONS.ai}>{section("ai")}</Section>
          <Section title="Appearance">
            <Appearance />
          </Section>
          <Section title={SECTIONS.advanced}>{section("advanced")}</Section>
        </div>
      )}
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <Label as="h2">{title}</Label>
      {children}
    </section>
  );
}

/**
 * One group's settings in a card: what they unlock, then a row each. A
 * platform's status sits in the header and its how-to under the rows, beside
 * the settings they are about rather than in a card of their own.
 *
 * Where the group has a switch — how Yahoo is read — only the way chosen is
 * spelled out: its note, its fields, its how-to. The other ways' fields fold
 * under "Other methods", kept rather than dropped so a value set there is
 * still in reach. Chosen means as pressed, saved or not, so pressing a way
 * shows at once what it needs.
 */
function GroupCard({
  group,
  drafts,
  onEdit,
}: {
  group: SettingsGroup;
  drafts: Drafts;
  onEdit: (setting: Setting) => (value: string) => void;
}) {
  const yahoo = group.platform === "yahoo";
  const status = useQuery<CaptureStatus, Error>({
    queryKey: keys.capture("yahoo"),
    queryFn: () => api.captureStatus("yahoo"),
    enabled: yahoo,
  });
  const switched = group.settings.find((setting) => setting.key === group.switch);
  const chosen = switched ? (drafts[switched.key] ?? switched.effective) : "";
  const needed = (setting: Setting) => !setting.mode || setting.mode === chosen;
  const others = group.settings.filter((setting) => !needed(setting));
  const note = [group.note, group.modes[chosen]].filter(Boolean);
  const row = (setting: Setting) => (
    <Row key={setting.key} setting={setting} draft={drafts[setting.key]} onChange={onEdit(setting)} />
  );
  return (
    <Card role="group" aria-label={group.title}>
      <CardHeader>
        <span>{group.title}</span>
        {yahoo && status.data && <YahooState status={status.data} />}
      </CardHeader>
      {note.map((text) => (
        <p key={text} className="max-w-[70ch] px-4 pt-3 text-[13px] leading-relaxed text-muted-foreground">
          {text}
        </p>
      ))}
      <div className="flex flex-col px-4 py-1">{group.settings.filter(needed).map(row)}</div>
      {yahoo && status.isError && <ErrorNote error={status.error} className="mx-4 mt-0 mb-4" />}
      {yahoo && status.data && <YahooHowTo status={status.data} mode={chosen || readBy(status.data)} />}
      {others.length > 0 && (
        <Disclosure summary="Other methods">
          <div className="flex flex-col px-4 pb-2">{others.map(row)}</div>
        </Disclosure>
      )}
    </Card>
  );
}

/** How Yahoo is read as the server last saw it, for a page that has no switch to ask. */
function readBy(status: CaptureStatus): string {
  return status.session ? "session" : status.active ? "browser" : "oauth";
}

/**
 * How reading Yahoo is going, said in the header's corner: in words, with the tone only to find it.
 *
 * Leads with how many leagues were read, once any were — "5 leagues · last
 * fetched 02:07 AM" — rather than listing them on a line of their own.
 */
export function yahooState(status: CaptureStatus): { text: string; variant: Variant } {
  const { session, leagues } = status;
  const read = (when: string) =>
    leagues.length ? `${leagues.length} league${leagues.length === 1 ? "" : "s"} · ${when}` : capitalized(when);
  if (session) {
    if (session.expired) return { text: "Session expired", variant: "warn" };
    return session.fetched_at
      ? { text: read(`last fetched ${moment(session.fetched_at)}`), variant: "ok" }
      : { text: "Not fetched yet", variant: "muted" };
  }
  if (status.active) {
    return status.synced_at
      ? { text: read(`last synced ${moment(status.synced_at)}`), variant: "ok" }
      : { text: "Never synced", variant: "muted" };
  }
  return { text: "Reading OAuth", variant: "muted" };
}

const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

function YahooState({ status }: { status: CaptureStatus }) {
  const { text, variant } = yahooState(status);
  return (
    <Badge variant={variant} appearance="status" className="normal-case tracking-normal">
      {text}
    </Badge>
  );
}

/**
 * How to set up the way Yahoo is read, for the way chosen only: the session
 * cookie to paste, or the bookmark to run on a Yahoo page. OAuth needs no
 * steps beyond its note. Open while it is the source in use and not yet working.
 *
 * The bookmark's link is set on the element rather than rendered: React refuses a
 * `javascript:` href, which is the only kind a bookmark can run. Clicking it
 * here does nothing — it runs on Yahoo's page, after being dragged away.
 */
function YahooHowTo({ status, mode }: { status: CaptureStatus; mode: string }) {
  const link = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    link.current?.setAttribute("href", bookmarklet(window.location.origin));
  }, []);
  const { session } = status;
  const steps = "max-w-[70ch] list-decimal pl-5";
  return (
    <>
      <Disclosure
        summary="Session cookie"
        open={Boolean(session && (session.expired || !session.fetched_at))}
        className={cn(mode !== "session" && "hidden")}
      >
        <div className="flex flex-col gap-2 px-4 pb-4 text-[13px] leading-relaxed text-muted-foreground">
          {session?.expired && <p className="text-foreground">Yahoo refused the cookie. Paste a fresh one.</p>}
          <ol className={steps}>
            <li>On a Yahoo Fantasy page in Chrome or Dia, open DevTools → Network.</li>
            <li>
              Pick a request to <code className="font-mono text-[12px]">pub-api-ro.fantasysports.yahoo.com</code> →
              Request Headers → cookie, and copy the value.
            </li>
            <li>Paste it into YAHOO_SESSION_COOKIE above.</li>
          </ol>
        </div>
      </Disclosure>
      <Disclosure
        summary="Sync bookmark"
        open={status.active && !status.synced_at}
        className={cn(mode !== "browser" && "hidden")}
      >
        <div className="flex flex-col items-start gap-2 px-4 pb-4 text-[13px] leading-relaxed text-muted-foreground">
          <a
            ref={link}
            draggable
            onClick={(e) => e.preventDefault()}
            className={buttonVariants({ variant: "secondary", size: "sm" })}
          >
            Sync Yahoo
          </a>
          <ol className={steps}>
            <li>Drag the button to your bookmarks bar.</li>
            <li>Open any Yahoo Fantasy Basketball page and click the bookmark.</li>
            <li>Allow local network access once when Chrome asks.</li>
          </ol>
        </div>
      </Disclosure>
    </>
  );
}

/**
 * Palette lives in this browser, not in `.env`.
 *
 * Said plainly because everything else on this page is configuration shared by
 * every front end — someone who sets a palette here and opens the app elsewhere
 * should know why it did not follow them.
 */
function Appearance() {
  const { palette, setPalette } = useTheme();
  return (
    <Card>
      <CardHeader>
        <span>Palette</span>
        <span className="font-normal normal-case tracking-normal">This browser only</span>
      </CardHeader>
      <div role="group" aria-label="Palette" className="flex flex-wrap gap-2 p-4">
        <ToggleGroup>
          {PALETTES.map((p) => (
            <ToggleChip
              key={p.id}
              pressed={p.id === palette}
              onClick={() => setPalette(p.id)}
              className="h-auto gap-2.5 py-2 text-left"
            >
              <span className="size-4 shrink-0 rounded-full border border-border" style={{ background: p.swatch }} />
              <span>
                <span className="block text-[13px] font-medium leading-tight">{p.label}</span>
                <span className="block font-mono text-[10px] opacity-70">{p.hint}</span>
              </span>
            </ToggleChip>
          ))}
        </ToggleGroup>
      </div>
    </Card>
  );
}

function Row({
  setting,
  draft,
  onChange,
}: {
  setting: Setting;
  draft: string | undefined;
  onChange: (value: string) => void;
}) {
  // A row of chips is several controls, so it cannot sit in a `<label>`: a
  // click on the key would press whichever chip came first.
  const Wrapper = setting.kind === "boolean" || setting.kind === "choice" ? "div" : "label";
  return (
    <Wrapper className="grid grid-cols-1 items-center gap-1.5 border-b border-border/45 py-2.5 last:border-b-0 sm:grid-cols-[16rem_minmax(0,42rem)] sm:gap-4">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <code className="break-all font-mono text-[12px] text-foreground">{setting.key}</code>
        {draft !== undefined && (
          <Badge variant="info" appearance="status">
            unsaved
          </Badge>
        )}
        {setting.secret && (
          <Badge variant={setting.present ? "ok" : "muted"} appearance="status">
            {setting.present ? "set" : "not set"}
          </Badge>
        )}
        {setting.shadowed && (
          <Tooltip label="Set in your shell, which overrides .env. Saving here won't change it.">
            <Badge variant="warn" appearance="status">
              shell wins
            </Badge>
          </Tooltip>
        )}
        {setting.hint && <span className="basis-full text-[12px] text-muted-foreground">{setting.hint}</span>}
      </div>
      <Control setting={setting} draft={draft} onChange={onChange} />
    </Wrapper>
  );
}

/** A value as `.env` spells it, so in mono; what fills an empty one is a sentence, so not. */
const FIELD = "h-8 px-2.5 font-mono text-[12.5px] placeholder:font-sans";

function Control({
  setting,
  draft,
  onChange,
}: {
  setting: Setting;
  draft: string | undefined;
  onChange: (value: string) => void;
}) {
  const current = draft ?? (setting.secret ? "" : setting.value);

  if (setting.kind === "boolean" || setting.kind === "choice") {
    // `.env` spells booleans lowercase, and that is what gets written.
    const options =
      setting.kind === "boolean"
        ? [
            { value: "true", label: "On" },
            { value: "false", label: "Off" },
          ]
        : setting.choices.map((choice) => ({ value: choice, label: choice }));
    return (
      <div role="group" aria-label={setting.key} className="flex flex-wrap gap-1.5">
        <ToggleGroup>
          {options.map((option) => (
            <ToggleChip
              key={option.value}
              pressed={option.value === current}
              onClick={() => onChange(option.value)}
              className={cn("h-8", setting.kind === "choice" && "font-mono text-[12.5px]")}
            >
              {option.label}
            </ToggleChip>
          ))}
        </ToggleGroup>
      </div>
    );
  }

  return (
    <Input
      type={setting.secret ? "password" : setting.kind === "text" ? "text" : "number"}
      step={setting.kind === "number" ? "0.1" : undefined}
      inputMode={setting.kind === "integer" ? "numeric" : undefined}
      autoComplete="off"
      spellCheck={false}
      value={current}
      onChange={(e) => onChange(e.target.value)}
      // A secret's characters never reach the client, so there is nothing to
      // show as a current value — only whether one exists.
      placeholder={
        setting.secret ? (setting.present ? "set — type to replace" : "not set") : setting.effective || "not set"
      }
      className={FIELD}
    />
  );
}
