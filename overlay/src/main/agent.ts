import { randomBytes } from 'node:crypto'

export const DEFAULT_PORT = 8765

export interface AgentLaunch {
  token: string
  port: number
  /** Command line to spawn; `GAZE_AGENT_CMD` overrides the real agent (spec §3/§4). */
  command: string
  env: Record<string, string>
}

/** Random 32-byte hex token, as in spec §4. */
export function makeToken(): string {
  return randomBytes(32).toString('hex')
}

export function resolveAgentCommand(env: NodeJS.ProcessEnv): string {
  const custom = env.GAZE_AGENT_CMD?.trim()
  return custom ? custom : 'uv run python -m gaze_agent.server'
}

export function buildLaunch(env: NodeJS.ProcessEnv, port: number, token = makeToken()): AgentLaunch {
  return {
    token,
    port,
    command: resolveAgentCommand(env),
    env: { GAZE_TOKEN: token, GAZE_PORT: String(port) }
  }
}
