import { RuleTester } from "oxlint/plugins-dev";
import { noNativeTitle, semanticColor } from "./front-office";

const tester = new RuleTester({ languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } }, sourceType: "module" } });

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
  valid: [{ code: '<Empty title="Nothing to do" />;' }, { code: '<span aria-label="x" />;' }],
  invalid: [{ code: '<span title="Projected points">12.3</span>;', errors: 1 }],
});
