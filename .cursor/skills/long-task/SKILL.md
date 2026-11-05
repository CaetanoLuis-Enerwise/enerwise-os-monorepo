---
name: long-task
description: Finish a multi-step repository task with saved progress and an independent check. Use when the user asks for a long task, when work must survive a new session, or when tasks/current.md lists acceptance checks.
---

# Long task

Follow this sequence for the brief in `tasks/current.md`. Keep each implementation step small enough to review. The parent session should be Claude Opus 5.5 at medium effort. The `verifier` subagent is the independent check.

1. Read `tasks/current.md`. If it is missing, stop and report that the brief must be copied from `tasks/TEMPLATE.md` and filled in. Do not invent the task, the user, or the acceptance checks.
2. Read `AGENTS.md`, `PROGRESS.md`, and the spec files the brief names. Plan the work as a short ordered list of steps with an observable result for each step. Record that plan's first action in `PROGRESS.md` before editing production code.
3. Implement one step at a time in the package that owns the behavior. Leave research directories unchanged unless the brief explicitly includes them.
4. After the implementation steps, run the repository checks named in `AGENTS.md`:
   - `PYTHONUTF8=1 python -m unittest discover -s tests -v` from the repository root.
   - `npm run build` in `personal-power-flow` only when that change touches the frontend and `personal-power-flow/package.json` exists.
   - Do not invent a lint command. This repository does not define one.
5. Call the `verifier` subagent. Give it the brief path, the files changed, the acceptance checks, and the commands you ran. It is read-only; it returns a table and does not edit the tree.
6. Fix every row whose verdict is `failed`. Re-run the failing check, then call the verifier again. After three failed attempts at the same check, stop. Record the blocker in `PROGRESS.md` and report it. Leave `unresolved` rows visible; do not relabel them as verified.
7. Update `PROGRESS.md` with the task, output paths, completed checks, confirmed decisions, open issues, and one concrete next action.
8. Report the changed paths and the check results. Include the verifier table. A task is done only when the acceptance checks and the required repository checks passed.

Never read or write `.env` or `.env.*`. Never invent savings, prices, peak reduction, forecast accuracy, or other financial claims.
