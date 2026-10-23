import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink as ExternalLinkIcon } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui/button";

/**
 * A failure, and the one thing this app can do about it.
 *
 * The server describes the condition and deliberately names no command — the
 * same text is read in a terminal — so the remedy is chosen here, off the code.
 */
export function ErrorNote({ error }: { error: unknown }) {
  const code = error instanceof ApiError ? error.code : "error";
  const queryClient = useQueryClient();
  return (
    <div className="m-5 flex flex-col items-start gap-3 rounded-md border border-destructive/30 bg-destructive/8 px-4 py-3">
      <p className="max-w-[70ch] text-[13.5px] leading-relaxed text-destructive">
        {error instanceof Error ? error.message : "Something went wrong."}
      </p>
      {code === "yahoo_login_required" && <YahooLoginButton />}
      {(code === "ai_key_invalid" || code === "ai_unavailable") && (
        <button
          onClick={() => window.dispatchEvent(new CustomEvent("tfo:settings"))}
          className="inline-flex h-9 items-center rounded-md border border-border bg-background px-4 text-sm font-medium hover:bg-muted"
        >
          Open Settings
        </button>
      )}
      {/* A platform that is down: waiting is the remedy, and asking again is
          the one thing this page can do about it. Everything is asked again,
          because whatever failed on it failed on the same outage. */}
      {code === "platform_unavailable" && (
        <button
          onClick={() => queryClient.invalidateQueries()}
          className="inline-flex h-9 items-center rounded-md border border-border bg-background px-4 text-sm font-medium hover:bg-muted"
        >
          Try again
        </button>
      )}
      {code === "yahoo_not_approved" && (
        <a
          href="https://sports.yahoo.com/developer/access/"
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-background px-4 text-sm font-medium hover:bg-muted"
        >
          Apply for API access
          <ExternalLinkIcon className="size-3.5" aria-hidden />
        </a>
      )}
    </div>
  );
}

/**
 * Starts the Yahoo handshake and watches it.
 *
 * The click cannot be answered by one request: authorizing means a browser tab
 * and a person, so the server starts the flow and reports progress separately.
 */
export function YahooLoginButton() {
  const queryClient = useQueryClient();
  const [watching, setWatching] = useState(false);

  const start = useMutation({ mutationFn: api.yahooLogin, onSuccess: () => setWatching(true) });

  const state = useQuery({
    queryKey: ["yahoo-login"],
    queryFn: api.yahooLoginState,
    enabled: watching,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1500 : false),
  });

  useEffect(() => {
    if (state.data?.status !== "ok") return;
    // Everything about this competition failed on the missing authorization;
    // none of those answers are worth keeping now that it exists. Polling
    // stops on its own — `refetchInterval` returns false the moment the status
    // is no longer running — so nothing is set here.
    queryClient.invalidateQueries();
  }, [state.data?.status, queryClient]);

  const status = state.data?.status;
  const running = start.isPending || status === "running";

  return (
    <div className="flex flex-col gap-2">
      <Button variant="primary" onClick={() => start.mutate()} disabled={running}>
        {running ? "Waiting for the browser…" : "Authorize Yahoo"}
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
