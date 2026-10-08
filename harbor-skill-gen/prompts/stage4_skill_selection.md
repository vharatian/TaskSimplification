# Stage 4 — choose 2-3 skills per task

You pick which skills from `skills/` each task receives. The chosen skills are copied into the
task's skills directory; the agent sees each one's name and description and opens it when it
judges it relevant.

## Why only 2-3

Published skill benchmarks find the gain comes from a few focused skills: 2-3 relevant skills
helped far more than 4 or more, "comprehensive" skill bundles averaged below the no-skill
baseline, and similar-looking skills compete for the agent's attention. A skill that does not
match the task's domain adds noise, not help (a CSS-animation skill does nothing for an
infrastructure task).

## What you may look at

Only what the agent itself will see: the task's `instruction.md`, `environment/spec.md`,
and its dependency pins (`environment/lock.txt`, `environment/build_requires.txt`). Do NOT
choose based on the task's failed runs, verifier tests or oracle. Selection must be something
a person could do before ever running the task; otherwise the experiment measures leakage, not
skill uplift.

## How to choose

1. List the task's domains: the third-party libraries, standard-library areas, frameworks and
   protocols the spec says the package uses (e.g. an ORM driver, a web framework, a tokenizer,
   a CLI library, a serialisation library).
2. Read every skill's description. Score each one on whether its trigger condition is clearly
   met by step 1. Ecosystem skills need a concrete match (the library is pinned or the spec
   uses the protocol); process skills match almost every task, so take at most one of them.
3. Take the best 2-3. If fewer clearly match, take fewer. Never pad.
4. If two candidates overlap heavily, keep the more specific one.

## Output

Write `selection.json` in the work dir:

```json
{
  "<task>": ["skill-name-a", "skill-name-b"],
  "_reasons": {"<task>": {"skill-name-a": "spec pins X and section N uses it for Y"}}
}
```

Every reason must cite something in the instruction, spec or lock file. Then run
`scripts/build_skills_dir.py`.
