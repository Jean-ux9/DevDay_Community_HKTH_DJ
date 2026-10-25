import { EventEmitter } from 'node:events'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { ChildProcess } from 'node:child_process'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FAKE_AGENT_COMMAND, REAL_AGENT_COMMAND, agentEnv, buildLaunch, chooseAgent, describeExit, describeLaunch,
  liveConfigProblems, running, spawnAgent, stopAgent } from './agent'
// Synthetic values only: no real key, no real agent, no Electron.
const KEY = 'synthetic-test-key-0001'
const LIVE_ENV = { OPENAI_API_KEY: KEY, OPENAI_MODEL_AGENT: 'model-a', OPENAI_MODEL_FAST: 'model-f', OPENAI_MODEL_VISION: 'model-v',
  OPENAI_REASONING_EFFORT_AGENT: 'xhigh', OPENAI_REASONING_EFFORT_FAST: 'low', OPENAI_REASONING_EFFORT_VISION: 'xhigh', REPLAY: 'off', DEMO_MODE: '1' }
describe('agent mode: the real agent only on an explicit live launch', () => {
  it('live runs the real Python agent; preview always the fake one', () => {
    expect(chooseAgent('live', {})).toEqual({ mode: 'live', command: REAL_AGENT_COMMAND })
    expect(chooseAgent('preview', {})).toEqual({ mode: 'preview', command: FAKE_AGENT_COMMAND })
    // A leftover custom command never turns the preview into something else.
    expect(chooseAgent('preview', { GAZE_AGENT_CMD: REAL_AGENT_COMMAND })).toEqual({ mode: 'preview', command: FAKE_AGENT_COMMAND })
  })
  it('without a mode, nothing is implied: an explicit GAZE_AGENT_CMD runs, otherwise it is an error', () => {
    expect(chooseAgent(undefined, { GAZE_AGENT_CMD: ' uv run scripts/fake_agent.py --delay 2 ' }))
      .toEqual({ mode: 'custom', command: 'uv run scripts/fake_agent.py --delay 2' })
    expect(chooseAgent('custom', { GAZE_AGENT_CMD: 'x' })).toEqual({ mode: 'custom', command: 'x' })
    for (const env of [{}, { GAZE_AGENT_CMD: '' }, { GAZE_AGENT_CMD: '   ' }]) {
      const choice = chooseAgent(undefined, env)
      expect(choice).toHaveProperty('error')
      expect('error' in choice && choice.error).toMatch(/No agent selected.*start\.sh preview.*start\.sh live/)
    }
  })
  it('refuses contradictory or unknown modes', () => {
    expect(chooseAgent('live', { GAZE_AGENT_CMD: 'uv run scripts/fake_agent.py' })).toHaveProperty('error')
    expect(chooseAgent('custom', {})).toHaveProperty('error')
    const unknown = chooseAgent('LIVE-ish', {})
    expect('error' in unknown && unknown.error).not.toContain('LIVE-ish')
  })
})
describe('live preflight (names only, never values)', () => {
  it('accepts a complete synthetic configuration', () => {
    expect(liveConfigProblems(LIVE_ENV)).toEqual([])
    expect(liveConfigProblems({ ...LIVE_ENV, REPLAY: undefined, DEMO_MODE: undefined, OPENAI_REASONING_EFFORT_FAST: undefined })).toEqual([])
  })
  it('a missing key is an error, except for strict replay (zero OpenAI calls)', () => {
    for (const key of [undefined, '', '   ']) {
      expect(liveConfigProblems({ ...LIVE_ENV, OPENAI_API_KEY: key })).toEqual(['OPENAI_API_KEY is missing (shell or .env)'])
    }
    expect(liveConfigProblems({ ...LIVE_ENV, OPENAI_API_KEY: undefined, REPLAY: 'replay' })).toEqual([])
    expect(liveConfigProblems({ ...LIVE_ENV, OPENAI_API_KEY: undefined, REPLAY: 'record' })).toContain('OPENAI_API_KEY is missing (shell or .env)')
  })
  it('names each missing model slot, invalid effort, REPLAY and DEMO_MODE without echoing values', () => {
    const problems = liveConfigProblems({ ...LIVE_ENV, OPENAI_MODEL_FAST: '', OPENAI_MODEL_VISION: undefined,
      OPENAI_REASONING_EFFORT_AGENT: 'secret-ish-effort', REPLAY: '', DEMO_MODE: 'yes' })
    expect(problems).toEqual(['REPLAY must be off, record or replay', 'OPENAI_REASONING_EFFORT_AGENT is invalid',
      'OPENAI_MODEL_FAST is missing', 'OPENAI_MODEL_VISION is missing', 'DEMO_MODE must be 0 or 1'])
    expect(problems.join(' ')).not.toContain('secret-ish-effort')
  })
})
describe('launch summary', () => {
  it('live: approved values, key presence and shell overrides; never the key or the token', () => {
    const launch = buildLaunch({ mode: 'live', command: REAL_AGENT_COMMAND }, 4321, 'synthetic-token-abc')
    const lines = describeLaunch(launch, LIVE_ENV, new Set(['OPENAI_API_KEY', 'DEMO_MODE', 'GAZE_SOURCE']))
    const text = lines.join('\n')
    expect(text).toContain('LIVE: real Python agent on 127.0.0.1:4321')
    expect(text).toContain('REPLAY=off DEMO_MODE=1 OPENAI_API_KEY=set efforts: agent=xhigh fast=low vision=xhigh')
    expect(text).toContain('The shell overrides .env for: OPENAI_API_KEY, DEMO_MODE')
    expect(text).not.toContain(KEY)
    expect(text).not.toContain('synthetic-token-abc')
  })
  it('preview and custom say what they are; a custom command stays hidden', () => {
    expect(describeLaunch({ mode: 'preview', port: 1 }, LIVE_ENV).join()).toMatch(/PREVIEW: fake agent.*no OpenAI, no desktop actions/)
    const custom = describeLaunch(buildLaunch({ mode: 'custom', command: 'secret-command --token x' }, 2), LIVE_ENV).join()
    expect(custom).toContain('CUSTOM')
    expect(custom).not.toContain('secret-command')
  })
  it('explains exits', () => {
    expect(describeExit(127, null)).toMatch(/command not found/)
    expect(describeExit(1, null)).toBe('exited with code 1')
    expect(describeExit(null, 'SIGKILL')).toBe('was stopped by SIGKILL')
  })
})
describe('agent environment', () => {
  it('passes token and port; the fake preview never receives credentials', () => {
    const env = { ...LIVE_ENV, OPENAI_ADMIN_KEY: 'synthetic-admin', PATH: '/bin' }
    const preview = agentEnv(buildLaunch({ mode: 'preview', command: FAKE_AGENT_COMMAND }, 5000, 't1'), env)
    expect(preview).toMatchObject({ GAZE_TOKEN: 't1', GAZE_PORT: '5000', PATH: '/bin', OPENAI_MODEL_FAST: 'model-f' })
    expect(preview).not.toHaveProperty('OPENAI_API_KEY')
    expect(preview).not.toHaveProperty('OPENAI_ADMIN_KEY')
    const live = agentEnv(buildLaunch({ mode: 'live', command: REAL_AGENT_COMMAND }, 5001, 't2'), env)
    expect(live).toMatchObject({ OPENAI_API_KEY: KEY, GAZE_TOKEN: 't2', GAZE_PORT: '5001' })
  })

  it('puts the agent package on PYTHONPATH for the real agent only', () => {
    const live = buildLaunch({ mode: 'live', command: REAL_AGENT_COMMAND }, 5001, 't2')
    expect(agentEnv(live, LIVE_ENV, '/repo dir').PYTHONPATH).toBe('/repo dir/agent')
    expect(agentEnv(live, { ...LIVE_ENV, PYTHONPATH: '/extra' }, '/repo dir').PYTHONPATH).toBe('/repo dir/agent:/extra')
    const preview = buildLaunch({ mode: 'preview', command: FAKE_AGENT_COMMAND }, 5000, 't1')
    expect(agentEnv(preview, LIVE_ENV, '/repo dir')).not.toHaveProperty('PYTHONPATH')
  })
})
class FakeChild extends EventEmitter {
  pid = 4242
  exitCode: number | null = null
  signalCode: NodeJS.Signals | null = null
}
describe('stopAgent escalation (fake child, fake timers)', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())
  it('SIGINT first and done when the agent exits', async () => {
    const child = new FakeChild(), kill = vi.fn()
    const stopped = stopAgent(child as unknown as ChildProcess, { kill })
    expect(kill.mock.calls.map(call => call[1])).toEqual(['SIGINT'])
    child.exitCode = 0; child.emit('exit', 0, null)
    await stopped
    vi.advanceTimersByTime(10_000)
    expect(kill).toHaveBeenCalledTimes(1)
  })
  it('then SIGTERM, then SIGKILL, for an agent that ignores both', async () => {
    const child = new FakeChild(), kill = vi.fn()
    const stopped = stopAgent(child as unknown as ChildProcess, { kill, graceMs: 100, termMs: 50 })
    vi.advanceTimersByTime(100)
    expect(kill.mock.calls.map(call => call[1])).toEqual(['SIGINT', 'SIGTERM'])
    vi.advanceTimersByTime(50)
    await stopped
    expect(kill.mock.calls.map(call => call[1])).toEqual(['SIGINT', 'SIGTERM', 'SIGKILL'])
  })
  it('does nothing for an agent that already exited', async () => {
    const child = new FakeChild(), kill = vi.fn()
    child.exitCode = 1
    expect(running(child as unknown as ChildProcess)).toBe(false)
    await stopAgent(child as unknown as ChildProcess, { kill })
    expect(kill).not.toHaveBeenCalled()
  })
})
// Real but harmless child processes: a tiny Node script stands in for the agent.
describe('spawnAgent with a fake agent script', () => {
  let dir = ''
  beforeEach(async () => { dir = await mkdtemp(join(tmpdir(), 'gaze-agent-test-')) })
  afterEach(async () => { await rm(dir, { recursive: true, force: true }) })
  const exited = (child: ChildProcess) => new Promise<[number | null, NodeJS.Signals | null]>(resolve => {
    if (!running(child)) resolve([child.exitCode, child.signalCode])
    else child.once('exit', (code, signal) => resolve([code, signal]))
  })
  const launchScript = async (body: string, mode: 'preview' | 'custom' = 'custom') => {
    await writeFile(join(dir, 'agent.mjs'), body)
    return buildLaunch({ mode, command: `"${process.execPath}" agent.mjs` }, 6123, 'child-token')
  }
  it('starts the command in the given directory with token, port and the environment it is allowed', async () => {
    const launch = await launchScript(`import { writeFileSync } from 'node:fs'
writeFileSync('seen.json', JSON.stringify({ token: process.env.GAZE_TOKEN, port: process.env.GAZE_PORT, key: 'OPENAI_API_KEY' in process.env }))`, 'preview')
    const child = spawnAgent(launch, dir, { PATH: process.env.PATH, OPENAI_API_KEY: KEY })
    expect(await exited(child)).toEqual([0, null])
    expect(JSON.parse(await readFile(join(dir, 'seen.json'), 'utf8'))).toEqual({ token: 'child-token', port: '6123', key: false })
  })
  it('reports a failing agent with its exit code', async () => {
    const child = spawnAgent(await launchScript('process.exit(3)'), dir, { PATH: process.env.PATH })
    const [code, signal] = await exited(child)
    expect(describeExit(code, signal)).toBe('exited with code 3')
  })
  it('stopAgent lets an agent shut down on SIGINT, and kills one that ignores it', async () => {
    const polite = spawnAgent(await launchScript(`process.on('SIGINT', () => process.exit(0)); setInterval(() => {}, 1000)`), dir, { PATH: process.env.PATH })
    await new Promise(resolve => setTimeout(resolve, 300))
    await stopAgent(polite, { graceMs: 2000, termMs: 500 })
    expect(await exited(polite)).toEqual([0, null])
    const stubborn = spawnAgent(await launchScript(`process.on('SIGINT', () => {}); process.on('SIGTERM', () => {}); setInterval(() => {}, 1000)`), dir, { PATH: process.env.PATH })
    await new Promise(resolve => setTimeout(resolve, 300))
    await stopAgent(stubborn, { graceMs: 100, termMs: 100 })
    const [, signal] = await exited(stubborn)
    expect(signal).toBe('SIGKILL')
  })
})
