### onboarding_next:
check what onboarding intake is still open (read-only, writes nothing)
returns the next required section still owed an answer plus its blank fields
or "nothing outstanding" once every required section is done or declined
use at the start of a session or when the user asks what's still needed
usage:
~~~json
{
    "thoughts": [
        "Let's see what's still outstanding in onboarding...",
    ],
    "headline": "Checking what onboarding still needs",
    "tool_name": "onboarding_next",
    "tool_args": {},
}
~~~
