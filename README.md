# kingkai

> King Kai watches the fight from his planet and speaks straight into Goku's head.
> kingkai watches Claude Code from a side pane and types straight into its prompt.

**Status: design phase. There is no code yet.**

kingkai is a terminal sidekick for [Claude Code](https://code.claude.com), built with Python and [Textual](https://textual.textualize.io):

- **See what the agent is doing, live:** the tree of agents and subagents, files read and edited, a timeline of tool calls, tokens and cost.
- **Get warned when it's stuck:** alerts for repeated identical tool calls, tool errors and retry loops.
- **Click to reference:** Alt+click an element in your local Next.js/React or Django app and `@path/to/file.tsx#L42` is pasted into the Claude Code prompt, never submitted.

See the [design spec](docs/superpowers/specs/) and the [implementation plan](docs/superpowers/plans/).

## License

[MIT](LICENSE)
