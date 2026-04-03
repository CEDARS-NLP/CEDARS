# writing-clinical-ui-copy Skill

The `writing-clinical-ui-copy` skill writes and reviews UX microcopy for clinical healthcare interfaces. It enforces MSK's content guidelines — sentence case, active voice, positive framing, Oxford commas, clinical terminology ("Select" not "Click," no "Please" in instructions, no exclamation points, spelled-out dates, 12-hour lowercase am/pm) — and layers in the MSK brand voice at the restrained end of the tone spectrum.

## Supported UI elements

- Buttons and labels
- Error messages
- Tooltips
- Empty states
- Confirmation dialogs
- Notifications (success, warning, error, info)
- Onboarding copy
- Loading states

## Usage

Invoke as a slash command in VS Code Copilot Chat:

```
/writing-clinical-ui-copy Write an error message for when a patient's uploaded file exceeds the size limit
```

```
/writing-clinical-ui-copy Review: "Please Click Here to Login to Your Account!"
```

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Skill definition, procedure, content guidelines summary, brand voice mapping |
| `references/content-guidelines.md` | Full content style guide (sourced from Chicago Manual of Style, Merriam-Webster's, PRISM Readability Toolkit, and Microsoft Writing Style Guide) |
| `references/brand-voice-summary.md` | MSK brand voice summary for digital interfaces |
| `references/clinical-plain-language.md` | Plain language substitutions for medical and clinical terminology in patient-facing UI |