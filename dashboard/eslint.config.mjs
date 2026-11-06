import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// eslint-config-next 16 ships native flat configs; FlatCompat resolved them into a circular reference.
export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  // eslint-plugin-react detects the version through APIs ESLint 10 removed; naming it skips the detection.
  { settings: { react: { version: "19" } } },
  globalIgnores([".next/**", "node_modules/**", "next-env.d.ts"]),
]);
