import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Setting } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { IconButton } from "@/components/ui/icon-button";
import { Loading } from "@/components/ui/state";
import { ToggleChip } from "@/components/ui/toggle";
import { Card, CardHeader } from "@/components/ui/card";
import { ArrowLeft, Check, Save } from "lucide-react";
import { useTheme } from "@/lib/useTheme";
import { PALETTES } from "@/themes/registry";
import { ErrorNote } from "@/components/ui/error-note";
import { PageHeader } from "@/components/ui/page-header";

/**
 * Grouped by what each key unlocks, in the order someone sets them up, rather
 * than by the order they happen to sit in `.env`. A key on its own means
 * nothing; "this is the one that turns on football" is what a person is
 * actually looking for.
 */
const GROUPS: { title: string; note: string; keys: string[] }[] = [
  {
    title: "Fantasy Premier League",
    note: "FPL has no username lookup. The entry id is the number in the URL of your own points page: fantasy.premierleague.com/entry/<THIS>/event/1",
    keys: ["FPL_ENTRY_ID"],
  },
  {
    title: "NFL on Sleeper",
    note: "Sleeper needs no key or OAuth — just the username your leagues are under.",
    keys: ["SLEEPER_USERNAME"],
  },
  {
    title: "NBA on Yahoo",
    note: "From a Yahoo developer app with Fantasy Sports read permission and redirect URI https://localhost:8080. Yahoo also reviews each application before granting API access. Authorizing is a button on the competition itself, once.",
    keys: ["YAHOO_CLIENT_ID", "YAHOO_CLIENT_SECRET", "YAHOO_REDIRECT_URI", "YAHOO_MAX_WEEKLY_ADDS"],
  },
  {
    title: "AI",
    note: "Optional, and each provider is free to start. Any one key turns on the report, trade evaluation and follow-up questions; without one, everything read from the platforms works exactly as it does now. With several, each backs up the one before when its free quota runs out — Gemini, then Groq, then OpenRouter. Models are settings because free catalogs change.",
    keys: [
      "GOOGLE_API_KEY",
      "DEFAULT_MODEL",
      "GROQ_API_KEY",
      "GROQ_ANALYSIS_MODEL",
      "GROQ_PARSING_MODEL",
      "OPENROUTER_API_KEY",
      "OPENROUTER_ANALYSIS_MODEL",
      "OPENROUTER_PARSING_MODEL",
    ],
  },
  {
    title: "Tracing",
    note: "Optional. Without a token nothing is exported and no network call is made. Prompt text is never sent unless you turn it on, and a prompt carries your roster and your leagues.",
    keys: ["LOGFIRE_TOKEN", "LOGFIRE_ENVIRONMENT", "LOGFIRE_CAPTURE_PROMPTS"],
  },
  {
    title: "Advanced",
    note: "Rarely worth changing. Each field shows the value already in force; typing replaces it.",
    keys: [
      "LOG_LEVEL",
      "SLEEPER_CACHE_DIR",
      "FPL_CACHE_DIR",
      "YAHOO_CACHE_DIR",
      "ESPN_CACHE_DIR",
      "ANSWER_CACHE_DIR",
      "ITEM_STATE_DIR",
      "YAHOO_TOKEN_FILE",
    ],
  },
];

export function SettingsPanel({ onBack }: { onBack: () => void }) {
  const queryClient = useQueryClient();
  const settings = useQuery<Setting[], Error>({ queryKey: ["settings"], queryFn: api.settings });
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const save = useMutation<Setting[], Error, Record<string, string>>({
    mutationFn: api.saveSettings,
    onSuccess: () => {
      setDrafts({});
      // Everything downstream depends on configuration: which sports appear,
      // which leagues they hold. Drop it all rather than guess what moved.
      queryClient.invalidateQueries();
    },
  });

  const byKey = useMemo(() => new Map((settings.data ?? []).map((s) => [s.key, s])), [settings.data]);

  // Anything the groups above forgot still has to be reachable, or a setting
  // added later becomes invisible here with nothing to say so.
  const ungrouped = (settings.data ?? []).filter((s) => !GROUPS.some((g) => g.keys.includes(s.key)));
  const groups = ungrouped.length
    ? [...GROUPS, { title: "Other", note: "Declared in settings.py but not grouped here.", keys: ungrouped.map((s) => s.key) }]
    : GROUPS;

  const pending = Object.keys(drafts).length;

  return (
    <>
      <PageHeader
        title="Settings"
        meta="Written to .env and applied immediately"
        leading={<IconButton label="Back" icon={<ArrowLeft />} onClick={onBack} />}
      >
        <div className="flex items-center gap-1">
          {/* The count lives in the label rather than beside the icon: the
              control does one thing whether one field changed or six, and the
              rows that changed already say which. */}
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

      {settings.isError && <ErrorNote error={settings.error} />}
      {save.isError && <ErrorNote error={save.error} />}
      {settings.isLoading && <Loading lines={6} />}

      {settings.data && (
        <div className="flex flex-col gap-4 p-5">
          <Appearance />
          {groups.map((group) => (
            <Card key={group.title}>
              <CardHeader>
                <span>{group.title}</span>
              </CardHeader>
              <p className="max-w-[70ch] px-4 pt-3 text-[13px] leading-relaxed text-muted-foreground">{group.note}</p>
              <div className="flex flex-col p-4 pt-3">
                {group.keys.map((key) => {
                  const setting = byKey.get(key);
                  if (!setting) return null;
                  return (
                    <Row
                      key={key}
                      setting={setting}
                      draft={drafts[key]}
                      onChange={(value) =>
                        setDrafts((current) => {
                          const next = { ...current };
                          // Typing back to the stored value is not a change.
                          if (value === (setting.secret ? "" : setting.value)) delete next[key];
                          else next[key] = value;
                          return next;
                        })
                      }
                    />
                  );
                })}
              </div>
            </Card>
          ))}
        </div>
      )}
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
        <span>Appearance</span>
        <span className="normal-case tracking-normal">this browser only</span>
      </CardHeader>
      <div className="flex flex-wrap gap-2 p-4">
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
  return (
    <label className="grid grid-cols-1 items-baseline gap-1.5 border-b border-border/45 py-2.5 last:border-b-0 sm:grid-cols-[16rem_minmax(0,1fr)] sm:gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <code className="font-mono text-[12px] text-foreground">{setting.key}</code>
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
          <Tooltip label="This is exported in your shell, which pydantic reads ahead of .env — saving here will not change the running value.">
            <Badge variant="warn" appearance="status">
              shell wins
            </Badge>
          </Tooltip>
        )}
      </div>
      <Control setting={setting} draft={draft} onChange={onChange} />
    </label>
  );
}

const FIELD = "h-8 w-full min-w-0 rounded-md border border-input bg-background px-2.5 font-mono text-[12.5px] placeholder:font-sans placeholder:text-muted-foreground";

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

  if (setting.kind === "boolean") {
    // `.env` spells booleans lowercase, and that is what gets written.
    return (
      <input
        type="checkbox"
        checked={current === "true"}
        onChange={(e) => onChange(e.target.checked ? "true" : "false")}
        className="size-4 accent-[var(--color-primary)] justify-self-start"
      />
    );
  }

  if (setting.kind === "choice") {
    return (
      <select value={current} onChange={(e) => onChange(e.target.value)} className={FIELD}>
        {setting.choices.map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    );
  }

  return (
    <input
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
        setting.secret
          ? setting.present
            ? "•••••••• — type to replace"
            : "not set"
          : setting.effective || "not set"
      }
      className={FIELD}
    />
  );
}
