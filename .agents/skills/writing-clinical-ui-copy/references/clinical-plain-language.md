# Clinical Plain Language Reference

Use this reference when writing patient-facing UI text that involves medical or clinical terminology. The goal is to use language patients already understand, without sacrificing accuracy.

## Contents

- [When to Use This Reference](#when-to-use-this-reference)
- [When Clinical Terms Are Acceptable](#when-clinical-terms-are-acceptable)
- [Plain Language Substitutions](#plain-language-substitutions)
  - [Common Medical Terms](#common-medical-terms)
  - [Common Procedural and Navigational Terms](#common-procedural-and-navigational-terms)
  - [Action Words in Clinical Contexts](#action-words-in-clinical-contexts)
  - [Phrases to Simplify](#phrases-to-simplify)
- [Applying This in UI Text](#applying-this-in-ui-text)
- [Important Notes](#important-notes)

## When to Use This Reference

- Writing patient-facing labels, instructions, tooltips, or messages that involve clinical concepts
- Reviewing existing UI text for jargon that could be simplified
- Choosing between a clinical term and a plain language alternative

## When Clinical Terms Are Acceptable

- **Clinician-facing interfaces:** Medical terminology is expected and appropriate. Do not oversimplify for clinical users — but instructional and navigational text should still follow plain language principles.
- **When the term appears in official data:** Lab result names, diagnosis codes, and medication names should match their source system. Add a plain language explanation alongside them when space allows.
- **When the plain language alternative would be less accurate:** If simplifying would change the meaning, keep the clinical term and add a brief explanation.

## Plain Language Substitutions

### Common Medical Terms

| Clinical / Technical Term | Plain Language Alternative | Notes |
|---|---|---|
| Abnormal | Not normal | |
| Acute | Sudden, short-term | |
| Administer | Give | |
| Adverse effect | Side effect, unwanted effect | |
| Benign | Not cancer, not harmful | |
| Chronic | Long-lasting, ongoing | |
| Comorbidity | Other health condition | |
| Contraindicated | Not recommended, should not be used | |
| Diagnosis | What the doctor found, your condition | |
| Edema | Swelling | |
| Efficacy | How well it works | |
| Etiology | Cause | |
| Exacerbation | Flare-up, getting worse | |
| Hemorrhage | Bleeding | |
| Hypertension | High blood pressure | |
| Hypotension | Low blood pressure | |
| Indication | Reason for use | |
| Lesion | Sore, wound, growth | Context-dependent |
| Malignant | Cancer, cancerous | |
| Metastasis | Cancer that has spread | |
| Morbidity | Illness, health problems | |
| Mortality | Death | |
| Nausea | Feeling sick to your stomach | |
| Neoplasm | Tumor, growth | |
| Onset | When it started, beginning | |
| Pathology | Lab results from tissue samples | In clinical app context |
| Prognosis | What to expect, outlook | |
| Prophylaxis | Prevention | |
| Renal | Kidney | |
| Subcutaneous | Under the skin | |
| Symptom | What you feel, sign | |
| Systemic | Throughout the body | |
| Therapy | Treatment | |
| Toxicity | Harmful effects, poisoning | |

### Common Procedural and Navigational Terms

| Clinical / Technical Term | Plain Language Alternative | Notes |
|---|---|---|
| Ambulatory | Outpatient, walk-in | |
| Biopsy | Taking a small sample of tissue to test | |
| Catheter | Thin tube | Add context about where it goes |
| Chemotherapy | Cancer treatment using medicine | Or just "chemo" if contextually clear |
| Discharge | Going home, leaving the hospital | |
| Follow-up | Next visit, check-in | |
| Imaging | Scans (X-ray, MRI, CT scan) | Be specific when possible |
| Infusion | Medicine given through an IV | |
| Inpatient | Staying in the hospital | |
| Intravenous (IV) | Through a vein, into your bloodstream | |
| Lab work | Blood tests, tests | Be specific when possible |
| Outpatient | Visit without staying overnight | |
| Post-operative | After surgery | |
| Pre-operative | Before surgery | |
| Procedure | Treatment, test | Be specific when possible |
| Radiation | Treatment using targeted energy to kill cancer cells | |
| Referral | Sending you to another doctor or specialist | |
| Screening | Test to check for a health condition | |
| Surgical | Related to surgery | |
| Vital signs | Heart rate, blood pressure, temperature | List them when possible |

### Action Words in Clinical Contexts

| Clinical / Technical Term | Plain Language Alternative |
|---|---|
| Abstain | Do not, avoid |
| Adhere to | Follow, stick to |
| Cease | Stop |
| Comply | Follow |
| Consult | Talk to, ask |
| Determine | Find out |
| Discontinue | Stop |
| Evaluate | Check, review |
| Facilitate | Help, make easier |
| Implement | Start, put in place |
| Initiate | Start, begin |
| Monitor | Watch, keep track of |
| Obtain | Get |
| Participate | Take part |
| Perform | Do |
| Prescribe | Order (medicine) |
| Provide | Give |
| Require | Need |
| Sufficient | Enough |
| Terminate | End, stop |
| Utilize | Use |

### Phrases to Simplify

| Instead of | Use |
|---|---|
| "At this point in time" | "Now" |
| "Due to the fact that" | "Because" |
| "For the purpose of" | "To" or "For" |
| "In order to" | "To" |
| "In the event that" | "If" |
| "Is able to" | "Can" |
| "It is important that" | "You should" or "You need to" |
| "On a daily basis" | "Every day" or "Daily" |
| "Prior to" | "Before" |
| "Subsequent to" | "After" |
| "With regard to" | "About" |

## Applying This in UI Text

### Example: Lab Results Screen

**Before (clinical jargon):**

> "Pathology results indicate a benign neoplasm with no evidence of malignancy."

**After (plain language):**

> "Your lab results show a growth that is not cancer."
>
> (With expandable detail: "Pathology report: Benign neoplasm, no malignancy detected")

### Example: Medication Instructions

**Before (clinical jargon):**

> "Discontinue the administration of this medication if adverse effects are observed."

**After (plain language):**

> "Stop taking this medicine if you notice side effects."

### Example: Appointment Scheduling

**Before (clinical jargon):**

> "Schedule a follow-up consultation with your referring physician subsequent to discharge."

**After (plain language):**

> "After you leave the hospital, schedule a follow-up visit with your doctor."

### Example: Tooltip on a Clinical Term

**Label:** "CBC results"

**Tooltip:** "Complete blood count — a blood test that measures your red cells, white cells, and platelets"

## Important Notes

- **Do not simplify medication names.** Use the exact name from the system. Add a plain language description of what it does if space allows.
- **Do not simplify diagnosis codes or official lab test names in data displays.** These must match the source system. Provide plain language alongside them.
- **When in doubt, use both:** Show the clinical term with a plain language explanation. This respects clinicians who may also see the screen while keeping it accessible to patients.