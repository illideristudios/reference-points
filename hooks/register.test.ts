import { expect, mock, test } from 'claude-code/testing'

const TRANSCRIPT = '/sessions/abc.jsonl'

// Answer beneath the mod: the session start, and a submit that echoes what reached
// the bottom of the chain, so the test sees the hook's changes.
// The engine finding no address in a prompt: it prints nothing and succeeds.
function quiet(on) {
  on('process.run', () => ({ value: { exitCode: 0, stdout: '', stderr: '' } }))
}

function echoSubmit(on) {
  on('classic.SessionStart', () => ({}))
  on('session.id', () => ({ value: 'abc' }))
  on('prompt.submit', ($, e) => ({ text: e.text, context: e.context }))
}

test('an address in the prompt arrives with its content attached', async ($, on) => {
  let call
  on('process.run', ($, e) => {
    call = e
    return { value: { exitCode: 0, stdout: '[N1-S1.P2]\nThe second half.\n', stderr: '' } }
  })
  mock.store(on)
  echoSubmit(on)

  await $.classic.SessionStart({ source: 'startup', transcript_path: TRANSCRIPT })
  const out = await $.prompt.submit({ text: 'what did N1-S1.P2 mean?', wait: false, origin: { kind: 'user' } })

  expect(call.argv.slice(1)).toEqual(['expand', TRANSCRIPT])
  expect(call.init.stdin).toBe('what did N1-S1.P2 mean?')
  expect(out.text).toBe('what did N1-S1.P2 mean?')
  expect(out.context.slice(1)).toEqual(['[N1-S1.P2]\nThe second half.'])
})

test('a bad address drops the prompt with the engine message', async ($, on) => {
  on('process.run', () => ({
    value: { exitCode: 1, stdout: '', stderr: 'MISSING: no P9 in N1-S1\n  -> try N1-S1.P2\n' },
  }))
  mock.store(on)
  echoSubmit(on)

  await $.classic.SessionStart({ source: 'startup', transcript_path: TRANSCRIPT })
  const out = await $.prompt.submit({ text: 'and N1-S1.P9?', wait: false, origin: { kind: 'user' } })

  expect(out.drop).toBe('MISSING: no P9 in N1-S1\n  -> try N1-S1.P2')
})

test('only a prompt the user typed is scanned for addresses', async ($, on) => {
  let spawned = 0
  on('process.run', () => {
    spawned++
    return { value: { exitCode: 0, stdout: '', stderr: '' } }
  })
  mock.store(on)
  echoSubmit(on)

  await $.classic.SessionStart({ source: 'startup', transcript_path: TRANSCRIPT })
  // A notification, a peer's message or a pasted log is not the user citing something.
  const note = await $.prompt.submit({ text: 'saved N1.P2 to disk', wait: false, origin: { kind: 'task-notification' } })
  expect(spawned).toBe(0)
  expect(note.context).toBeUndefined()

  // The mod holds no grammar, so the engine decides what is an address; it says nothing here.
  const typed = await $.prompt.submit({ text: 'just a question', wait: false, origin: { kind: 'user' } })
  expect(spawned).toBe(1)
  expect(typed.context).toHaveLength(1) // only the one-time NOTE
})

test('the model is told once per conversation that the viewer labels replies', async ($, on) => {
  quiet(on)
  mock.store(on)
  echoSubmit(on)

  await $.classic.SessionStart({ source: 'startup', transcript_path: TRANSCRIPT })
  const first = await $.prompt.submit({ text: 'hello', wait: false, origin: { kind: 'user' } })
  const second = await $.prompt.submit({ text: 'again', wait: false, origin: { kind: 'user' } })
  expect(first.context).toHaveLength(1)
  expect(first.context[0]).toMatch(/do not write N<turn>-S<n> labels/)
  expect(second.context).toBeUndefined()

  await $.classic.SessionStart({ source: 'clear', transcript_path: TRANSCRIPT })
  const cleared = await $.prompt.submit({ text: 'fresh', wait: false, origin: { kind: 'user' } })
  expect(cleared.context).toHaveLength(1)
})

// --- display: labels drawn on a reply, a click puts the address in the prompt ---

const BASE = 'http://reference-points.invalid/'
const BLOCK = 'aaaa-1111'

