# Installing for OpenCode

No marketplace — add to your `opencode.json` (global `~/.config/opencode/opencode.json` or project):

```json
{ "plugin": ["claude-session-keeper@git+https://github.com/superbereza/claude-session-keeper.git"] }
```

Restart OpenCode. The plugin (`.opencode/plugins/claude-session-keeper.js`) registers this repo's
`skills/` directory — no symlinks. Adapted from [obra/superpowers](https://github.com/obra/superpowers) (MIT); verify against your OpenCode version.
