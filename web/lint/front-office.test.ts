import { RuleTester } from "oxlint/plugins-dev";
import { noNativeTitle, semanticColor } from "./front-office";

const tester = new RuleTester({ languageOptions: { sourceType: "module" } });

tester.run("semantic-color", semanticColor, {
  valid: [
    { code: 'const a = "bg-card text-muted-foreground";' },
    // A palette name that is not a utility is a word, not a color.
    { code: 'const a = "the red zone";' },
  ],
  invalid: [
    { code: 'const a = "text-red-500";', errors: 1 },
    { code: "const a = `p-2 ${b} bg-emerald-50`;", errors: 1 },
  ],
});

tester.run("no-native-title", noNativeTitle, {
  valid: [
    // A component's own `title`, and a heading's, are no attribute.
    { code: 'Empty(h, { title: "Nothing to do" });' },
    { code: 'SlideOverHeader(h, { title: "Trade", onClose });' },
    { code: 'h.span.attr("aria-label", "x");' },
    { code: 'h.span.attrs({ "aria-label": "x", class: "y" });' },
    // A key held in a variable is not known to be `title`.
    { code: "h.span.attrs({ [name]: value });" },
  ],
  invalid: [
    { code: 'h.span.attr("title", "Projected points").children("12.3");', errors: 1 },
    { code: 'h.span.attrs({ title: "Projected points", class: "x" });', errors: 1 },
    { code: 'h.span.attrs({ "title": hint });', errors: 1 },
    { code: "h.button.attrs({ title });", errors: 1 },
  ],
});
