import { Command, Component, UiSchema } from "@effect/ui";
import type { View } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Cause, Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { PageHeader } from "@/components/league/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Input } from "@/components/ui/controls/input";
import { MARKER } from "@/components/ui/controls/tabs";
import { ToggleChip } from "@/components/ui/controls/toggle";
import { ErrorNote } from "@/components/ui/error-note";
import { Hint } from "@/components/ui/overlays/hint";
import { Disclosure } from "@/components/ui/overlays/disclosure";
import { Label, META } from "@/components/ui/label";
import { QueryState } from "@/components/ui/state";
import { ApiError, api } from "@/lib/api";
import { GetCaptureStatus, GetSettings } from "@/lib/queries/app";
import { fetching, tags } from "@/lib/queries/cache";
import { PaintPalette, currentTheme } from "@/lib/theme";
import type { CaptureStatus, Setting, SettingsGroup } from "@/lib/types";
import { cn } from "@/lib/utils";
import { YahooHowTo, YahooState, readBy } from "@/panels/settings-yahoo";
import { PALETTES } from "@/themes/registry";

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

/** What has been typed or pressed and not yet saved, by key. */
const Drafts = Schema.Record(Schema.String, Schema.String);

type Drafts = typeof Drafts.Type;

/** An edit to one setting, and what it holds as stored: typing back to that is not a change. */
const Edit = { key: Schema.String, value: Schema.String, stored: Schema.String };

const SettingsMessage = UiSchema.TaggedEnum({
  ClickedBack: {},
  UpdatedField: Edit,
  ClickedChoice: Edit,
  ClickedDiscard: {},
  ClickedSave: {},
  SucceededSaveSettings: {},
  FailedSaveSettings: { error: ApiError },
  ClickedPalette: { palette: Schema.String },
});

/** `RequestedBack`: the way out of Settings was pressed. The shell goes back to where it was. */
export const SettingsEvents = UiSchema.TaggedEnum({ RequestedBack: {} });

/**
 * Writes the drafts to `.env`. Everything downstream depends on
 * configuration — which sports appear, which leagues they hold — so every
 * answer is dropped rather than guessing what moved.
 */
class SaveSettings extends Command.Service<SaveSettings>()("settings/SaveSettings", {
  args: { values: Drafts },
  success: SettingsMessage,
  invalidates: () => [tags.api],
}) {
  static readonly layer = this.toLayer(({ values }) =>
    fetching(() => api.saveSettings(values)).pipe(
      Effect.match({
        onSuccess: () => SettingsMessage.SucceededSaveSettings(),
        onFailure: (error) => SettingsMessage.FailedSaveSettings({ error }),
      }),
    ),
  );
}

type Message = typeof SettingsMessage.Type;

type H = Html.H<Message>;

/** `drafts` with `value` for `key`, or without it where the value is what is stored. */
function edited(drafts: Drafts, { key, value, stored }: { key: string; value: string; stored: string }): Drafts {
  const next = { ...drafts };

  if (value === stored) delete next[key];
  else next[key] = value;

  return next;
}

/** What a setting holds as stored, as its field would show it: a secret's characters never reach the client. */
const storedOf = (setting: Setting) => (setting.secret ? "" : setting.value);

