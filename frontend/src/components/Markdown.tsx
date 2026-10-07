import { Children, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Source } from '../types'
import { Icon } from './Icon'

const CITATION = /(\[[ST]\d+\])/g
const IS_CITATION = /^\[([ST]\d+)\]$/

/** The small [S1] / [T1] pill. Document citations link to the PDF page; record citations show a database icon. */
export function CitationChip({ id, source }: { id: string; source?: Source }) {
  const base =
    'mx-0.5 inline-flex items-center gap-0.5 rounded-md px-1.5 py-px align-baseline text-[11px] font-semibold ' +
    'no-underline transition-colors'
  if (source?.type === 'document' && source.url) {
    const href = source.url + (source.page ? `#page=${source.page}` : '') // PDF viewers jump to the page
    return (
      <a href={href} target="_blank" rel="noopener noreferrer"
         title={`${source.title}${source.page ? `, page ${source.page}` : ''}`}
         className={`${base} bg-teal-100 text-teal-800 hover:bg-teal-200 dark:bg-teal-900/50 dark:text-teal-200 dark:hover:bg-teal-800/60`}>
        {id}
      </a>
    )
  }
  return (
    <span title={source?.title ?? 'Patient records'}
          className={`${base} bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-200`}>
      <Icon name="database" className="h-3 w-3" />{id}
    </span>
  )
}

/** Replace "[S1]" inside text nodes with chips, leaving every other React node untouched. */
function withCitations(children: ReactNode, byId: Map<string, Source>): ReactNode {
  return Children.map(children, (child) => {
    if (typeof child !== 'string') return child
    return child.split(CITATION).map((part, i) => {
      const m = IS_CITATION.exec(part)
      return m ? <CitationChip key={i} id={m[1]} source={byId.get(m[1])} /> : part
    })
  })
}

/**
 * Renders the assistant's markdown. react-markdown does NOT render raw HTML, so model output can't inject
 * markup or scripts (the server's output guard also strips unapproved links before we ever see them).
 */
export function Markdown({ text, sources }: { text: string; sources: Source[] }) {
  const byId = new Map(sources.map((s) => [s.id, s]))
  const cite = (Tag: 'p' | 'li' | 'td' | 'th' | 'strong' | 'em') =>
    ({ children }: { children?: ReactNode }) => {
      const Element = Tag
      return <Element>{withCitations(children, byId)}</Element>
    }
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: cite('p'), li: cite('li'), td: cite('td'), th: cite('th'), strong: cite('strong'), em: cite('em'),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}
