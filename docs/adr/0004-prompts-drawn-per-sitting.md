# Prompts are drawn one at a time, independently per parent

A parent is never shown a form of questions. They are shown one prompt, and answering or skipping it draws the next — a sitting continues until the parent ends it. Prompts are drawn at random from the bank, independently for each parent, rather than both parents being given the same prompt for the day.

The draw order within a sitting: exclude prompts already answered today; prefer prompts neither answered nor skipped today; when those run out, re-offer today's skipped prompts; break ties by least-recently-answered.

## Considered Options

Forcing the day's first prompt to be the same for both parents was considered, to preserve the shared-visibility payoff of ADR-0001, and rejected in favour of keeping the model simple.

Permanently retiring answered prompts was rejected: it would exhaust a bank of ~20 prompts within weeks and leave nothing to ask. Repetition over time is intended, and variety is handled by preferring least-recently-answered.

## Consequences

Skips are recorded, not forgotten. This is both what makes the re-offer rule possible and the only way to eventually learn which prompts get reliably dodged.

Answers are stored one row per answer, keyed by parent, prompt and diary day; there is no day-entry table, because with independent draws the two parents' evenings are ragged and a per-day container would be permanently half-empty. A "day" is a query, not a row.

A diary day runs 04:00 to 04:00 rather than midnight to midnight, so an answer given at 01:30 belongs to the day that just ended.