const SettingsPanelNoDeps = Html.component({
  name: "SettingsPanel",
  model: Schema.Struct({
    drafts: Drafts,
    /** Whether the last save went through, and nothing has been saved since. */
    saved: Schema.Boolean,
    failed: Schema.NullOr(ApiError),
    palette: Schema.String,
  }),
  message: SettingsMessage,
  events: SettingsEvents,
  queries: {
    // Grouped by the server, by what each key unlocks: a key on its own means
    // nothing, and "this is the one that turns on football" is what a person is
    // actually looking for.
    settings: { query: GetSettings, args: () => ({}) },
    capture: {
      query: GetCaptureStatus,
      args: ({ queries }) =>
        AsyncResult.isSuccess(queries.settings) && queries.settings.value.some((group) => group.platform === "yahoo")
          ? { platform: "yahoo" }
          : undefined,
    },
  },
}).make({
  init: () => ({ drafts: {}, saved: false, failed: null, palette: currentTheme().palette }),
  update: {
    ClickedBack: ($) => $.emit(SettingsEvents.RequestedBack()),
    UpdatedField: ($, edit) => $.evolve({ drafts: (drafts) => edited(drafts, edit) }),
    // A choice's fill slides from the chip it left to the one pressed.
    ClickedChoice: ($, edit) => $.evolve({ drafts: (drafts) => edited(drafts, edit) }).viewTransition([MARKER]),
    ClickedDiscard: ($) => $.evolve({ drafts: {} }),
    ClickedSave: ($) => $.evolve({ saved: false, failed: null }).run(SaveSettings.make({ values: $.model.drafts })),
    SucceededSaveSettings: ($) => $.evolve({ drafts: {}, saved: true, failed: null }),
    FailedSaveSettings: ($, { error }) => $.evolve({ failed: error }),
    ClickedPalette: ($, { palette }) =>
      $.evolve({ palette }).run(PaintPalette.make({ palette }).pipe(Command.asNoop)).viewTransition([MARKER]),
  },
  view: (h, model) => {
    const saving = h.isRunning(SaveSettings);
    const pending = Object.keys(model.drafts).length;
    const settings = h.queries.settings;
    const capture = h.queries.capture;
    const groups = AsyncResult.isSuccess(settings) ? settings.value : null;

    const section = (id: SettingsGroup["section"]) =>
      (groups ?? [])
        .filter((group) => group.section === id)
        .map((group) => GroupCard(h, { group, drafts: model.drafts, capture }));

    return h.div(
      PageHeader(h, {
        title: "Settings",
        meta: "Saved to .env, applied at once",
        leading: [
          IconButton(h, {
            key: "back",
            props: { label: "Back", icon: "arrow-left" },
            onEmit: { Clicked: () => SettingsMessage.ClickedBack() },
          }),
        ],
        children: [
          h.div.class("flex items-center gap-2").children(
            // Said in words beside the control, so whether anything is waiting
            // to be written — or just was — reads without hovering.
            h.span
              .attrs({ role: "status", class: META })
              .children(saving ? "Saving…" : pending ? `${pending} unsaved` : model.saved ? "Saved" : ""),
            pending > 0 &&
              IconButton(h, {
                key: "discard",
                props: { label: "Discard changes", icon: "undo-2", disabled: saving },
                onEmit: { Clicked: () => SettingsMessage.ClickedDiscard() },
              }),
            IconButton(h, {
              key: "save",
              props: {
                label: saving ? "Saving" : pending ? `Save ${pending} change${pending === 1 ? "" : "s"}` : "Nothing to save",
                variant: pending ? "primary" : "ghost",
                icon: pending ? "save" : "check",
                disabled: !pending || saving,
              },
              onEmit: { Clicked: () => SettingsMessage.ClickedSave() },
            }),
          ),
        ],
      }),
      QueryState(h, settings, { lines: 6 }),
      model.failed !== null && ErrorNote(h, { error: model.failed, key: "save" }),
      groups !== null &&
        h.div.class("flex flex-col gap-8 p-5").children(
          Section(h, SECTIONS.platforms, section("platforms")),
          Section(h, SECTIONS.ai, section("ai")),
          Section(h, "Appearance", [Appearance(h, model.palette)]),
          Section(h, SECTIONS.advanced, section("advanced")),
        ),
    );
  },
});

/** Settings, with the Command that saves them. */
export const SettingsPanel = SettingsPanelNoDeps.pipe(Component.provide(SaveSettings.layer));

