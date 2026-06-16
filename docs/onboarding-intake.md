# Workday-Ready Onboarding Intake Schema

Source: master spec **FR-ONBOARD-1/2/3** (§3.8), §11 (Workday-ready onboarding is heavier by design), and the `onboarding_profiles` table (§8). Seeded from the `kevinhirsch/ai-job-search` `CLAUDE.md` candidate-profile schema (Identity, Education, Experience, Skills, Certifications, Behavioral Profile, Target Sectors, Deal-breakers) and **extended to be Workday-complete** — enough to finish a Workday application with minimal soft-error interruptions.

## Properties

- **Comprehensive and Workday-ready from the very beginning** (FR-ONBOARD-1). The deliberate trade (§11): a longer setup in exchange for far fewer soft-error interruptions on early applications, for a Workday-first MVP.
- **Persistent and resumable across steps** (FR-ONBOARD-2): the wizard state lives in `onboarding_profiles` with a completion flag.
- **Gates automated work** (FR-ONBOARD-2): the completion flag **MUST be set before any automated work begins**.
- **Bootstraps the attribute cloud** (FR-ONBOARD-3): the uploaded base resume is parsed to seed the per-campaign attribute cloud, and parsed data is reconciled with interview answers.
- **Per campaign** (FR-CRIT-4): the profile is campaign-scoped.

## Schema

### 1. Identity & contact
- Full legal name; preferred name.
- Email, phone.
- Mailing address (street, city, state/region, postal code, country).
- LinkedIn / portfolio / GitHub URLs; LinkedIn headline.
- Languages (with proficiency).

### 2. Work authorization
- Authorized to work in [country]? (yes/no)
- Will you now or in the future require sponsorship? (yes/no)
- Visa/status type (if applicable).
- Other countries authorized to work in (if relevant to remote roles).

> Factual screening questions (work authorization, availability) fill directly from these stored attributes (FR-ANSWER-1).

### 3. Location & work-mode preferences
- Current location; commute constraints.
- Willing to relocate? (yes/no; preferred locations).
- Work mode preference: remote / hybrid / onsite (and acceptable set).
- Time zone / working-hours constraints.

### 4. Target roles / titles
- Target job titles.
- Seniority level(s).
- Adjacent/acceptable titles.

### 5. Compensation
- Salary floor (hard minimum).
- Desired salary / range.
- Currency; base vs total-comp basis.

> Informs salary-floor/desired-salary handling (the ai-job-search `salary_lookup.py` pattern, per §5.1).

### 6. Full work history (with dates) — Workday-critical
For **each** position (most recent first):
- Job title.
- Company / employer.
- Location.
- Start date (month/year) and end date (month/year, or "present").
- Employment type (full-time, part-time, contract, internship).
- Key responsibilities and achievements.
- Reason for leaving (optional).
- Manager name + contact (optional; some Workday tenants ask).

> Full dated history is what lets the engine complete Workday's experience pages without soft errors (§11).

### 7. Education
For each entry (most recent first):
- Degree level and field.
- Institution.
- Start/end years (or expected).
- Thesis title / key topics (optional).
- GPA / honors (optional).

### 8. References
For each reference:
- Name, relationship, company/title.
- Email and/or phone.
- Note whether contactable now.

### 9. Certifications
- Certification name, issuing body, hours (if applicable), completion/expiry date.

### 10. Key attributes & professional voice
- Technical skills (primary / secondary / domain / software/tools).
- Behavioral profile (traits, strengths, growth areas, ideal environment).
- What excites you / motivations.
- Publications and awards (optional).
- These seed the attribute cloud and the voice corpus for generation (FR-RESUME-5).

### 11. Explicit EEO / voluntary self-identification answers
- Race/ethnicity.
- Gender.
- Veteran status.
- Disability status.

> **Default for every EEO field: "decline to self-identify"** unless the user explicitly sets otherwise. These are **filled only from the user's explicit stored answers, never AI-guessed** (FR-ATTR-6). Stored with `is_sensitive` true (§8).

### 12. Base resume
- Upload the base resume (docx).
- On upload, **detect required fonts and prompt the user to upload any missing ones** (FR-FONT-1), confirming once installed.
- The system **compiles the LaTeX conversion and presents it for accept/reject** (FR-RESUME-3a): accept → LaTeX becomes the campaign's primary engine; reject → fall back to the docx engine.
- The resume is **parsed to bootstrap the attribute cloud**, reconciled with the interview answers (FR-ONBOARD-3).

### 13. Initial campaign criteria
- Initial search criteria (human-readable, editable later; FR-CRIT-1/2).
- Target sectors and example companies.
- Deal-breakers / hard constraints.
- Run mode (24/7 / fixed duration / until N viable), throughput target (FR-AGENT-1/2).
- Discovery source selections (FR-DISC-2).

## Wizard sequencing (FR-OOBE-2)

The onboarding intake is **step 4** of the setup wizard, after: (1) LLM provider/model/key, (2) notification channels, (3) font upload/management. Channels must be configured and onboarding complete before automated work begins (FR-OOBE-3, FR-ONBOARD-2).

## Origin note

Structure seeded from `kevinhirsch/ai-job-search` `CLAUDE.md` candidate-profile schema (consulted per §5.1: "a near-ready template for the Workday-ready onboarding intake and the campaign attribute cloud"). Extended here with work-authorization, dated full work history, references, location/work-mode, compensation floor, explicit EEO answers, and base-resume conversion gate to reach Workday completeness. The ai-job-search repo is a manual CLI tool, not an architecture model — only the profile schema, LaTeX template, and validation rigor are reused (§5.1).
