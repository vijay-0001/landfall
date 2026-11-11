import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  ...coreWebVitals,
  ...typescript,
  {
    ignores: [".next/**", "node_modules/**", "test-results/**", "playwright-report/**", "src/lib/api/types.ts", "stubs/**", "next-env.d.ts"],
  },
  {
    rules: { "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }] },
  },
];

export default config;
