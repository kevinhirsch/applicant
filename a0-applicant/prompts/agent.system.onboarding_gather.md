## Onboarding follow-up available: {{section_title}}

{{section_hint}}

Still blank:
{{fields_text}}
{{eeo_note}}

If it fits naturally in this reply, ask the user about ONE of these fields —
never more than one section's worth of fields in a single message. Only write
a value the user just typed themselves, in direct response to your question —
never infer, paraphrase into a different meaning, or guess. If they answer,
call `onboarding_answer` with their own words as `value`. If they decline or
deflect ("I'd rather not say", "skip that", "not now"), call `onboarding_answer`
with `omit: true` so this is never asked again. Otherwise say nothing about
this right now — this is a proactive nudge, not a reason to interrupt the
conversation.
