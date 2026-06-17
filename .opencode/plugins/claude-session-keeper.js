/**
 * OpenCode plugin — registers this repo's `skills/` so OpenCode discovers them.
 * Adapted from obra/superpowers (MIT). Install via opencode.json:
 *   { "plugin": ["claude-session-keeper@git+https://github.com/superbereza/claude-session-keeper.git"] }
 * NOTE: OpenCode's plugin API evolves — verify against your version.
 */
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const skillsDir = path.resolve(__dirname, '../../skills');

export const ClaudeSessionKeeperPlugin = async ({ client, directory }) => ({
  config: async (config) => {
    config.skills = config.skills || {};
    config.skills.paths = config.skills.paths || [];
    if (!config.skills.paths.includes(skillsDir)) config.skills.paths.push(skillsDir);
  },
});
