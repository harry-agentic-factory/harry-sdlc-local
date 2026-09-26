// Stub harness of a Workflow script (run-ticket.js): no LLM, no dependency (node:* only).
//
//   node run_ticket_harness.mjs --script <path> --scenario <json> [--exec]
//
// The script is evaluated as the body of an AsyncFunction(args, agent, phase, log, workflow): the
// `export` keyword in front of `const meta` is removed and the top level `return` becomes the result.
// Every agent() call is journaled as {prompt, agentType, label, phase}; phase() and log() calls are
// journaled apart (the golden only carries the agent calls). Output (stdout): {calls, result}.
//
// Scenario: {args, responses: {<label prefix>: [reply, ...]}}. The longest prefix that starts the
// label wins; its replies are consumed in order (the last one is repeated). A reply is either the
// verdict itself or, in --exec mode, {"$reply": verdict, "$doc": type, "$commit": message,
// "$files": {<path relative to the run root>: text}} for an ACTIVE role stub.
//
// Dry mode (default): `prepare:*` replies a fixed fake run, `finish:*` replies {state: "published"},
// unless the scenario gives a reply for that label.
// --exec mode: `prepare:*` / `finish:*` run the first `sdlc ...` command of the prompt for real,
// with `sdlc` replaced by $SDLC_CMD (for example `python3 -m sdlc.cli`); the reply is the JSON of
// stdout (stderr when stdout is empty). Role stubs read `--run <root>` and `CODE=<path>` from their
// prompt, write their files, commit (fixer) and `doc add` through $SDLC_CMD.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { execFileSync } from 'node:child_process'

function parseArgv(argv) {
  const o = { exec: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--script') o.script = argv[++i]
    else if (a === '--scenario') o.scenario = argv[++i]
    else if (a === '--exec') o.exec = true
    else throw new Error(`unknown option ${a}`)
  }
  if (!o.script || !o.scenario) throw new Error('usage: --script <path> --scenario <json> [--exec]')
  return o
}

const opt = parseArgv(process.argv.slice(2))
const scenario = JSON.parse(readFileSync(opt.scenario, 'utf8'))
const responses = scenario.responses || {}
const cursor = {}
const calls = []
const events = []
let prepared = 0

function pick(label) {
  let best = null
  for (const k of Object.keys(responses)) {
    if (label.startsWith(k) && (best === null || k.length > best.length)) best = k
  }
  if (best === null) return { found: false }
  const list = responses[best]
  const i = cursor[best] || 0
  cursor[best] = i + 1
  return { found: true, value: list.length ? list[Math.min(i, list.length - 1)] : null }
}

function sdlcArgv() {
  const cmd = (process.env.SDLC_CMD || 'sdlc').split(' ').filter(Boolean)
  return { file: cmd[0], pre: cmd.slice(1) }
}

function runSdlc(args) {
  const { file, pre } = sdlcArgv()
  try {
    const out = execFileSync(file, [...pre, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
    return { code: 0, stdout: out, stderr: '' }
  } catch (e) {
    return { code: e.status ?? 1, stdout: e.stdout ? String(e.stdout) : '', stderr: e.stderr ? String(e.stderr) : '' }
  }
}

function firstSdlcCommand(prompt) {
  const m = prompt.match(/`sdlc ([^`]+)`/)
  if (!m) throw new Error(`no sdlc command in prompt: ${prompt.slice(0, 120)}`)
  return m[1].split(' ').filter(Boolean)
}

function execStep(prompt) {
  const r = runSdlc(firstSdlcCommand(prompt))
  const text = r.stdout.trim() ? r.stdout : r.stderr
  try { return JSON.parse(text) } catch { return { error: text.trim() } }
}

function fakeRun(label) {
  prepared += 1
  const n = prepared
  const repo = (scenario.args && scenario.args.repoName) || 'app-repo'
  const root = `/runs/${n}`
  const branch = (scenario.args && scenario.args.branch) || `feat/${(scenario.args && scenario.args.ticket) || 'T'}`
  return {
    run_uid: `20260101-000000-00000${n}`, root, in: `${root}/in`, rw: `${root}/rw`, out: `${root}/rw/out`,
    code: `${root}/rw/code`, scratch: `${root}/rw/scratch`, warnings: [],
    repos: { [repo]: { role: 'target', path: `${root}/rw/code/${repo}`, branch, base: 'main', head: 'h'.repeat(40), created: false } },
  }
}

function field(prompt, re) {
  const m = prompt.match(re)
  return m ? m[1] : null
}

function activeStub(prompt, value) {
  if (!value || typeof value !== 'object' || !('$reply' in value)) return value
  const root = field(prompt, /--run (\S+?)[`\s]/)
  const code = field(prompt, /CODE=(\S+?)[`\s]/)
  const runUid = root ? root.split('/').pop() : ''
  for (const [rel, text] of Object.entries(value.$files || {})) {
    const p = join(root, rel)
    mkdirSync(dirname(p), { recursive: true })
    writeFileSync(p, text)
  }
  if (value.$commit) {
    writeFileSync(join(code, 'fix.txt'), `${value.$commit}\n`)
    const git = (...a) => execFileSync('git', ['-C', code, '-c', 'user.name=t', '-c', 'user.email=t@t', ...a], { stdio: 'pipe' })
    git('add', '-A')
    git('commit', '-q', '-m', value.$commit)
  }
  if (value.$doc) {
    const draft = join(root, 'rw', 'scratch', `${value.$doc}.md`)
    writeFileSync(draft, `## Recap\n${value.$doc} by stub\n`)
    const r = runSdlc(['doc', 'add', value.$doc, draft, '--run', root])
    if (r.code !== 0) throw new Error(`doc add failed: ${r.stderr}`)
  }
  return JSON.parse(JSON.stringify(value.$reply).split('{RUN_UID}').join(runUid))
}

async function agent(prompt, opts = {}) {
  const label = opts.label || ''
  calls.push({ prompt, agentType: opts.agentType ?? null, label, phase: opts.phase ?? null })
  const r = pick(label)
  const step = label.startsWith('prepare:') || label.startsWith('finish:')
  const rw = step && label.split(':').length >= 3
  if (opt.exec && rw && !r.found) return execStep(prompt)
  if (r.found) return opt.exec ? activeStub(prompt, r.value) : r.value
  if (rw && label.startsWith('prepare:')) return fakeRun(label)
  if (rw) return { state: 'published' }
  return null
}

const phase = (title) => { events.push({ phase: title }) }
const log = (msg) => { events.push({ log: String(msg) }) }
const workflow = async () => { throw new Error('nested workflow() is not simulated') }

const src = readFileSync(opt.script, 'utf8').replace(/^export const meta/m, 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const body = new AsyncFunction('args', 'agent', 'phase', 'log', 'workflow', src)
const result = await body(scenario.args || {}, agent, phase, log, workflow)
process.stdout.write(JSON.stringify({ calls, result }, null, 2) + '\n')
