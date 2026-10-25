import { randomBytes } from 'node:crypto'
import { createServer } from 'node:net'
import { spawn, type ChildProcess } from 'node:child_process'
import { delimiter, join } from 'node:path'
/** live = the real Python agent (OpenAI + desktop actions); preview = the scripted fake; custom = GAZE_AGENT_CMD. */
export type AgentMode = 'live' | 'preview' | 'custom'
export const REAL_AGENT_COMMAND = 'uv run --project agent python -m gaze_agent.server'
export const FAKE_AGENT_COMMAND = 'uv run scripts/fake_agent.py'
export interface AgentLaunch { mode: AgentMode; token: string; port: number; command: string; env: Record<string, string> }
export type AgentChoice = { mode: AgentMode; command: string } | { error: string }
export const makeToken = (): string => randomBytes(32).toString('hex')
const START_HINT = 'Start with scripts/start.sh preview (fake agent) or scripts/start.sh live (real agent).'
/**
 * Which agent to spawn. `requestedMode` is GAZE_AGENT_MODE from the launcher's own environment, read
 * before .env is loaded, so a .env file can never switch on desktop control. Without a mode only an
 * explicit GAZE_AGENT_CMD runs: the real agent is never an implicit default.
 */
export function chooseAgent(requestedMode: string | undefined, env: NodeJS.ProcessEnv): AgentChoice {
  const custom = env.GAZE_AGENT_CMD?.trim() ?? ''
  switch (requestedMode?.trim() ?? '') {
    case 'live':
      return custom ? { error: 'GAZE_AGENT_MODE=live conflicts with GAZE_AGENT_CMD; unset GAZE_AGENT_CMD in the shell and .env.' }
        : { mode: 'live', command: REAL_AGENT_COMMAND }
    case 'preview': return { mode: 'preview', command: FAKE_AGENT_COMMAND }
    case 'custom': return custom ? { mode: 'custom', command: custom } : { error: 'GAZE_AGENT_MODE=custom needs GAZE_AGENT_CMD.' }
    case '': return custom ? { mode: 'custom', command: custom } : { error: `No agent selected. ${START_HINT}` }
    default: return { error: `Unknown GAZE_AGENT_MODE (use live, preview or custom). ${START_HINT}` }
  }
}
const SLOTS = ['AGENT', 'FAST', 'VISION'] as const
const EFFORTS = new Set(['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'])
/**
 * Live settings the real agent would otherwise reject only at its first model call (gaze_agent/llm.py).
 * Messages name variables, never their values.
 */
export function liveConfigProblems(env: NodeJS.ProcessEnv): string[] {
  const problems: string[] = []
  const replay = env.REPLAY ?? 'off'
  if (!['off', 'record', 'replay'].includes(replay)) problems.push('REPLAY must be off, record or replay')
  // Strict replay answers from the cache only and makes no OpenAI call.
  if (replay !== 'replay' && !env.OPENAI_API_KEY?.trim()) problems.push('OPENAI_API_KEY is missing (shell or .env)')
  for (const slot of SLOTS) {
    if (!env[`OPENAI_MODEL_${slot}`]?.trim()) problems.push(`OPENAI_MODEL_${slot} is missing`)
    const effort = env[`OPENAI_REASONING_EFFORT_${slot}`]?.trim()
    if (effort && !EFFORTS.has(effort)) problems.push(`OPENAI_REASONING_EFFORT_${slot} is invalid`)
  }
  if (env.DEMO_MODE !== undefined && !['0', '1'].includes(env.DEMO_MODE)) problems.push('DEMO_MODE must be 0 or 1')
  return problems
}
const LIVE_SETTINGS = ['OPENAI_API_KEY', ...SLOTS.flatMap(slot => [`OPENAI_MODEL_${slot}`, `OPENAI_REASONING_EFFORT_${slot}`]), 'REPLAY', 'DEMO_MODE']
/**
 * Terminal lines for the chosen agent. Never the token, the key or the custom command; for live, the
 * approved setting values and which settings the shell takes over .env (dotenv does not override).
 */
