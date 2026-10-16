# Pausing at the usage limit, and "continue"

The owner's Claude plan has a 5-hour usage limit and a weekly one. Hitting either stops Claude Code in the middle of whatever it was doing. This file makes those stops clean:
- progress is always written down
- Claude pauses on its own at 90%
- the owner only has to say **continue** once the limit resets

## How you know the usage

You can't see plan usage yourself, so never guess it. The status line saves the numbers after every reply. When a limit reaches 90%, the usage guard hook (`.claude/hooks/usage_guard.py`) adds a note like this:

> Plan usage: 5-hour limit at 91% (resets 13:40). ...

No note means usage is under 90% or the numbers aren't available. Keep working either way.

## Always: keep docs/PROGRESS.md current

Update [PROGRESS.md](PROGRESS.md) every time you finish a step and commit, not only when pausing. A limit can still cut you off mid-step, because one large command or subagent run can jump past 90% in one go. The file has to be good enough to resume from at any moment.

Keep it short: replace old content instead of adding a diary. Git history and pull requests hold the details.

## At 90%: write it up and stop

When the note appears:

1. **Start nothing new.** If the current edit needs only a few more tool calls, finish it. Otherwise leave it where it is.
2. **Run the fast tests** (`uv run pytest -m "not slow"`) and note the result.
3. **Commit** everything to the current branch, never `main`. Unfinished work gets a message starting with `wip:`.
4. **Update docs/PROGRESS.md:**
   - set the state to "paused (usage)"
   - what's done
   - what's half-done and where
   - the exact next step
   - anything the owner has to do

   Commit it, then **push the branch** (`git push -u origin <branch>`, never `main`, never forced) so the work is backed up.
5. **Stop** with one short message and nothing else, for example:
   `Paused at 91% of the 5-hour limit. It resets at 13:40. Say "continue" after that.`

If the fast tests fail because of half-done work, the Stop hook blocks your first attempt to stop. Reply in one line naming the failing tests (they're already in PROGRESS.md) and stop again.

Never skip, weaken or delete tests to pause faster, and never rewrite history.

## When the owner says "continue"

1. Read docs/PROGRESS.md, then run `git status` and `git branch --show-current`.
2. If the usage note says a limit is still at 90% or more, it hasn't reset yet. Tell the owner the reset time in one line and wait. Go on only if he says **continue anyway**.
3. Otherwise set the state back to "working" and carry on from **Next step**. Don't redo finished steps. Reread SPEC.md or DECISIONS.md only if the next step needs them.

The same applies after a compaction or in a new session: start from PROGRESS.md.
