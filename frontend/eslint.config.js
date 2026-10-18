import js from '@eslint/js'
import prettier from 'eslint-config-prettier'
import reactHooks from 'eslint-plugin-react-hooks'
import { reactRefresh } from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default defineConfig([
  globalIgnores(['dist', 'coverage']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      prettier,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: { 'react-refresh': reactRefresh.plugin },
    rules: {
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // Downgrade any to warn — we have existing any usage to fix incrementally
      '@typescript-eslint/no-explicit-any': 'warn',
      // Allow unused vars with _ prefix convention
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // react-hooks v7 introduced new strict rules not present in v4.
      // "refs" flags the well-established "latest ref" pattern (useRef + assign in render)
      // which React docs endorse — disable as a false positive for this codebase.
      'react-hooks/refs': 'off',
      // "static-components" flags component lookups from registries (e.g. LucideIcon
      // from getGroupIcon) as "created during render" — false positive for icon registries.
      'react-hooks/static-components': 'off',
      // "set-state-in-effect" flags synchronous setState inside effects — this is
      // a common and legitimate pattern for resetting dialog state, syncing draft
      // state from props, etc. Disabled as overly strict for this codebase.
      'react-hooks/set-state-in-effect': 'off',
      // @tanstack/react-virtual's useVirtualizer intentionally returns non-memo-safe
      // functions — this warning is a false positive for our usage.
      'react-hooks/incompatible-library': 'off',
    },
  },
  {
    files: ['**/*.test.ts', '**/*.test.tsx'],
    rules: {
      // Test mocking often requires `any` casts
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
  {
    // Build and tooling config run by Node
    files: ['**/*.{js,mjs}'],
    extends: [js.configs.recommended, prettier],
    languageOptions: { globals: globals.node },
  },
])
