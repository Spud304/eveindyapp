import { useMemo, useState } from 'react'
import { usePageTitle } from '@/hooks/usePageTitle'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useSlashFocus } from '@/hooks/useSlashFocus'
import { sortRows, useSort } from '@/hooks/useSort'
import { useLibrary } from '@/lib/api/hooks'
import type { BlueprintRow } from '@/lib/api/client'
import { duration, qty } from '@/lib/format'
import { Badge, Button, Empty, ErrorText, Input, Mono, Num, PageHeader, Panel, Select, Table } from '@/components/ui'

type Kind = 'all' | 'bpo' | 'bpc'
type SortKey = 'name' | 'me' | 'te' | 'runs' | 'location'

const KIND_TONE = { bpo: 'ok', bpc: 'info', stack: 'muted' } as const

/** A blueprint installed in a job is not in its hangar until the job is delivered. */
function JobNote({ b }: { b: BlueprintRow }) {
  if (!b.job_status || !b.job_activity) return null
  const activity = b.job_activity.replace('_', ' ')
  const end = b.job_end ? new Date(b.job_end) : null
  const text =
    b.job_status === 'ready'
      ? `in ${activity} job · finished, deliver it`
      : b.job_status === 'paused'
        ? `in ${activity} job · paused`
        : `in ${activity} job · ${end ? duration((end.getTime() - Date.now()) / 1000) : '?'} left`
  return (
    <Badge tone={b.job_status === 'ready' ? 'warn' : 'info'} testId={`library.row.${b.item_id}.job`} title={end ? `ends ${end.toLocaleString()}` : undefined}>
      {text}
    </Badge>
  )
}

export function LibraryPage() {
  usePageTitle('Library')
  useSlashFocus('library.search')
  const lib = useLibrary()
  const [q, setQ] = useState('')
  const [kind, setKind] = useState<Kind>('all')
  const [location, setLocation] = useState('')
  const term = useDebouncedValue(q).trim().toLowerCase()
  const { sort, toggle } = useSort<SortKey>({ key: 'name', dir: 'asc' })
  const all = useMemo(() => lib.data ?? [], [lib.data])
  const locations = useMemo(() => [...new Set(all.map((b) => b.location_name))].sort(), [all])
  const rows = useMemo(() => {
    const filtered = all.filter(
      (b) =>
        (!term || b.name.toLowerCase().includes(term)) &&
        (kind === 'all' || (kind === 'bpo' ? b.kind !== 'bpc' : b.kind === 'bpc')) &&
        (!location || b.location_name === location),
    )
    const pick: Record<SortKey, (b: BlueprintRow) => string | number> = {
      name: (b) => b.name,
      me: (b) => b.me,
      te: (b) => b.te,
      runs: (b) => b.runs,
      location: (b) => b.location_name,
    }
    return sortRows(filtered, sort.dir, pick[sort.key], (b) => b.name)
  }, [all, term, kind, location, sort])
  const filtered = term || kind !== 'all' || location
  const head = (key: SortKey, label: string, right = false) => (
    <th className={right ? 'text-right' : ''}>
      <button type="button" className="uppercase hover:text-fg" onClick={() => toggle(key, key === 'name' || key === 'location' ? 'asc' : 'desc')}>
        {label}
        {sort.key === key ? (sort.dir === 'asc' ? ' ▴' : ' ▾') : ''}
      </button>
    </th>
  )
  return (
    <>
      <PageHeader
        title="Library"
        count={rows.length === all.length ? all.length : `${rows.length} / ${all.length}`}
        context="blueprints your characters and corp hold"
        actions={
          <>
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search blueprint  /" testId="library.search" className="w-56" />
            <Select value={kind} onChange={(e) => setKind(e.target.value as Kind)} testId="library.kind">
              <option value="all">originals and copies</option>
              <option value="bpo">originals</option>
              <option value="bpc">copies</option>
            </Select>
            <Select value={location} onChange={(e) => setLocation(e.target.value)} testId="library.location" className="max-w-64">
              <option value="">every location</option>
              {locations.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </Select>
          </>
        }
      />
      <ErrorText error={lib.error} />
      <Panel flush testId="library.table">
        {rows.length === 0 && !lib.isLoading ? (
          <Empty
            hint={filtered ? undefined : 'Blueprints arrive with the next sync of a linked character (Setup).'}
            action={
              filtered ? (
                <Button
                  onClick={() => {
                    setQ('')
                    setKind('all')
                    setLocation('')
                  }}
                >
                  Clear filters
                </Button>
              ) : undefined
            }
          >
            {filtered ? 'No blueprint matches.' : 'No blueprints yet.'}
          </Empty>
        ) : (
          <Table hover>
            <thead>
              <tr>
                {head('name', 'Blueprint')}
                <th>Kind</th>
                {head('me', 'ME', true)}
                {head('te', 'TE', true)}
                {head('runs', 'Runs', true)}
                <th>Owner</th>
                {head('location', 'Location')}
                <th>Hangar</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.item_id} data-testid={`library.row.${b.item_id}`}>
                  <td>{b.name}</td>
                  <td>
                    <Badge tone={KIND_TONE[b.kind]} title={b.kind === 'stack' ? 'a stack of unresearched originals' : undefined}>
                      {b.kind === 'stack' ? `${b.quantity} × bpo` : b.kind}
                    </Badge>
                  </td>
                  <Num>{b.me}</Num>
                  <Num>{b.te}</Num>
                  <Num>{b.runs < 0 ? <span className="text-muted">∞</span> : qty(b.runs)}</Num>
                  <td className="text-muted">
                    {b.owner_name} <Mono className="text-label">{b.owner_kind === 'corporation' ? 'corp' : ''}</Mono>
                  </td>
                  <td className="max-w-96">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate" title={b.location_name}>
                        {b.location_name}
                      </span>
                      <JobNote b={b} />
                    </div>
                  </td>
                  <td className="text-muted">{b.hangar}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>
    </>
  )
}