function drawn(text) {
  return {
    plugin: 'reference-points',
    component: 'AssistantMessage',
    requestId: BLOCK,
    surface: 'terminal',
    viewport: { columns: 100, rows: 30 },
    props: { text, isFirstOfReply: true },
  } as const
}

test('a reply is drawn with its labels, and a click on one fills the prompt', async ($, on) => {
  const labeledText = `[.P1](${BASE}N3-S1.P1) Hello there.`
  let call
  on('process.run', ($, e) => {
    if (e.argv[1] === 'serve') return { value: { exitCode: 1, stdout: '', stderr: '' } } // not under test here
    call = e
    return { value: { exitCode: 0, stdout: JSON.stringify({ text: labeledText, base: BASE }), stderr: '' } }
  })
  mock.clock(on)
  const filled = []
  on('prompt.fill', ($, e) => {
    filled.push(e)
    return { isFilled: true }
  })
  mock.store(on)
  echoSubmit(on)

  await $.classic.SessionStart({ source: 'startup', transcript_path: TRANSCRIPT })
  const ui = await $.ui.mount(drawn('Hello there.'))

  expect(call.argv.slice(1)).toEqual(['label', TRANSCRIPT, '-T', '--block', BLOCK])
  const md = await ui.find({ type: 'Markdown' })
  expect(md.props.text).toBe(labeledText)
  expect(md.props.pressableLinks).toEqual([`${BASE}N3-S1.P1`])

  await ui.press({ key: `rp-${BLOCK}`, link: { href: `${BASE}N3-S1.P1` } })
  expect(filled.map((f) => [f.text, f.mode])).toEqual([['N3-S1.P1 ', 'insert']])
})

