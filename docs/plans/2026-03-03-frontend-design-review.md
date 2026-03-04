# CEDARS v2 Frontend Design Review

**Date:** 2026-03-03
**Scope:** All files under `frontend/src/` on `feature/v2-platform` branch

---

## Overall Impression

The codebase is well-structured — clean component hierarchy, proper TypeScript usage, good separation of concerns with React Query, and a sensible shadcn/ui foundation. The code quality is solid. The design issues are primarily about what's **missing** rather than what's wrong.

---

## Clinical Design Compliance Audit

### 1. Accessibility (WCAG 2.1 AA) — Needs Work

**Color contrast concerns:**
- `--muted-foreground: oklch(0.50 0.02 240)` on `--background: oklch(0.985 0.002 240)` — this is borderline for WCAG AA (4.5:1 ratio for normal text). Muted text is used extensively for descriptions, timestamps, and helper text. In clinical apps, staff work long shifts under fluorescent lighting — low-contrast text causes fatigue and errors.
- Role badge text sizes (`text-[11px]`) are below the minimum recommended 12px for clinical UIs. Small text with color-only differentiation is a problem.

**Missing keyboard/screen reader support:**
- Project cards use `onClick` on a `<Card>` div — no keyboard focus, no `role="button"`, no `tabIndex`, no `onKeyDown` handler. A keyboard-only user cannot navigate the project list.
- The dark mode toggle and logout button in the sidebar lack `aria-label` attributes.
- No skip-navigation link exists for screen reader users.
- Loading states are plain `<p>` tags — no `aria-live="polite"` regions, so screen readers won't announce loading/error state changes.

**No focus-visible styles defined** — the default outline may be invisible on the dark sidebar background.

### 2. Error Handling & Feedback — Minimal

**What's there:** Basic error banners with destructive styling. Good start.

**What's missing for clinical use:**
- **No form validation feedback.** The login form uses `required` but has no inline validation messages, no password strength indicator on registration, no character limits communicated. Clinical users need clear, immediate guidance.
- **No success confirmations.** Creating a project silently redirects — no toast/notification confirming "Project created." In clinical contexts, users need explicit confirmation that actions completed.
- **No timeout handling.** JWT tokens expire, but there's no interceptor to catch 401s and redirect to login gracefully. A clinician mid-workflow hitting an expired session with a generic error is a real problem.
- **Loading states are text-only.** No spinners, no skeleton screens. "Loading projects..." as plain text provides no visual feedback hierarchy.

### 3. Session & Authentication Safety — Gaps

- **Tokens in localStorage** (`AuthProvider.tsx`). This is an XSS risk. For clinical applications handling PHI-adjacent data, `httpOnly` cookies are the standard recommendation. At minimum, document this as a known tradeoff.
- **No session timeout warning.** Clinical apps typically warn users before auto-logout (e.g., "Your session expires in 2 minutes") to prevent data loss during annotation.
- **No "Remember me" vs. strict session option.** Clinical workstations are often shared — defaulting to persistent tokens is a concern.

### 4. Navigation & Wayfinding — Functional but Sparse

**Good:**
- Sidebar with contextual nav (project sections vs. project list) is a sound pattern.
- Breadcrumbs in `ProjectLayout` are helpful.

**Missing:**
- **No breadcrumbs on the projects list or create page.** Navigation context disappears at the top level.
- **No confirmation on destructive navigation.** If a user is mid-form on `CreateProjectPage` and clicks "All Projects," the form silently discards input. Clinical apps should prompt "Discard unsaved changes?"
- **The sidebar has no collapse/expand.** On smaller screens the 224px fixed sidebar consumes significant space. Clinical workstations vary widely in screen size.
- **No indication of current user role/permissions** in the UI. The sidebar shows the user name but not their role in the current project context.

### 5. Typography & Readability — Default

- The CSS defines no custom font family. It will fall back to the Tailwind default (system UI stack — San Francisco on Mac, Segoe UI on Windows). This is functional but:
  - Clinical apps benefit from a font with clear distinction between similar characters (l/1/I, O/0). Monospace is correctly used for the project ID, which is good.
  - No `font-size` base is set — relying on browser default 16px, which is fine, but body text sizes like `text-sm` (14px) and `text-xs` (12px) are used heavily for descriptions that may contain clinical context.

### 6. Data Density & Information Architecture — Early Stage

The current pages are sparse because it's early, but some structural concerns:

- **ProjectOverview** shows placeholder `--` for Documents and Annotations counts. Once real data flows, this page needs clear visual hierarchy separating "at a glance" metrics from "workflow actions." Currently both are flat card grids.
- **No table views anywhere.** Clinical data apps inevitably need dense tabular layouts (patient lists, note lists, annotation queues). The component library has no Table primitive yet.
- **No search or filter capability** on the project list. With multi-tenancy, users may have many projects.

### 7. Design System Completeness — Gaps

The shadcn/ui component set is minimal:
- **Present:** Button, Card, Input, Label (4 components)
- **Missing for clinical app:** Table, Dialog/Modal, Toast/Notification, Select/Dropdown, Textarea, Badge, Tooltip, Alert, Skeleton loader, Tabs, Pagination, Checkbox, Radio, Switch, Progress, Avatar

Most of these will be needed soon for the annotation UI, data upload, pipeline configuration, and evaluation pages.

### 8. Responsive Design — Partial

- Login/Register have a nice split-panel layout that hides the branding panel on mobile.
- The sidebar is fixed at 224px with no responsive behavior — on tablets or narrow windows, it will crowd the content area.
- Project card grid uses `sm:grid-cols-2 xl:grid-cols-3` — reasonable breakpoints.

### 9. Dark Mode — Implemented but Untested Edge Cases

- The dark theme is well-defined with OKLCH values.
- **Concern:** The logo uses `brightness-0 invert` for white-on-dark treatment. This only works for simple monochrome logos. If the logo ever gets more complex, this breaks.
- **Missing:** No system-preference-change listener. If a user's OS switches to dark mode while the app is open, it won't react.

### 10. Clinical-Specific UX Patterns — Not Yet Present

These are expected to come later but worth flagging:
- **Audit trail visibility** — who changed what, when
- **PHI handling indicators** — visual cues that data is sensitive
- **Role-based UI gating** — showing/hiding actions based on permissions (currently the role badge is display-only)
- **Annotation confidence indicators** — for NLP predictions
- **Batch operation safety** — confirmations for bulk actions

---

## Summary Scorecard

| Category | Rating | Priority |
|---|---|---|
| Code quality & structure | Strong | — |
| Color contrast / WCAG | Needs improvement | High |
| Keyboard accessibility | Missing | High |
| Screen reader support | Missing | High |
| Error/success feedback | Minimal | High |
| Session security | localStorage risk | Medium |
| Component library coverage | 4 of ~20 needed | Medium |
| Form validation UX | Missing | Medium |
| Responsive sidebar | Not implemented | Medium |
| Typography (custom fonts) | Not set | Low |
| Clinical-specific patterns | Not yet (expected) | Later |

The highest-priority items are the accessibility gaps (keyboard nav, ARIA attributes, contrast ratios) and the lack of user feedback patterns (toasts, validation, loading skeletons). These affect usability for all users and are particularly important in clinical settings where mistakes have real consequences.
