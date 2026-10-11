// The reference-points mod. Every decision about an address — what is one, what
// it points at, why it failed — is the Python engine's. This file only moves text
// between Claude Code and `reference-points expand`.

const RETRY_MS = 1000
const MAX_TRIES = 3
const SERVER_RETRY_MS = 60_000

// Per block: the text length it was labeled at (a streaming block grows), the
// labeling as a promise so concurrent renders share one process, the retries spent
// on that length, and when the engine last ran. A cache only: losing it to a
// reload costs one spawn.
const blocks = new Map()

// Once a conversation: the viewer does the job the skill used to ask the model to do.
const NOTE =
  '[reference-points mod active] Reply labels are drawn by the viewer: do not write N<turn>-S<n> ' +
  'labels yourself. Addresses in a prompt arrive already resolved, in blocks headed [address]; ' +
  'quote those, do not run reference-points for them.'

// Kept in the store, not a variable: a hot reload re-runs this module but not
// classic.SessionStart, and a variable would be gone. Per session, so two
// terminals do not overwrite each other.
const transcriptKey = async ($) => `transcript:${await $.session.id()}`
const notedKey = async ($) => `noted:${await $.session.id()}`

const spawn = ($, argv, init) => $.process.run([`${$.plugin.root}/bin/reference-points`, ...argv], init)

// The engine kept running behind a socket, so a call costs a request rather than a
// Python start. Null when there is none (or it is out of date): the caller runs the
// CLI, which gives the same answer, slower. The socket path is the engine's to name.
const viaServer = async ($, argv, stdin) => {
  const socketPath = await $.store.get('socket')
  if (!socketPath) return null
  try {
    const ran = await $.http.fetch('http://reference-points/', {
      method: 'POST',
      body: JSON.stringify({ argv, stdin }),
      socketPath,
    })
    return ran.ok ? JSON.parse(ran.text) : null
  } catch {
    return null
  }
}

// A cache only: a reload costs one more attempt.
let lastStart = -Infinity
const startServer = async ($) => {
  const now = await $.clock.now()
  if (now - lastStart < SERVER_RETRY_MS) return
  lastStart = now
  const ran = await spawn($, ['serve', '--daemon']).catch(() => null)
  if (ran?.exitCode === 0 && ran.stdout.trim()) await $.store.set('socket', ran.stdout.trim())
}

const engine = async ($, ...args) => {
  const init = typeof args.at(-1) === 'object' ? args.pop() : undefined
  const served = await viaServer($, args, init?.stdin ?? '')
  if (served) return served
  startServer($).catch(() => {}) // for the next call; this one runs the CLI itself
  return spawn($, args, init)
}

// null when the engine says no — most often because the record is not in the
// transcript file yet; the caller draws the reply as Claude Code would.
const labelBlock = async ($, transcript, uuid) => {
  try {
    const ran = await engine($, 'label', transcript, '-T', '--block', uuid)
    return ran.exitCode === 0 ? JSON.parse(ran.stdout) : null
  } catch {
    return null
  }
}

export function register(on) {
  on('classic.SessionStart', async ($, e, next) => {
    await $.store.set(await transcriptKey($), e.transcript_path)
    await $.store.delete(await notedKey($))
    blocks.clear()
    return next(e)
  })

  // Labels are drawn, not written: the stored reply, and so the model's context,
  // never contains them. A click on one puts its full address in the prompt box.
  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const transcript = await $.store.get(await transcriptKey($))
    if (!transcript) return next(e)
    const length = e.props.text.length
    const now = await $.clock.now()
    const block = blocks.get(e.requestId) ?? { lastTry: -Infinity }
    blocks.set(e.requestId, block)
    if (block.length !== length) Object.assign(block, { length, tries: 0, hit: undefined })
    if (!block.hit) {
      // Retries spent on this text: it will not label by being drawn again. A change
      // of length starts a new count.
      if (block.tries >= MAX_TRIES) return next(e)
      // A streaming block grows by the chunk and its record is not written yet, so a
      // try per chunk is a process per chunk: one a second, and a wake-up for the rest.
      const wait = RETRY_MS - (now - block.lastTry)
      if (wait > 0) {
        if (!block.wake) {
          block.wake = true
          $.clock.after(wait, () => {
            block.wake = false
            return $.ui.invalidate('ui.render')
          })
        }
        return next(e)
      }
      block.lastTry = now
      block.hit = labelBlock($, transcript, e.requestId)
    }
    const hit = await block.hit
    if (!hit) {
      block.hit = undefined
      if (++block.tries < MAX_TRIES) $.clock.after(RETRY_MS, () => $.ui.invalidate('ui.render'))
      return next(e)
    }

    // Only our own links are ours to answer; the model's keep their usual click.
    const hrefs = hit.text.split(hit.base).slice(1).map((rest) => hit.base + rest.split(')')[0])
    const { Markdown } = $.ui.resolve(e)
    return Markdown({
      key: `rp-${e.requestId}`,
      text: hit.text,
      pressableLinks: [...new Set(hrefs)],
      onLinkPress: (link) => $.prompt.fill({ text: `${link.href.slice(hit.base.length)} `, mode: 'insert' }),
    })
  })

  // Addresses the user typed arrive with their content already attached, so the
  // model never spends a tool call (or a recalled, wrong paragraph) on one.
  on('prompt.submit', async ($, e, next) => {
    // A notification, a peer's message or pasted tool output is not the user citing a reply.
    if (e.origin?.kind !== 'user') return next(e)
    const transcript = await $.store.get(await transcriptKey($))
    if (!transcript) return next(e)
    const context = [...(e.context ?? [])]
    const noted = await notedKey($)
    const first = !(await $.store.get(noted))
    if (first) context.push(NOTE)

    // Whether the text holds an address is the engine's call; it prints nothing when it does not.
    let ran
    try {
      ran = await engine($, 'expand', transcript, { stdin: e.text })
    } catch (error) {
      return { drop: `reference-points could not run: ${error.message}` }
    }
    // Fail loud: the engine's message already names its category and what to type instead.
    if (ran.exitCode !== 0) return { drop: ran.stderr.trim() }
    if (ran.stdout.trim()) context.push(ran.stdout.trim())

    if (first) await $.store.set(noted, true) // only once the prompt is really going out
    return context.length === (e.context?.length ?? 0) ? next(e) : next({ ...e, context })
  })
}
