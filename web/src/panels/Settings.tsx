import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Setting, type SettingsGroup } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Input, Select } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { IconButton } from "@/components/ui/icon-button";
import { QueryState } from "@/components/ui/state";
import { keys } from "@/lib/queries";
import { ToggleChip } from "@/components/ui/toggle";
import { Card, CardHeader } from "@/components/ui/card";
import { ArrowLeft, Check, Save } from "lucide-react";
import { useTheme } from "@/lib/useTheme";
import { PALETTES } from "@/themes/registry";
import { ErrorNote } from "@/components/ui/error-note";
import { PageHeader } from "@/components/ui/page-header";

export function SettingsPanel({ onBack }: { onBack: () => void }) {
  const queryClient = useQueryClient();
  // Grouped by the server, by what each key unlocks and in the order someone
  // sets them up: a key on its own means nothing, and "this is the one that
  // turns on football" is what a person is actually looking for.
  const settings = useQuery<SettingsGroup[], Error>({ queryKey: keys.settings, queryFn: api.settings });
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const save = useMutation<SettingsGroup[], Error, Record<string, string>>({
    mutationFn: api.saveSettings,
    onSuccess: () => {
      setDrafts({});
      // Everything downstream depends on configuration: which sports appear,
      // which leagues they hold. Drop it all rather than guess what moved.
      queryClient.invalidateQueries();
    },
  });

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

      <QueryState query={settings} lines={6} />
      {save.isError && <ErrorNote error={save.error} />}

      {settings.data && (
        <div className="flex flex-col gap-4 p-5">
          <Appearance />
          {settings.data.map((group) => (
            <Card key={group.title}>
              <CardHeader>
                <span>{group.title}</span>
              </CardHeader>
              <p className="max-w-[70ch] px-4 pt-3 text-[13px] leading-relaxed text-muted-foreground">{group.note}</p>
              <div className="flex flex-col p-4 pt-3">
                {group.settings.map((setting) => (
                  <Row
                    key={setting.key}
                    setting={setting}
                    draft={drafts[setting.key]}
                    onChange={(value) =>
                      setDrafts((current) => {
                        const next = { ...current };
                        // Typing back to the stored value is not a change.
                        if (value === (setting.secret ? "" : setting.value)) delete next[setting.key];
                        else next[setting.key] = value;
                        return next;
                      })
                    }
                  />
                ))}
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
    <label className="grid grid-cols-1 items-baseline gap-1.5 border-b border-border/45 py-2.5 last:border-b-0 sm:grid-cols-[16rem_minmax(0,42rem)] sm:gap-4">
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
      <Select value={current} onChange={(e) => onChange(e.target.value)} className={FIELD}>
        {setting.choices.map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </Select>
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
