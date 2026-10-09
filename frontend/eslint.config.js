import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    rules: {
      // Ratchet: existing violations are warnings; `npm run lint` fails if the count rises (--max-warnings).
      'react-hooks/set-state-in-effect': 'warn',
      'react-refresh/only-export-components': 'warn',
    },
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
])