export function describeLaunch(launch: Pick<AgentLaunch, 'mode' | 'port'>, env: NodeJS.ProcessEnv, overridden: ReadonlySet<string> = new Set()): string[] {
  const where = `on 127.0.0.1:${launch.port}`
  if (launch.mode === 'preview') return [`[agent] PREVIEW: fake agent ${where}. Scripted suggestions and results; no OpenAI, no desktop actions.`]
  if (launch.mode === 'custom') return [`[agent] CUSTOM: GAZE_AGENT_CMD ${where} (command hidden; it may be a real agent).`]
  const shown = (value: string | undefined, allowed: Iterable<string>, fallback: string) =>
    value === undefined ? fallback : new Set(allowed).has(value) ? value : 'invalid'
  const efforts = SLOTS.map(slot => `${slot.toLowerCase()}=${shown(env[`OPENAI_REASONING_EFFORT_${slot}`]?.trim() || undefined, EFFORTS, 'API default')}`).join(' ')
  const shell = LIVE_SETTINGS.filter(name => overridden.has(name))
  return [
    `[agent] LIVE: real Python agent ${where}. It calls OpenAI and acts on this Mac.`,
    `[agent] REPLAY=${shown(env.REPLAY, ['off', 'record', 'replay'], 'off')} DEMO_MODE=${shown(env.DEMO_MODE, ['0', '1'], '0')}` +
      ` OPENAI_API_KEY=${env.OPENAI_API_KEY?.trim() ? 'set' : 'unset'} efforts: ${efforts}`,
    ...(shell.length ? [`[agent] The shell overrides .env for: ${shell.join(', ')}`] : [])
  ]
}
export function buildLaunch(choice: { mode: AgentMode; command: string }, port: number, token = makeToken()): AgentLaunch {
  return { ...choice, token, port, env: { GAZE_TOKEN: token, GAZE_PORT: String(port) } }
}
/** The preview's fake agent needs no credentials, so it never receives them. */
const SECRETS = ['OPENAI_API_KEY', 'OPENAI_ADMIN_KEY', 'AZURE_OPENAI_API_KEY']
export function agentEnv(launch: AgentLaunch, env: NodeJS.ProcessEnv, repo?: string): NodeJS.ProcessEnv {
  const out = { ...env, ...launch.env }
  if (launch.mode === 'preview') for (const name of SECRETS) delete out[name]
  // The real agent must import even when Python skips the editable install's .pth file
  // (e.g. a checkout in an iCloud-synced folder, where the file gets the hidden flag).
  if (launch.mode === 'live' && repo) out.PYTHONPATH = [join(repo, 'agent'), env.PYTHONPATH].filter(Boolean).join(delimiter)
  return out
}
/** Each workspace gets a free loopback port; explicit ports fall back when busy. */
export function freePort(preferred = 0): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.once('error', error => {
      if (preferred) void freePort().then(resolve, reject)
      else reject(error)
    })
    server.listen(preferred, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close(error => error ? reject(error) : resolve(port))
    })
  })
}
export function spawnAgent(launch: AgentLaunch, cwd: string, env: NodeJS.ProcessEnv): ChildProcess {
  return spawn(launch.command, { shell: true, cwd, env: agentEnv(launch, env, cwd),
    stdio: 'inherit', detached: process.platform !== 'win32' })
}
export function describeExit(code: number | null, signal: NodeJS.Signals | null): string {
  if (signal) return `was stopped by ${signal}`
  return code === 127 ? 'exited with code 127 (command not found: is uv installed and on PATH?)' : `exited with code ${code}`
}
export const running = (child: ChildProcess): boolean => !!child.pid && child.exitCode === null && child.signalCode === null
/** Signals the agent's whole process group (shell, uv and Python). */
export function killAgent(child: ChildProcess, signal: NodeJS.Signals = 'SIGTERM'): void {
  if (!child.pid) return
  try {
    if (process.platform === 'win32') child.kill(signal)
    else process.kill(-child.pid, signal)
  } catch { /* already exited */ }
}
/**
 * SIGINT first: the agent then closes its sessions, which stops a running task and releases held
 * keys. SIGTERM after `graceMs`, SIGKILL after `termMs` more. Resolves on exit or after SIGKILL.
 */
export function stopAgent(child: ChildProcess, { graceMs = 2500, termMs = 1000, kill = killAgent } = {}): Promise<void> {
  return new Promise(resolve => {
    if (!running(child)) { resolve(); return }
    const timers: ReturnType<typeof setTimeout>[] = []
    const done = () => { for (const timer of timers) clearTimeout(timer); child.off('exit', done); resolve() }
    child.once('exit', done)
    kill(child, 'SIGINT')
    timers.push(setTimeout(() => kill(child, 'SIGTERM'), graceMs))
    timers.push(setTimeout(() => { kill(child, 'SIGKILL'); done() }, graceMs + termMs))
  })
}
