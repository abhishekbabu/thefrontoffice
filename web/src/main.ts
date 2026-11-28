/**
 * The browser entry: mounts the app on the page with the platform's Layers —
 * the browser Router over the address bar, and every query's fetch.
 */
import { Router } from "@effect/ui";
import { BrowserHost, BrowserRouter } from "@effect/ui/html";
import { Effect, Layer } from "effect";
import { App } from "@/App";
import { readCompared } from "@/lib/compare";
import { QueriesLayer } from "@/lib/queries/layer";
import { AppRoute } from "@/lib/route";
import { currentTheme } from "@/lib/theme";
import { assertPalettesResolve } from "@/themes/paint";
import "@/index.css";

assertPalettesResolve();

const { mode, followsSystem } = currentTheme();

const props = Router.props(AppRoute).pipe(
  Effect.map(({ route }) => ({ route, mode, followsSystem, compared: readCompared() })),
);

const Main = BrowserHost.mount(App, props, document.getElementById("root")!).pipe(
  Layer.provide(Layer.mergeAll(BrowserRouter.layer({ routes: AppRoute }), QueriesLayer)),
);

Layer.launch(Main).pipe(Effect.runFork);
