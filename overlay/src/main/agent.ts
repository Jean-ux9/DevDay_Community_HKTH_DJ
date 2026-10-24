import { randomBytes } from 'node:crypto'
import { createServer } from 'node:net'
import { spawn, type ChildProcess } from 'node:child_process'
export interface AgentLaunch { token: string; port: number; command: string; env: Record<string, string> }
export const makeToken = (): string => randomBytes(32).toString('hex')
export const resolveAgentCommand = (env: NodeJS.ProcessEnv): string =>
  env.GAZE_AGENT_CMD?.trim() || 'uv run --project agent python -m gaze_agent.server'
export function buildLaunch(env: NodeJS.ProcessEnv, port: number, token = makeToken()): AgentLaunch {
  return { token, port, command: resolveAgentCommand(env), env: { GAZE_TOKEN: token, GAZE_PORT: String(port) } }
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
  return spawn(launch.command, { shell: true, cwd, env: { ...env, ...launch.env },
    stdio: 'inherit', detached: process.platform !== 'win32' })
}
export function killAgent(child: ChildProcess): void {
  if (!child.pid) return
  try {
    if (process.platform === 'win32') child.kill('SIGTERM')
    else process.kill(-child.pid, 'SIGTERM')
  } catch { /* already exited */ }
}
