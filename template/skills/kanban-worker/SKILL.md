---
name: kanban-worker
description: "Kanban worker rules — force-loaded by the kanban engine on every worker and review card (--skills kanban-worker); not for other sessions."
metadata:
  hermes:
    requires_tools:
      - __manual_command_only__
---

# Kanban worker

This session was opened with `work kanban task <id>`: you are working ONE card of a kanban board.

## The card is the contract

- Read your card before anything else (`kanban_show`). Its body wins over everything else you
  were given — your profile's SOUL, any project instruction file, and this skill. Follow its
  HARD RULES and WORKER CONTRACT, and end the card exactly as its body says.
- After a context compaction, re-read the card with `kanban_show` before your next write. The
  summary that replaced the earlier turns is not the card: it keeps the goal and drops the hard
  rules.
- The kanban engine's own `AGENTS.md` ("Hermes kanban coding-team template") is loaded when
  your work directory lies inside the engine's repository. It is for work on the engine, not
  your card — ignore it. A work directory in another project may carry that project's own
  instruction files; your card says how far to follow them.

## One card, one job

- The body says which job this card is: the researcher refines the idea, the plan card plans,
  the test card writes tests, the implementation card writes the code, the review cards issue
  the verdicts, and the gates belong to a person or the driver. Whatever your profile usually
  does, do this card's job and no other. Never borrow another card's job into this session:
  never write the tests you implement against, and never certify your own card.
- The refined idea is the researcher's whole deliverable: planning, task decomposition and card
  filing belong to the plan card, and the tests and verdicts to the cards after it.
- When your card names the tests a test card staged, they are the acceptance criteria. Make them
  pass without weakening, deleting or rewriting them; a test you believe is wrong is named in your
  result, and the review decides.
- Never deploy — to a live profile, a portal bundle or any declared target root — unless the
  card records a person's approval and the deployment steps.
