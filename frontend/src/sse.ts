import type { StreamEvent } from './types'

/**
 * Incremental Server-Sent-Events parser.
 *
 * Network chunks do NOT line up with event boundaries: one chunk may hold half an event, or three
 * events. So we keep a buffer, split on the blank line that ends each event, and keep the unfinished
 * tail for the next chunk.
 *
 * Wire format (what FastAPI sends):
 *   : connected                      <- comment line, ignored (keeps the connection open)
 *   event: status
 *   data: {"type":"status", ...}     <- JSON payload
 *   (blank line)                     <- ends the event
 */
export class SSEParser {
  private buffer = ''

  feed(chunk: string): StreamEvent[] {
    this.buffer += chunk.replace(/\r\n/g, '\n')
    const events: StreamEvent[] = []

    let boundary: number
    while ((boundary = this.buffer.indexOf('\n\n')) !== -1) {
      const block = this.buffer.slice(0, boundary)
      this.buffer = this.buffer.slice(boundary + 2)
      const parsed = parseBlock(block)
      if (parsed) events.push(parsed)
    }
    return events
  }
}

function parseBlock(block: string): StreamEvent | null {
  const dataLines: string[] = []
  let name: string | null = null
  for (const line of block.split('\n')) {
    if (line.startsWith(':')) continue // comment
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
  }
  if (dataLines.length === 0) return null
  try {
    const payload = JSON.parse(dataLines.join('\n'))
    // The server puts the event name inside the payload as "type"; fall back to the SSE name.
    return { type: name ?? payload.type, ...payload } as StreamEvent
  } catch {
    return null // a malformed event must never crash the UI
  }
}
