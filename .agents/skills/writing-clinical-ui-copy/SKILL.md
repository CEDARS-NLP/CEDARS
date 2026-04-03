---
name: writing-clinical-ui-copy
description: "Writes and reviews UX microcopy for clinical healthcare interfaces. Use when writing button labels, error messages, tooltips, empty states, confirmation dialogs, notifications, onboarding copy, loading states, or reviewing existing UI text against content style and brand voice rules. Enforces sentence case, active voice, positive framing, Oxford commas, clinical terminology (Select not Click, no Please in instructions, no exclamation points, spelled-out dates, 12-hour lowercase am/pm)."
argument-hint: "Describe the UI element and context, or paste existing microcopy to review"
---

# Writing Clinical UI Copy

Write new microcopy or review existing UI text for clinical healthcare applications, enforcing content style rules and layering in a warm-but-restrained brand voice.

## When to Use

- Writing new UI text: buttons, error messages, tooltips, empty states, confirmation dialogs, notifications, onboarding flows, loading states
- Reviewing or rewriting existing microcopy for style compliance
- Checking terminology consistency across an interface
- Adapting marketing or documentation copy into UI-appropriate language

## Inputs

The user will provide one of:
1. **A UI element type + context** — e.g., "Write an error message for when a patient's insurance can't be verified"
2. **Existing microcopy to review** — e.g., "Review this button label: 'Click Here to Submit Form!'"
3. **A batch of UI strings** — e.g., a list of labels, messages, or an entire screen's copy

## Procedure

### Step 1 — Identify the element type and context

Determine:
- **Element type:** button, error message, tooltip, empty state, confirmation dialog, notification (success/warning/error/info), onboarding copy, loading state, label, heading, or other
- **User context:** What is the user doing? What clinical workflow is this part of?
- **Emotional moment:** Is this a functional/neutral moment or a moment where warmth matters (onboarding, support, reassurance)?

### Step 2 — Load references

Read the full content guidelines and brand voice summary to ground your output:
- [Content guidelines](./references/content-guidelines.md) — all editorial rules for capitalization, terminology, punctuation, formatting, readability, and the writing checklist
- [Brand voice summary](./references/brand-voice-summary.md) — MSK brand character, tone spectrum, communication intents, and digital UI boundaries
- [Clinical plain language reference](./references/clinical-plain-language.md) — consult when choosing terminology for patient-facing or clinician-facing UI text

### Step 3 — Apply content guidelines

Every piece of microcopy MUST pass ALL rules defined in `content-guidelines.md`. These are non-negotiable and override brand voice when in conflict.

**Critical rules to never miss** (the most commonly violated):
- **Sentence case** for all UI text — no title case except proper nouns and acronyms
- **"Select"** not "Click," "Tap," or "Press"
- **No "Please"** in instructional UI text
- **No exclamation points** — ever, in any UI element
- **No periods** on buttons, labels, tooltips, or list items
- **Active voice** and **positive framing** throughout
- **Oxford comma** in all lists of three or more

For the complete set of rules including formatting (dates, times, numbers), punctuation, acronyms, readability targets, contractions, text alignment, parallel structure, and the glossary of required terminology, consult the full content guidelines.

### Step 4 — Layer in brand voice

After the content guidelines are satisfied, apply brand voice — but only where it adds value, never where it adds words.

**Default tone: restrained end of the spectrum.** Calm, competent, trustworthy.

| UI context | Tone dial | Brand tactics to apply |
|---|---|---|
| Buttons, labels, form fields | Minimal — functional clarity only | None; content guidelines are sufficient |
| Error messages | Restrained + supportive | "Humanize directions" — guide to resolution like explaining to a friend |
| Tooltips | Restrained — informational | "Speak person to person" — conversational but brief |
| Empty states | Slightly warm | "Warm welcome" — reassure and guide next action |
| Confirmation dialogs | Restrained | "Plan your unique path" — clear sequential steps |
| Notifications (success) | Slightly warm | "Enduring care" — acknowledge completion warmly |
| Notifications (error/warning) | Restrained + supportive | "Relentlessly reassure" — make clear we're helping resolve this |
| Onboarding copy | Warm | "Safe space" + "Warm welcome" — human connection matters here |
| Loading states | Minimal — functional | Brief reassurance only; no marketing language |

