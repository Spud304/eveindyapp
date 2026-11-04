import { useEffect, useRef, useState } from 'react'
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TableHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'
import clsx from 'clsx'

/** The one place visual styling lives (docs/ui-design.md). Pages compose these; a restyle edits this file. */

export function Panel({
  title,
  actions,
  children,
  className,
  testId,
  flush = false,
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  testId?: string
  flush?: boolean // no body padding (a table that runs edge to edge)
}) {
  return (
    <section className={clsx('rounded border border-line bg-panel', className)} data-testid={testId}>
      {title !== undefined ? (
        <header className="flex min-h-9 flex-wrap items-center justify-between gap-x-2 gap-y-1 border-b border-line px-3 py-1">
          <h2 className="text-label font-semibold uppercase tracking-wide text-muted">{title}</h2>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={flush ? '' : 'p-3'}>{children}</div>
    </section>
  )
}

type ButtonVariant = 'default' | 'primary' | 'danger' | 'ghost'

const buttonClass = (variant: ButtonVariant, small = false) =>
  clsx(
    'inline-flex items-center gap-1 rounded border font-medium whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50',
    small ? 'h-6 px-2 text-label' : 'h-7 px-2.5 text-ui',
    variant === 'default' && 'border-line bg-panel-2 hover:border-muted',
    variant === 'primary' && 'border-transparent bg-accent text-accent-fg hover:brightness-110',
    variant === 'danger' && 'border-transparent bg-bad/15 text-bad hover:bg-bad/25',
    variant === 'ghost' && 'border-transparent text-muted hover:bg-panel-2 hover:text-fg',
  )

export function Button({
  variant = 'default',
  small = false,
  className,
  testId,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; small?: boolean; testId?: string }) {
  return <button type="button" data-testid={testId} {...props} className={clsx(buttonClass(variant, small), className)} />
}

/** A plain link styled as a button (server routes such as /auth/login, which leave the SPA). */
export function LinkButton({ href, children, variant = 'primary', testId, title }: { href: string; children: ReactNode; variant?: ButtonVariant; testId?: string; title?: string }) {
  return (
    <a data-testid={testId} href={href} title={title} className={buttonClass(variant)}>
      {children}
    </a>
  )
}

export function Input({ className, invalid, testId, ...props }: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean; testId?: string }) {
  return (
    <input
      data-testid={testId}
      {...props}
      className={clsx(
        'h-7 rounded border bg-bg px-2 text-ui text-fg placeholder:text-muted focus:border-accent focus:outline-none',
        props.type === 'number' && '[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none',
        invalid ? 'border-warn' : 'border-line',
        className,
      )}
    />
  )
}

export function Textarea({ className, invalid, testId, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean; testId?: string }) {
  return (
    <textarea
      data-testid={testId}
      {...props}
      className={clsx(
        'mono rounded border bg-bg p-2 text-ui leading-snug text-fg placeholder:text-muted focus:border-accent focus:outline-none',
        invalid ? 'border-warn' : 'border-line',
        className,
      )}
    />
  )
}

export function Select({ className, testId, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { testId?: string }) {
  return (
    <select
      data-testid={testId}
      {...props}
      className={clsx('h-7 rounded border border-line bg-bg px-1.5 text-ui text-fg focus:border-accent focus:outline-none', className)}
    />
  )
}

export function Checkbox({ label, testId, ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode; testId?: string }) {
  const box = <input type="checkbox" data-testid={testId} {...props} className={clsx('accent-[var(--accent)]', props.className)} />
  if (!label) return box
  return (
    <label className="inline-flex items-center gap-1.5 text-ui">
      {box}
      {label}
    </label>
  )
}

export type Tone = 'muted' | 'ok' | 'warn' | 'bad' | 'info' | 'accent' | 'build' | 'buy' | 'stock'

export function Badge({ tone = 'muted', children, testId, title }: { tone?: Tone; children: ReactNode; testId?: string; title?: string }) {
  return (
    <span
      data-testid={testId}
      title={title}
      className={clsx(
        'inline-flex items-center rounded px-1.5 py-0.5 text-label font-medium whitespace-nowrap uppercase tracking-wide',
        tone === 'muted' && 'bg-panel-2 text-muted',
        tone === 'ok' && 'bg-ok/15 text-ok',
        tone === 'warn' && 'bg-warn/15 text-warn',
        tone === 'bad' && 'bg-bad/15 text-bad',
        tone === 'info' && 'bg-info/15 text-info',
        tone === 'accent' && 'bg-accent/15 text-accent',
        tone === 'build' && 'bg-build/15 text-build',
        tone === 'buy' && 'bg-buy/15 text-buy',
        tone === 'stock' && 'bg-stock/15 text-stock',
      )}
    >
      {children}
    </span>
  )
}

/** `hover` tints the row under the pointer so the eye can follow it across a wide list. */
export function Table({ children, className, hover = false, ...props }: TableHTMLAttributes<HTMLTableElement> & { children: ReactNode; hover?: boolean }) {
  return (
    <div className={clsx('overflow-x-auto', className)}>
      <table
        {...props}
        className={clsx(
          'w-full border-collapse text-left text-ui [&_td]:border-t [&_td]:border-line [&_td]:px-2 [&_td]:py-1 [&_th]:px-2 [&_th]:py-1 [&_th]:text-label [&_th]:font-semibold [&_th]:whitespace-nowrap [&_th]:uppercase [&_th]:tracking-wide [&_th]:text-muted',
          hover && '[&_tbody_tr:hover]:bg-panel-2',
        )}
      >
        {children}
      </table>
    </div>
  )
}

/** Right-aligned monospace cell for numbers. */
export function Num({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <td className={clsx('mono text-right whitespace-nowrap', className)} title={title}>
      {children}
    </td>
  )
}

/** One header row per routed page: what the page is, how much is in it, its context, and actions on the right. */
export function PageHeader({ title, count, context, actions, testId = 'page.header' }: { title: ReactNode; count?: ReactNode; context?: ReactNode; actions?: ReactNode; testId?: string }) {
  return (
    <div className="mb-3 flex min-h-9 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line pb-2" data-testid={testId}>
      <h1 className="text-title font-semibold tracking-tight" data-testid="page.title">
        {title}
      </h1>
      {count != null ? (
        <Mono className="text-muted" testId="page.count">
          {count}
        </Mono>
      ) : null}
      {context ? <div className="flex flex-wrap items-center gap-2 text-muted">{context}</div> : null}
      {actions ? (
        <div className="ml-auto flex flex-wrap items-center gap-2" data-testid="page.actions">
          {actions}
        </div>
      ) : null}
    </div>
  )
}

export function Field({ label, children, hint }: { label: ReactNode; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5 text-label text-muted">
      {label}
      {children}
      {hint ? <span className="text-label">{hint}</span> : null}
    </label>
  )
}

/** An empty list or panel: what is missing, one line on why or what to do, and the action that fills it. */
export function Empty({ children, hint, action, testId }: { children: ReactNode; hint?: ReactNode; action?: ReactNode; testId?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-6 text-center text-muted" data-testid={testId}>
      <p>{children}</p>
      {hint ? <p className="text-ui">{hint}</p> : null}
      {action ? <div>{action}</div> : null}
    </div>
  )
}

export function ErrorText({ error, testId }: { error: unknown; testId?: string }) {
  if (!error) return null
  return (
    <p className="text-bad" data-testid={testId}>
      {error instanceof Error ? error.message : String(error)}
    </p>
  )
}

export function Mono({ children, className, testId }: { children: ReactNode; className?: string; testId?: string }) {
  return (
    <span className={clsx('mono', className)} data-testid={testId}>
      {children}
    </span>
  )
}

/** The reason behind a derived value, as the engine wrote it (docs/ui-design.md: every derived value shows its reason). */
export function Why({ text, className }: { text?: string | null; className?: string }) {
  if (!text) return null
  return <span className={clsx('text-label text-muted', className)}>{text}</span>
}

export function Tabs<K extends string>({ tabs, value, onChange, testId }: { tabs: { key: K; label: ReactNode }[]; value: K; onChange: (key: K) => void; testId: string }) {
  return (
    <div className="mb-3 flex gap-1 border-b border-line" role="tablist" data-testid={testId}>
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          role="tab"
          aria-selected={value === t.key}
          data-testid={`${testId}.${t.key}`}
          onClick={() => onChange(t.key)}
          className={clsx(
            '-mb-px border-b-2 px-3 py-1.5 text-ui',
            value === t.key ? 'border-accent font-semibold text-fg' : 'border-transparent text-muted hover:text-fg',
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

/**
 * A text box that searches as you type and lists matches under it; Enter or a click picks one.
 * For long lists, where a native <select> would be too tall (docs/ui-design.md).
 */
export function SearchPicker<T>({
  value,
  onValue,
  results,
  loading,
  render,
  onPick,
  placeholder,
  testId,
  className,
}: {
  value: string
  onValue: (v: string) => void
  results: T[] | undefined
  loading?: boolean
  render: (item: T) => ReactNode
  onPick: (item: T) => void
  placeholder: string
  testId: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])
  const items = results ?? []
  const pick = (item: T) => {
    onPick(item)
    setOpen(false)
  }
  return (
    <div className={clsx('relative', className)} ref={box}>
      <Input
        testId={testId}
        value={value}
        placeholder={placeholder}
        className="w-full"
        onChange={(e) => {
          onValue(e.target.value)
          setOpen(true)
          setActive(0)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setActive((a) => Math.min(a + 1, items.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setActive((a) => Math.max(a - 1, 0))
          } else if (e.key === 'Enter' && items[active]) {
            e.preventDefault()
            pick(items[active])
          } else if (e.key === 'Escape') {
            setOpen(false)
          }
        }}
      />
      {open && value.trim().length >= 2 ? (
        <ul className="absolute z-20 mt-0.5 max-h-72 w-full overflow-auto rounded border border-line bg-panel py-0.5 text-ui shadow" data-testid={`${testId}.results`}>
          {items.length === 0 ? <li className="px-2 py-1 text-muted">{loading ? 'searching' : 'no match'}</li> : null}
          {items.map((item, i) => (
            <li
              key={i}
              className={clsx('cursor-pointer px-2 py-1', i === active && 'bg-panel-2')}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault()
                pick(item)
              }}
            >
              {render(item)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
