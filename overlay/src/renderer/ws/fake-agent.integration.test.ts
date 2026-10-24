import { spawn, type ChildProcess } from 'node:child_process'
import { createServer } from 'node:net'
import { resolve } from 'node:path'
import { randomBytes } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import WebSocket from 'ws'
import { GazeWsClient, type SocketLike } from './client'
import type { SessionState } from './session'
let child: ChildProcess
let client: GazeWsClient
const until = (predicate: (state: SessionState) => boolean, timeout = 10000): Promise<SessionState> => new Promise((resolve, reject) => {
  if (predicate(client.getState())) { resolve(client.getState()); return }
  const timer = setTimeout(() => { off(); reject(new Error(`Fake-agent timeout: ${JSON.stringify(client.getState())}`)) }, timeout)
  const off = client.subscribe(state => { if (predicate(state)) { clearTimeout(timer); off(); resolve(state) } })
})
beforeAll(async () => {
  const port = await new Promise<number>(resolve => {
    const server = createServer()
    server.listen(0, '127.0.0.1', () => { const address = server.address() as { port: number }; server.close(() => resolve(address.port)) })
  })
  const token = randomBytes(16).toString('hex')
  // Only the scripted fake server is launched. It has no desktop-action dependencies.
  child = spawn('uv', ['run', 'scripts/fake_agent.py', '--quiet', '--delay', '0.01'], {
    cwd: resolve(import.meta.dirname, '../../../..'),
    env: { ...process.env, GAZE_PORT: String(port), GAZE_TOKEN: token }, stdio: ['ignore', 'ignore', 'pipe']
  })
  client = new GazeWsClient({ url: `ws://127.0.0.1:${port}/?token=${token}`, createSocket: url => new WebSocket(url) as unknown as SocketLike })
  client.start()
  await until(state => state.ready)
}, 15000)
afterAll(async () => {
  client?.stop()
  if (child && child.exitCode === null) { child.kill('SIGTERM'); await new Promise<void>(resolve => child.once('exit', () => resolve())) }
})
describe('TS client against task D live fake agent', () => {
  it('requests suggestions and completes a fake music task', async () => {
    expect(client.suggestNow()).toBe(true)
    expect(client.getState().suggestPending).toBe(true)
    const suggestions = await until(state => !!state.list && !state.suggestPending)
    expect(suggestions.list?.source).toBe('suggestions')
    client.setMode('type'); client.resetLocal()
    client.send('intent_submit', { text: 'Play my focus playlist' })
    const plans = await until(state => state.list?.source === 'plans')
    const plan = plans.list!.items.find(plan => plan.kind === 'task')!
    expect(client.selectPlan(plans.list!.listId, plan.id)).toBe(true)
    const result = await until(state => !!state.result)
    expect(result.result?.ok).toBe(true)
    expect(result.result?.summary).toContain('Playing')
  })
  it('reaches fake BUY confirmation, STOP wins, and late CONFIRM is refused', async () => {
    client.resetLocal()
    client.send('intent_submit', { text: 'Tickets for my favorite artist' })
    const plans = await until(state => state.list?.source === 'plans')
    client.selectPlan(plans.list!.listId, plans.list!.items.find(plan => plan.kind === 'task')!.id)
    const choice = await until(state => !!state.choice)
    expect(client.respondChoice(choice.choice!.options[0]!.id)).toBe(true)
    const confirm = await until(state => !!state.confirm)
    expect(confirm.confirm?.demo_noop).toBe(true)
    expect(client.sendStop('gaze')).toBe(true)
    expect(client.respondConfirm(true)).toBe(false)
    await until(state => state.task?.state === 'stopped' || state.result !== null)
  })
})