**Brand voice boundaries:**
- If a brand tactic would violate any content guideline rule, the content guideline wins
- Never use marketing-level emotional language in functional UI
- Users should feel supported, never sold to
- The brand voice adds warmth but never adds unnecessary words

### Step 5 — Format the output

For **new microcopy**, provide:
1. The recommended copy
2. Which content guidelines shaped it
3. Which brand voice tactics were applied (if any)
4. One alternative version if the element type benefits from options (e.g., error messages, empty states)

For **microcopy review**, provide:
1. A pass/fail for each content guideline rule, flagging every violation
2. The specific rule violated with the correct alternative
3. A rewritten version that passes all rules
4. Brand voice notes (if the tone could be improved)

Format reviews as a table when multiple strings are provided:

| Original | Issues | Rewritten | Rules applied |
|---|---|---|---|
| Click Submit! | "Click" → "Select"; exclamation point | Select submit | Terminology, Punctuation, Capitalization |

### Step 6 — Final checklist

Before delivering, verify every piece of output against this checklist. **If any item fails, fix it and re-run the full checklist before delivering.**

- [ ] Sentence case (no title case except proper nouns)
- [ ] No "Click," "Tap," "Press" — use "Select"
- [ ] No "Please" in instructional text
- [ ] No exclamation points
- [ ] No periods on buttons, labels, tooltips, or list items
- [ ] Active voice throughout
- [ ] Positive framing (what to do, not what not to do)
- [ ] Oxford commas in all lists
- [ ] Dates spelled out (month name, not numeric)
- [ ] Times in 12-hour lowercase am/pm with minutes
- [ ] Numbers zero–nine spelled out (numerals for 10+); exception: always use numerals for all numbers 1–9 in patient-facing text
- [ ] Acronyms defined at first use
- [ ] Second person ("you/your") for user-facing text
- [ ] 10–20 words per sentence max (target 15 for clinical UI)
- [ ] Brand voice appropriate to element type and emotional moment
- [ ] No superlatives, no jargon, no marketing language in functional UI
- [ ] No ampersands (&) or plus signs (+) in labels or headings
- [ ] Parallel structure for headings and lists at the same level
- [ ] Contractions used appropriately (not in destructive actions or legal text)

## Element-Type Quick Reference

### Buttons
- Sentence case, no period
- Verb-first when possible: "Save changes", "Create account", "Sign in"
- 1–3 words preferred, 4 max
- Use "Select" language in surrounding instructions, never "Click"

### Error messages
- State what happened + how to fix it
- Positive framing: "Enter a valid email address" not "Invalid email"
- No blame language, no exclamation points
- Keep under 20 words

### Tooltips
- One sentence, no period
- Explain what the element does, not how to use it
- Under 15 words

### Empty states
- Acknowledge the empty state briefly
- Guide the user to the next action
- Slightly warm tone permitted
- Example: "No appointments scheduled yet. Select a date to get started"

### Confirmation dialogs
- Title: describe the action ("Remove patient record?")
- Body: state consequence clearly in 1–2 sentences
- Buttons: specific verbs, not "OK" / "Cancel" — use "Remove" / "Keep record"

### Notifications
- **Success:** brief confirmation, optionally warm: "Your changes have been saved"
- **Warning:** state the issue + recommended action
- **Error:** state what went wrong + how to resolve it
- **Info:** state the fact concisely

### Onboarding copy
- Warmer tone permitted
- Use "Welcome" tactics from brand voice
- Guide users step by step
- Keep each step to one sentence

### Loading states
- Brief, functional: "Loading your records" or "Updating results"
- No exclamation points, no "please wait"
- Under 5 words when possible