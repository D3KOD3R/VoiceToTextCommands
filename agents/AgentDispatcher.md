# AgentDispatcher — Context Router

Purpose: Read the user request and route to the most relevant agent(s). Always document which agents you chose and why; do not skip routing.

Process:
1) Parse the task intent (UI/UX, install, config, persistence, code, testing, features, merge).
2) Select the matching agent(s) from Agents.md and apply their principles.
3) If multiple domains are involved, prioritize in this order: Install/Config > Persistence > Code > UI/UX > Features > Test > Merge.
4) Keep routing transparent: note which agent(s) you’re following when executing a task.

Outcome: Every task should explicitly align with the chosen agent guidance before implementation.
