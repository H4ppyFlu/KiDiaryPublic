# One shared diary, not two private ones

Both parents write into a single diary and each can read everything the other has written; there are no private entries and no per-parent diaries. The alternative — two parallel private diaries sharing an app — would reduce Kidiary to a note-taking tool that happens to have two logins, and would lose the thing neither parent can produce alone: what the other one noticed while you weren't in the room.

## Consequences

Answers are still individually authored — an answer belongs to exactly one parent — so "shared" means jointly readable, not jointly written.

Prompts are drawn independently per parent (see ADR-0004), so in practice the two parents are rarely answering the same prompt on the same evening. This was a deliberate choice, made knowing it weakens the shared-visibility payoff; the option of forcing a shared first prompt each day was considered and rejected as an unnecessary rule. Don't "fix" the independent draw back into a shared one without revisiting this.

A per-answer "keep this private" flag was left out on purpose. It is easy to add later and hard to justify before the need is actually felt.
