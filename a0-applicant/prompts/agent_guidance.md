# Agent Guidance: Application Deferral

Do not attempt to submit or submit applications automatically until the engine reports `apply_ready` as true. Always check the current setup status first — either by calling `GET /api/setup/status` on the engine or by querying the features handler — and inspect the `apply_ready` field.

When `apply_ready` is false, the engine also returns an `apply_missing` list listing which prerequisites are not yet met (e.g., missing LLM configuration, incomplete resume, or unverified job listings). Report those missing items to the user so they know exactly what to fix before retrying.

Only proceed with automated application once `apply_ready` is true and the `apply_missing` list is empty.
