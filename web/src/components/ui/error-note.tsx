import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink as ExternalLinkIcon } from "lucide-react";
import { ApiError, api, type Remedy } from "@/lib/api";
import { keys } from "@/lib/queries";
import { SETTINGS } from "@/lib/route";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * A failure, and the one thing this app can do about it.
 *
 * The server says both: the condition in words, and the remedy — the same one
 * a terminal prints as a command — so nothing here decides what fixes what.
 *
 * Inset by its own margin, for the common case of standing in for a page or a
 * card's contents; a caller placing it in a padded stack passes `m-0`.
 */
export function ErrorNote({ error, className }: { error: unknown; className?: string }) {
  return (
    <div
      role="alert"
      className={cn(
        "m-5 flex flex-col items-start gap-3 rounded-md border border-destructive/30 bg-destructive/8 px-4 py-3",
        className,
      )}
    >
      <p className="max-w-[70ch] text-[13.5px] leading-relaxed text-destructive">
        {error instanceof Error ? error.message : "Something went wrong."}
      </p>
      {error instanceof ApiError && error.remedy && <RemedyAction remedy={error.remedy} />}
    </div>
  );
}

/** The control a remedy asks for: a login, Settings, another try, or a page off the app. */
export function RemedyAction({ remedy }: { remedy: Remedy }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  switch (remedy.action) {
    case "authorize":
      return <YahooLoginButton label={remedy.label} />;
    case "settings":
      return (
        <Button variant="outline" onClick={() => navigate(SETTINGS)}>
          {remedy.label}
        </Button>
      );
    case "retry":
      // Everything is asked again: whatever else failed on this page failed
      // on the same outage.
      return (
        <Button variant="outline" onClick={() => queryClient.invalidateQueries()}>
          {remedy.label}
        </Button>
      );
    case "link":
      return (
        <a href={remedy.url} target="_blank" rel="noopener noreferrer" className={buttonVariants({ variant: "outline" })}>
          {remedy.label}
          <ExternalLinkIcon className="size-3.5" aria-hidden />
        </a>
      );
  }
}

/**
 * Starts the Yahoo handshake and watches it.
 *
 * The click cannot be answered by one request: authorizing means a browser tab
 * and a person, so the server starts the flow and reports progress separately.
 */
function YahooLoginButton({ label }: { label: string }) {
  const queryClient = useQueryClient();
  const [watching, setWatching] = useState(false);

  const start = useMutation({ mutationFn: api.yahooLogin, onSuccess: () => setWatching(true) });

  const state = useQuery({
    queryKey: keys.yahooLogin,
    queryFn: api.yahooLoginState,
    enabled: watching,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1500 : false),
  });

  useEffect(() => {
    if (state.data?.status !== "ok") return;
    // Everything about this competition failed on the missing authorization;
    // none of those answers are worth keeping now that it exists. Polling
    // stops on its own once the status is no longer running.
    queryClient.invalidateQueries();
  }, [state.data?.status, queryClient]);

  const status = state.data?.status;
  const running = start.isPending || status === "running";

  return (
    <div className="flex flex-col gap-2">
      <Button variant="primary" onClick={() => start.mutate()} disabled={running}>
        {running ? "Waiting for the browser…" : label}
      </Button>
      {running && (
        <p className="max-w-[60ch] text-[12.5px] text-muted-foreground">
          A tab has opened. Accept the certificate warning if one appears, then approve the app.
        </p>
      )}
      {status === "failed" && (
        <p className="max-w-[70ch] text-[12.5px] leading-relaxed text-destructive">{state.data?.detail}</p>
      )}
    </div>
  );
}