test('when the engine cannot label a block it is drawn as Claude Code draws it', async ($, on) => {
  on('process.run', () => ({ value: { exitCode: 1, stderr: 'MISSING: no reply record', stdout: '' } }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  on('ui.invalidate', () => ({ value: undefined }))
  on('classic.SessionStart', () => ({}))
  on('session.id', () => ({ value: 'abc' }))
  mock.store(on)
  mock.clock(on)

  await $.classic.SessionStart({ source: 'startup', transcript_path: TRANSCRIPT })
  const ui = await $.ui.mount(drawn('Hello there.'))

  expect(await ui.find({ type: 'Markdown' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
})

// A hot reload re-runs the module but not classic.SessionStart, so anything the mod
// learned there must come back from somewhere that outlives the module.
test('after a hot reload the mod still knows its transcript', async ($, on) => {
  let call
  on('process.run', ($, e) => {
    call = e
    return { value: { exitCode: 0, stdout: '[N1-S1.P2]\nThe second half.\n', stderr: '' } }
  })
  mock.store(on, { 'transcript:abc': TRANSCRIPT })
  echoSubmit(on)

  const out = await $.prompt.submit({ text: 'what did N1-S1.P2 mean?', wait: false, origin: { kind: 'user' } })

  expect(call.argv.slice(1)).toEqual(['expand', TRANSCRIPT])
  expect(out.context.slice(1)).toEqual(['[N1-S1.P2]\nThe second half.'])
})

test('the note is once per session and survives a hot reload', async ($, on) => {
  quiet(on)
  mock.store(on, { 'noted:abc': true, 'transcript:abc': TRANSCRIPT })
  echoSubmit(on)

  const out = await $.prompt.submit({ text: 'hello', wait: false, origin: { kind: 'user' } })
  expect(out.text).toBe('hello') // not dropped, and no note this time
  expect(out.context).toBeUndefined()
})

test('a block that grew gets its own retries, so its final text is still labeled', async ($, on) => {
  on('process.run', () => ({ value: { exitCode: 1, stdout: '', stderr: 'MISSING: no reply record' } }))
  let retries = 0
  on('ui.invalidate', () => {
    retries++
    return { value: undefined }
  })
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  on('classic.SessionStart', () => ({}))
  on('session.id', () => ({ value: 'abc' }))
  mock.store(on)
  const clock = mock.clock(on)

  await $.classic.SessionStart({ source: 'startup', transcript_path: TRANSCRIPT })
  // The streaming text fails again and again until its retries are spent.
  for (let i = 0; i < 4; i++) {
    const ui = await $.ui.mount(drawn('Hel'))
    await clock.advance(1000)
    await ui.unmount()
  }
  const spent = retries
  // The final text is a new length: if its record is not written yet, it must retry too.
  const final = await $.ui.mount(drawn('Hello there.'))
  await clock.advance(1000)
  await final.unmount()
  expect(retries).toBeGreaterThan(spent)
})

test('a streaming block starts the engine once a second, not once per chunk', async ($, on) => {
  let spawned = 0
  on('process.run', ($, e) => {
    if (e.argv[1] !== 'serve') spawned++ // the server start is not a labeling try
    return { value: { exitCode: 1, stdout: '', stderr: 'MISSING: no reply record' } }
  })
  on('ui.invalidate', () => ({ value: undefined }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  on('classic.SessionStart', () => ({}))
  on('session.id', () => ({ value: 'abc' }))
  mock.store(on)
  const clock = mock.clock(on)

  await $.classic.SessionStart({ source: 'startup', transcript_path: TRANSCRIPT })
  const ui = await $.ui.mount(drawn('H'))
  for (const text of ['He', 'Hel', 'Hell', 'Hello']) await ui.redraw({ text, isFirstOfReply: true })
  expect(spawned).toBe(1)

  await clock.advance(1000)
  await ui.redraw({ text: 'Hello there.', isFirstOfReply: true })
  expect(spawned).toBe(2)
})

// --- the long-lived engine: a socket when there is one, the CLI when there is not ---

const SOCKET = '/tmp/reference-points-test/engine.sock'

test('with a server up, the engine is reached over its socket and nothing is spawned', async ($, on) => {
  let spawned = 0
  let fetched
  on('process.run', () => {
    spawned++
    return { value: { exitCode: 0, stdout: '', stderr: '' } }
  })
  on('http.fetch', ($, e) => {
    fetched = e
    const body = { exitCode: 0, stdout: '[N1-S1.P2]\nThe second half.\n', stderr: '' }
    return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(body) } }
  })
  mock.store(on, { 'transcript:abc': TRANSCRIPT, socket: SOCKET, 'noted:abc': true })
  mock.clock(on)
  echoSubmit(on)

  const out = await $.prompt.submit({ text: 'what did N1-S1.P2 mean?', wait: false, origin: { kind: 'user' } })

  expect(spawned).toBe(0)
  expect(fetched.init.socketPath).toBe(SOCKET)
  expect(JSON.parse(fetched.init.body)).toEqual({ argv: ['expand', TRANSCRIPT], stdin: 'what did N1-S1.P2 mean?' })
  expect(out.context).toEqual(['[N1-S1.P2]\nThe second half.'])
})

test('with no server the CLI answers, and a server is started once for the next call', async ($, on) => {
  const spawns = []
  on('process.run', ($, e) => {
    spawns.push(e.argv.slice(1))
    if (e.argv[1] === 'serve') return { value: { exitCode: 0, stdout: `${SOCKET}\n`, stderr: '' } }
    return { value: { exitCode: 0, stdout: '[N1-S1.P2]\nThe second half.\n', stderr: '' } }
  })
  let served = false
  on('http.fetch', () => {
    if (!served) throw new Error('connect ENOENT')
    const body = { exitCode: 0, stdout: '[N1-S1.P2]\nvia socket\n', stderr: '' }
    return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(body) } }
  })
  mock.store(on, { 'transcript:abc': TRANSCRIPT, 'noted:abc': true })
  const clock = mock.clock(on)
  echoSubmit(on)

  // This call is answered by the CLI itself: slower, never wrong.
  const first = await $.prompt.submit({ text: 'N1-S1.P2?', wait: false, origin: { kind: 'user' } })
  expect(first.context).toEqual(['[N1-S1.P2]\nThe second half.'])
  expect(spawns.map((a) => a[0])).toContain('serve')
  expect(spawns.find((a) => a[0] === 'serve')).toEqual(['serve', '--daemon'])

  // Failing again within the minute does not start another.
  await $.prompt.submit({ text: 'N1-S1.P2?', wait: false, origin: { kind: 'user' } })
  expect(spawns.filter((a) => a[0] === 'serve')).toHaveLength(1)

  // Once the server answers, the socket path it printed is what the mod uses.
  served = true
  await clock.advance(1000)
  const third = await $.prompt.submit({ text: 'N1-S1.P2?', wait: false, origin: { kind: 'user' } })
  expect(third.context).toEqual(['[N1-S1.P2]\nvia socket'])
})
