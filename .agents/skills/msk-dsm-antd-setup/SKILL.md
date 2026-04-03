---
name: msk-dsm-antd-setup
description: >
  Use this skill to set up the MSK Design System (DSM) in a web project.
  It integrates Ant Design (antd) with the MSK brand theme, design tokens,
  and optional Tailwind 4 support. Supports Next.js, Vite, and CRA projects.
  Reference: https://antd.prototype.mskcc.org/docs
---

# MSK Design System (DSM) Setup Skill

This skill sets up the MSKCC Design System in a web project using Ant Design
as the component library with MSK brand theming, tokens, and optional Tailwind 4 integration.

**Online documentation:** https://antd.prototype.mskcc.org/docs

---

## Packages Overview

| Package              | Purpose                                                |
| -------------------- | ------------------------------------------------------ |
| `antd`               | Ant Design component library (>=5 required)            |
| `@mskcc/theme-antd`  | MSK theme for antd ConfigProvider                      |
| `@mskcc/tokens`      | MSK design tokens (CSS variables, Tailwind 4, JS/TS)   |
| `@mskcc/fundamentals` | Base reset, typography, font families, helpers (optional) |
| `@mskcc/themes`      | SCSS dark/light mode theming utilities (optional)       |

---

## Step 1 — Detect the Project Type

Before starting, identify:

1. **Framework**: Next.js App Router, Next.js Pages Router, Vite, or CRA
2. **Package manager**: Check for `pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn, otherwise npm
3. **Tailwind**: Check if `tailwindcss` is already in `package.json`

---

## Step 2 — Install Required Packages

### Core (always required)

```bash
# npm
npm install antd @mskcc/theme-antd @mskcc/tokens

# pnpm
pnpm add antd @mskcc/theme-antd @mskcc/tokens

# yarn
yarn add antd @mskcc/theme-antd @mskcc/tokens
```

### Optional: Base stylesheets and fonts

```bash
npm install @mskcc/fundamentals
```

### Optional: SCSS theming

```bash
npm install @mskcc/themes
```

---

## Step 3 — Add CSS Imports to Global Stylesheet

Update the project's global CSS file (`app/globals.css` for Next.js App Router,
`src/index.css` for Vite/CRA).

### With Tailwind 4

```css
@import "tailwindcss";
@import "@mskcc/tokens/css/tailwind.css";

/* Use "consumer" for patient-facing apps, "pro" for provider/internal apps */
@import "@mskcc/tokens/css/consumer.css";

@import "@mskcc/theme-antd/dist/styles/theme.css";
```

### Without Tailwind

```css
@import "@mskcc/tokens/css/root.css";
@import "@mskcc/tokens/css/reset.css";

/* Use "consumer" for patient-facing apps, "pro" for provider/internal apps */
@import "@mskcc/tokens/css/consumer.css";

@import "@mskcc/theme-antd/dist/styles/theme.css";
```

### Optional: If using @mskcc/fundamentals, also add

```css
@import "@mskcc/fundamentals/css/styles-all";
```

---

## Step 4 — Create the AntdProvider Component

Create a provider component that wraps the app with antd's `ConfigProvider`
and the MSK theme.

### File location

- **Next.js App Router**: `app/providers/AntdProvider.tsx`
- **Vite / CRA**: `src/providers/AntdProvider.tsx`

### Provider code

```tsx
'use client'; // Only needed for Next.js App Router

import { ConfigProvider } from 'antd';
import { getDsmTheme } from '@mskcc/theme-antd';
import type { ReactNode } from 'react';

// getDsmTheme(role, theme)
//   role  — 'consumer' (patient-facing) or 'pro' (provider-facing)
//   theme — 'light' or 'dark'
const mskTheme = getDsmTheme('consumer', 'light');

export default function AntdProvider({ children }: { children: ReactNode }) {
  return <ConfigProvider theme={mskTheme}>{children}</ConfigProvider>;
}
```

### Theme API Reference

| Function                              | Description                          | Parameters                                          |
| ------------------------------------- | ------------------------------------ | --------------------------------------------------- |
| `getDsmTheme(role?, theme?)`          | CSS variables strategy (recommended) | role: `'consumer'` \| `'pro'`, theme: `'light'` \| `'dark'` |
| `getDsmThemeComponent(role?, theme?)` | CSS-in-JS strategy (fallback)        | role: `'consumer'` \| `'pro'`, theme: `'light'` \| `'dark'` |

Use `getDsmTheme` (CSS variables) for most projects — it's lighter weight.
Use `getDsmThemeComponent` (CSS-in-JS) only when CSS file imports are not possible.

---

## Step 5 — Register the Provider in the Root Layout

### Next.js App Router — `app/layout.tsx`

```tsx
import AntdProvider from './providers/AntdProvider';
import './globals.css';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AntdProvider>{children}</AntdProvider>
      </body>
    </html>
  );
}
```

### Vite / CRA — `src/main.tsx`

```tsx
import AntdProvider from './providers/AntdProvider';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <AntdProvider>
    <App />
  </AntdProvider>
);
```

---

## Step 6 — Verify the Setup

1. Run the dev server (`npm run dev`)
2. Confirm no build or TypeScript errors
3. Add a quick test component to any page:

```tsx
import { Button, Space } from 'antd';

export default function TestPage() {
  return (
    <Space>
      <Button type="primary">Primary</Button>
      <Button>Default</Button>
    </Space>
  );
}
```

4. Verify the primary button renders using MSK brand colors

---

## Token CSS Files Reference

| Import path                               | Description                          |
| ----------------------------------------- | ------------------------------------ |
| `@mskcc/tokens/css/tailwind.css`          | Tailwind 4 token integration         |
| `@mskcc/tokens/css/consumer.css`          | Consumer-facing font/color CSS vars  |
| `@mskcc/tokens/css/pro.css`               | Provider-facing font/color CSS vars  |
| `@mskcc/tokens/css/root.css`              | Root CSS variable definitions        |
| `@mskcc/tokens/css/reset.css`             | CSS reset                            |
| `@mskcc/tokens/css/sidebar-layout.css`    | Sidebar layout CSS vars              |
| `@mskcc/theme-antd/dist/styles/theme.css` | Antd component theme overrides       |

---

## Using MSK Themes (SCSS — optional)

If using SCSS, you can use `@mskcc/themes` for dark/light mode:

```scss
@use '@mskcc/themes';
```

Or for JavaScript/TypeScript access to theme tokens:

```tsx
import { lightTheme, darkTheme } from '@mskcc/themes';
```

CSS variable usage:

```css
body {
  background-color: var(--msk-color-bg);
}
```

---

## Using MSK Fundamentals (optional)

For base reset, helpers, and font families:

```scss
@use '@mskcc/fundamentals/src/styles-all';
```

For SCSS colors, variables, and mixins:

```scss
@use '@mskcc/fundamentals/scss/colors' as c;
@use '@mskcc/fundamentals/scss/variables' as v;
@use '@mskcc/fundamentals/scss/mixins' as m;

.example {
  background-color: c.$msk--color-blue-50;
  box-shadow: v.$msk--elevation-plus-24;
  font-size: m.msk-rem(16px);
}
```

---

## Notes

- Always ask the user whether the app is **consumer** (patient-facing) or **pro** (provider/internal) before selecting the role
- Always ask whether they want **light** or **dark** theme as default
- If the project already has Tailwind configured, use the Tailwind integration path
- The `'use client'` directive on the provider is only needed in Next.js App Router
- `@mskcc/theme-antd` has a peer dependency on `antd >= 5`
