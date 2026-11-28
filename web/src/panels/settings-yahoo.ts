/**
 * How Settings says Yahoo is being read, and how to set up the way chosen:
 * the status in its card's corner, and the steps under its rows.
 */
import { Component, Mount } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { Effect, Schema } from "effect";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/controls/button";
import { Disclosure } from "@/components/ui/overlays/disclosure";
import { bookmarklet } from "@/lib/bookmarklet";
import { moment } from "@/lib/times";
import type { Variant } from "@/lib/tone";
import type { CaptureStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How Yahoo is read as the server last saw it, for a page that has no switch to ask. */
export function readBy(status: CaptureStatus): string {
  return status.session ? "session" : status.active ? "browser" : "oauth";
}

/** A line of status and the tone that finds it. */
type Readout = { text: string; variant: Variant };

const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/**
 * How reading Yahoo is going, said in the header's corner: in words, with the tone only to find it.
 *
 * Leads with how many leagues were read, once any were — "5 leagues · last
 * fetched 02:07 AM" — rather than listing them on a line of their own.
 */
export function yahooState(status: CaptureStatus): Readout {
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

export function YahooState<M>(h: Html.H<M>, status: CaptureStatus) {
  const { text, variant } = yahooState(status);

  return Badge(h, { variant, appearance: "status", class: "normal-case tracking-normal" }).children(text);
}

/**
 * Sets the bookmark's link on the element itself: the view's renderer refuses
 * a `javascript:` href, which is the only kind a bookmark can run. `app` is
 * the origin it is served from, so the bookmark calls back the same app.
 */
export const SetBookmark = Mount.make("SetBookmark", { args: { app: Schema.String } }, (node: HTMLAnchorElement, { app }) =>
  Effect.sync(() => node.setAttribute("href", bookmarklet(app))).pipe(Effect.as(Component.noop)),
);

/**
 * How to set up the way Yahoo is read, for the way chosen only: the session
 * cookie to paste, or the bookmark to run on a Yahoo page. OAuth needs no
 * steps beyond its note. Open while it is the source in use and not yet working.
 *
 * Clicking the bookmark here does nothing — it runs on Yahoo's page, after
 * being dragged away.
 */
export function YahooHowTo<M>(h: Html.H<M>, status: CaptureStatus, mode: string) {
  const { session } = status;
  const steps = "max-w-[70ch] list-decimal pl-5";

  return h.div.class("contents").children(
    Disclosure(h, {
      summary: ["Session cookie"],
      open: Boolean(session && (session.expired || !session.fetched_at)),
      class: cn(mode !== "session" && "hidden"),
      children: [
        h.div.class("flex flex-col gap-2 px-4 pb-4 text-[13px] leading-relaxed text-muted-foreground").children(
          session?.expired && h.p.class("text-foreground").children("Yahoo refused the cookie. Paste a fresh one."),
          h.ol.class(steps).children(
            h.li("On a Yahoo Fantasy page in Chrome or Dia, open DevTools → Network."),
            h.li(
              "Pick a request to ",
              h.code.class("font-mono text-[12px]").children("pub-api-ro.fantasysports.yahoo.com"),
              " → Request Headers → cookie, and copy the value.",
            ),
            h.li("Paste it into YAHOO_SESSION_COOKIE above."),
          ),
        ),
      ],
    }),
    Disclosure(h, {
      summary: ["Sync bookmark"],
      open: status.active && !status.synced_at,
      class: cn(mode !== "browser" && "hidden"),
      children: [
        h.div.class("flex flex-col items-start gap-2 px-4 pb-4 text-[13px] leading-relaxed text-muted-foreground").children(
          h.a
            .attrs({ draggable: "true", class: buttonVariants({ variant: "secondary", size: "sm" }) })
            .on("click", () => undefined, { preventDefault: "always" })
            .onMount(SetBookmark({ app: window.location.origin }))
            .children("Sync Yahoo"),
          h.ol.class(steps).children(
            h.li("Drag the button to your bookmarks bar."),
            h.li("Open any Yahoo Fantasy Basketball page and click the bookmark."),
            h.li("Allow local network access once when Chrome asks."),
          ),
        ),
      ],
    }),
  );
}
