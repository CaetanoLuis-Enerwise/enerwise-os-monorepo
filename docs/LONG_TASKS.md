# Long tasks in Cursor

Use this procedure when a change is too large for one uninterrupted session. The parent agent is Claude Opus 5.5 at medium effort. Progress is saved in `PROGRESS.md`, and a fresh session continues from that file.

## Start

1. Copy `tasks/TEMPLATE.md` to `tasks/current.md`.
2. Fill in every section of `tasks/current.md`. Acceptance checks must be observable: a command and the result that counts as success, a path that must exist, or a field and the value it must have.
3. Open a new Agent chat in this repository.
4. Select Claude Opus 5.5 and set reasoning effort to medium. In the model picker this is the medium-effort variant of Opus 5.5. Keep the parent session at medium effort unless the task brief says otherwise. The `verifier` subagent is configured separately at high effort.
5. Ask the agent to follow the `long-task` skill, or invoke `/long-task`.

The skill reads the brief, plans, implements in small steps, runs the checks in `AGENTS.md`, calls the `verifier` subagent, fixes failed checks, updates `PROGRESS.md`, and reports changed paths plus check results.

## Fill `tasks/current.md`

| Section | What to write |
| --- | --- |
| Task | The change or question, specific enough that two readers would expect the same result. |
| User | Who uses the result and what they will do with it. |
| Deliverable | Files, endpoints, or documents that must exist at the end. |
| Acceptance | One observable check per line. Include the evidence that proves it. |
| Constraints | Modules to leave alone, safety limits, and claims that must not be invented. |

Replace the whole brief when a new task starts. Keep durable repository rules in `AGENTS.md`.

## Resume

Start a new Agent chat in the same repository. Select Claude Opus 5.5 at medium effort, then paste:

```text
Read PROGRESS.md and the files it references. Continue from the recorded next action and update PROGRESS.md.
```

`PROGRESS.md` records the task, outputs, completed checks, confirmed decisions, open issues, and one next action. Update it after each meaningful stage so the next session does not restart the task.

## Done

Done means the acceptance checks in `tasks/current.md` were observed and the repository checks in `AGENTS.md` passed. Those checks are:

- From the repository root: `PYTHONUTF8=1 python -m unittest discover -s tests -v`
- For a frontend change, and only when `personal-power-flow/package.json` is present: `npm run build` in `personal-power-flow`

This repository does not define a lint command. Do not treat an invented lint run as proof.

If the same check still fails after three attempts, the agent stops and reports the blocker in `PROGRESS.md`. The task stays unfinished until that check passes.

The `verifier` subagent is read-only. It may run the checks above and must return a table:

| criterion | verdict | evidence | required fix |

Verdicts are `verified`, `failed`, or `unresolved`. The parent agent applies required fixes. It does not edit files through the verifier.

## Secrets and claims

Do not read, edit, or commit `.env` or `.env.*`. `.cursorignore` keeps those files out of agent file tools. Checked-in templates `.env.example` and `.env.local.template` stay visible when they exist. Do not print secret values with the terminal.

Do not invent savings, prices, peak reduction, forecast accuracy, or other financial claims. Cite a figure only when a file already in the repository contains it, and name that file.
