### onboarding_answer:
record the user's own onboarding answer, or an explicit decline
section: one of identity, work_authorization, location, target_roles,
compensation, work_history, education, references, certifications,
key_attributes, eeo, campaign_criteria (base_resume is upload-only, never this tool)
field: the one field key being answered (omit only when declining a WHOLE section)
value: the user's own freeform words — required unless omit is true
omit: true the moment the user declines or deflects; false (default) otherwise
never infer, paraphrase, or guess a value the user did not state themselves
never ask about more than one section's fields in a single message
usage — recording an answer:
~~~json
{
    "thoughts": [
        "The user just told me their preferred work mode...",
    ],
    "headline": "Saving the user's work-mode answer",
    "tool_name": "onboarding_answer",
    "tool_args": {
        "section": "location",
        "field": "work_mode",
        "value": "remote",
    },
}
~~~
usage — recording an explicit decline:
~~~json
{
    "thoughts": [
        "The user said they'd rather not share references right now...",
    ],
    "headline": "Recording that references were declined",
    "tool_name": "onboarding_answer",
    "tool_args": {
        "section": "references",
        "omit": true,
    },
}
~~~
