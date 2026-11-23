import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionProvider } from "@/lib/motion/provider";
import { TooltipProvider } from "@/components/ui/overlays/tooltip";
import { assertPalettesResolve } from "@/themes/paint";
import App from "@/App";
import "@/index.css";

assertPalettesResolve();

const client = new QueryClient({
  defaultOptions: {
    queries: {
      // League state changes on the platform's clock, not ours, and every fetch
      // is a real API call the platform rate-limits. Refetching because a window
      // regained focus buys nothing here.
      refetchOnWindowFocus: false,
      staleTime: 60_000,
      retry: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={client}>
      {/* Loaded after first paint, not bundled into it: `m` components carry
          no animation code of their own, and the feature set arrives in a
          second chunk. It has to come from its own module: an import of
          `motion/react` from here resolves to this same bundle and never
          splits. */}
      <MotionProvider features={() => import("@/lib/motion/features").then((mod) => mod.default)}>
        <TooltipProvider>
          <App />
        </TooltipProvider>
      </MotionProvider>
      </QueryClientProvider>
    </BrowserRouter>
  </StrictMode>,
);
