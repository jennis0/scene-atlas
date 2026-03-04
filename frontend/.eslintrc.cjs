module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
    "prettier",
  ],
  ignorePatterns: ["dist", ".eslintrc.cjs"],
  parser: "@typescript-eslint/parser",
  plugins: ["react-refresh"],
  rules: {
    "react-refresh/only-export-components": [
      "warn",
      { allowConstantExport: true },
    ],
    // Downgrade any to warn — we have existing any usage to fix incrementally
    "@typescript-eslint/no-explicit-any": "warn",
    // Allow unused vars with _ prefix convention
    "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    // react-hooks v7 introduced new strict rules not present in v4.
    // "refs" flags the well-established "latest ref" pattern (useRef + assign in render)
    // which React docs endorse — disable as a false positive for this codebase.
    "react-hooks/refs": "off",
    // "static-components" flags component lookups from registries (e.g. LucideIcon
    // from getGroupIcon) as "created during render" — false positive for icon registries.
    "react-hooks/static-components": "off",
    // "set-state-in-effect" flags synchronous setState inside effects — this is
    // a common and legitimate pattern for resetting dialog state, syncing draft
    // state from props, etc. Disabled as overly strict for this codebase.
    "react-hooks/set-state-in-effect": "off",
    // @tanstack/react-virtual's useVirtualizer intentionally returns non-memo-safe
    // functions — this warning is a false positive for our usage.
    "react-hooks/incompatible-library": "off",
  },
  overrides: [
    {
      files: ["**/*.test.ts", "**/*.test.tsx"],
      rules: {
        // Test mocking often requires `any` casts
        "@typescript-eslint/no-explicit-any": "off",
      },
    },
  ],
};