function Section<C extends View.Children<Message>>(h: H, title: string, children: C) {
  return h.section.class("flex flex-col gap-3").children(Label(h, { as: "h2" }).children(title), children);
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
function GroupCard(
  h: H,
  {
    group,
    drafts,
    capture,
  }: { group: SettingsGroup; drafts: Drafts; capture: AsyncResult.AsyncResult<CaptureStatus, ApiError> },
) {
  const yahoo = group.platform === "yahoo";
  const status = yahoo && AsyncResult.isSuccess(capture) ? capture.value : null;
  const switched = group.settings.find((setting) => setting.key === group.switch);
  const chosen = switched ? (drafts[switched.key] ?? switched.effective) : "";
  const needed = (setting: Setting) => !setting.mode || setting.mode === chosen;
  const others = group.settings.filter((setting) => !needed(setting));
  const note = [group.note, group.modes[chosen]].filter((text): text is string => Boolean(text));

  const row = (setting: Setting) => Row(h, setting, drafts[setting.key]);

  return Card(h)
    .key(group.title)
    .attrs({ role: "group", "aria-label": group.title })
    .children(
      CardHeader(h).children(h.span(group.title), status !== null && YahooState(h, status)),
      ...note.map((text) =>
        h.p.key(text).class("max-w-[70ch] px-4 pt-3 text-[13px] leading-relaxed text-muted-foreground").children(text),
      ),
      h.div.class("flex flex-col px-4 py-1").children(group.settings.filter(needed).map(row)),
      yahoo &&
        AsyncResult.isFailure(capture) &&
        ErrorNote(h, { error: Cause.squash(capture.cause), key: "capture", class: "mx-4 mt-0 mb-4" }),
      status !== null && YahooHowTo(h, status, chosen || readBy(status)),
      others.length > 0 &&
        Disclosure(h, {
          summary: ["Other methods"],
          children: [h.div.class("flex flex-col px-4 pb-2").children(others.map(row))],
        }),
    );
}

/**
 * Palette lives in this browser, not in `.env`.
 *
 * Said plainly because everything else on this page is configuration shared by
 * every front end — someone who sets a palette here and opens the app elsewhere
 * should know why it did not follow them.
 */
function Appearance(h: H, palette: string) {
  return Card(h).children(
    CardHeader(h).children(h.span("Palette"), h.span.class("font-normal normal-case tracking-normal").children("This browser only")),
    h.div.attrs({ role: "group", "aria-label": "Palette", class: "flex flex-wrap gap-2 p-4" }).children(
      PALETTES.map((p) =>
        ToggleChip(h, {
          pressed: p.id === palette,
          onClick: SettingsMessage.ClickedPalette({ palette: p.id }),
          group: "palette",
          class: "h-auto gap-2.5 py-2 text-left",
        })
          .key(p.id)
          .children(
            h.span.class("size-4 shrink-0 rounded-full border border-border").style({ background: p.swatch }),
            h.span(
              h.span.class("block text-[13px] font-medium leading-tight").children(p.label),
              h.span.class("block font-mono text-[10px] opacity-70").children(p.hint),
            ),
          ),
      ),
    ),
  );
}

/** The id a setting's field goes by, so the row's label names it. */
const fieldId = (setting: Setting) => `setting-${setting.key}`;

function Row(h: H, setting: Setting, draft: string | undefined) {
  // A row of chips is several controls, so it cannot sit in a `<label>`: a
  // click on the key would press whichever chip came first. A field's label
  // names it by id, so a click on the key reaches the field and not the
  // "shell wins" note before it.
  const chips = setting.kind === "boolean" || setting.kind === "choice";
  const wrapper = chips ? h.div : h.label.attr("for", fieldId(setting));

  return wrapper
    .key(setting.key)
    .class(
      "grid grid-cols-1 items-center gap-1.5 border-b border-border/45 py-2.5 last:border-b-0 sm:grid-cols-[16rem_minmax(0,42rem)] sm:gap-4",
    )
    .children(
      h.div.class("flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1").children(
        h.code.class("break-all font-mono text-[12px] text-foreground").children(setting.key),
        draft !== undefined && Badge(h, { variant: "info", appearance: "status" }).children("unsaved"),
        setting.secret &&
          Badge(h, { variant: setting.present ? "ok" : "muted", appearance: "status" }).children(
            setting.present ? "set" : "not set",
          ),
        setting.shadowed &&
          Hint(h, {
            key: `${setting.key}/shell`,
            props: { label: "Set in your shell, which overrides .env. Saving here won't change it." },
            slots: { content: Badge(h, { variant: "warn", appearance: "status" }).children("shell wins") },
          }),
        setting.hint && h.span.class("basis-full text-[12px] text-muted-foreground").children(setting.hint),
      ),
      chips ? Choices(h, setting, draft) : Field(h, setting, draft),
    );
}

/** A value as `.env` spells it, so in mono; what fills an empty one is a sentence, so not. */
const FIELD = "h-8 px-2.5 font-mono text-[12.5px] placeholder:font-sans";

function Choices(h: H, setting: Setting, draft: string | undefined) {
  const current = draft ?? storedOf(setting);

  // `.env` spells booleans lowercase, and that is what gets written.
  const options =
    setting.kind === "boolean"
      ? [
          { value: "true", label: "On" },
          { value: "false", label: "Off" },
        ]
      : setting.choices.map((choice) => ({ value: choice, label: choice }));

  return h.div.attrs({ role: "group", "aria-label": setting.key, class: "flex flex-wrap gap-1.5" }).children(
    options.map((option) =>
      ToggleChip(h, {
        pressed: option.value === current,
        onClick: SettingsMessage.ClickedChoice({ key: setting.key, value: option.value, stored: storedOf(setting) }),
        group: setting.key,
        class: cn("h-8", setting.kind === "choice" && "font-mono text-[12.5px]"),
      })
        .key(option.value)
        .children(option.label),
    ),
  );
}

function Field(h: H, setting: Setting, draft: string | undefined) {
  return Input(h, FIELD)
    .attrs({
      id: fieldId(setting),
      type: setting.secret ? "password" : setting.kind === "text" ? "text" : "number",
      step: setting.kind === "number" ? "0.1" : undefined,
      inputmode: setting.kind === "integer" ? "numeric" : undefined,
      autocomplete: "off",
      spellcheck: "false",
      // A secret's characters never reach the client, so there is nothing to
      // show as a current value — only whether one exists.
      placeholder: setting.secret
        ? setting.present
          ? "set — type to replace"
          : "not set"
        : setting.effective || "not set",
    })
    .value(draft ?? storedOf(setting))
    .on("input", ({ value }) => SettingsMessage.UpdatedField({ key: setting.key, value, stored: storedOf(setting) }));
}
