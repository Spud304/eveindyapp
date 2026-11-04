import { useEffect, useState } from 'react'
import { useNavigate, useParams } from '@tanstack/react-router'
import { usePageTitle } from '@/hooks/usePageTitle'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useLocalCopy } from '@/hooks/useLocalCopy'
import { useCorporations, useLibrary, useMe, usePlan, usePlanMutations, usePlanResult, useStations, useTypeSearch } from '@/lib/api/hooks'
import { useCopy } from '@/hooks/useCopy'
import { Link } from '@tanstack/react-router'
import type { BlueprintRow, LineIO, PlanOut, PlanResultOut, TypeOut } from '@/lib/api/client'
import { BUILD_CATEGORY_LABELS } from '@/lib/format'
import {
  Badge,
  Button,
  Checkbox,
  Empty,
  ErrorText,
  Field,
  Input,
  Mono,
  PageHeader,
  Panel,
  SearchPicker,
  Select,
  Tabs,
} from '@/components/ui'
import { BlueprintsTab, CostTab, ScheduleTab, ShoppingTab, type Lookups } from './tabs'
import { ProgressTab } from './progress'

type TabKey = 'shopping' | 'blueprints' | 'schedule' | 'cost' | 'progress'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'shopping', label: 'Shopping list' },
  { key: 'blueprints', label: 'Blueprints' },
  { key: 'schedule', label: 'Schedule' },
  { key: 'cost', label: 'Cost' },
  { key: 'progress', label: 'Progress' },
]

export function PlanPage() {
  const { planId } = useParams({ from: '/plans/$planId' })
  const id = Number(planId)
  const plan = usePlan(id)
  const result = usePlanResult(id)
  const me = useMe()
  const stations = useStations()
  const [tab, setTab] = useState<TabKey>('shopping')
  usePageTitle(plan.data?.name ?? 'Plan')

  if (plan.error) return <ErrorText error={plan.error} />
  if (!plan.data) return null
  const p = plan.data
  const lookups: Lookups = {
    characters: new Map((me.data?.characters ?? []).map((c) => [c.character_id, c.name])),
    stations: new Map((stations.data ?? []).map((s) => [s.id, s.name])),
  }
  const r = result.data
  return (
    <>
      <PlanHeader plan={p} result={r} computing={result.isFetching} />
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <div className="min-w-0">
          <Tabs tabs={TABS} value={tab} onChange={setTab} testId="plan.tabs" />
          <ErrorText error={result.error} />
          {r?.error ? (
            <Empty hint={r.error === 'plan has no lines' ? 'Add what you want built on the right.' : undefined} testId="plan.empty">
              {r.error === 'plan has no lines' ? 'Nothing to plan yet.' : r.error}
            </Empty>
          ) : null}
          {r?.result ? (
            <>
              {tab === 'shopping' ? <ShoppingTab data={r} /> : null}
              {tab === 'blueprints' ? <BlueprintsTab data={r} lookups={lookups} plan={p} /> : null}
              {tab === 'schedule' ? <ScheduleTab data={r} lookups={lookups} /> : null}
              {tab === 'cost' ? <CostTab data={r} /> : null}
            </>
          ) : null}
          {tab === 'progress' ? <ProgressTab planId={p.id} /> : null}
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <LinesPanel plan={p} />
          <SharingPanel plan={p} />
          <SettingsPanel plan={p} />
          {r?.result?.warnings.length ? <WarningsPanel data={r} /> : null}
        </div>
      </div>
    </>
  )
}

function PlanHeader({ plan: p, result, computing }: { plan: PlanOut; result: PlanResultOut | undefined; computing: boolean }) {
  const { edit, activate, deactivate, remove } = usePlanMutations()
  const navigate = useNavigate()
  const [name, setName] = useState(p.name)
  useEffect(() => setName(p.name), [p.name])
  const total = result?.result?.costs.total
  const days = result?.result ? result.result.total_seconds / 86400 : null
  return (
    <PageHeader
      title={
        <input
          className="w-64 rounded border border-transparent bg-transparent px-1 text-title font-semibold hover:border-line focus:border-accent focus:outline-none"
          value={name}
          data-testid="plan.name"
          title="rename"
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            if (name.trim() && name !== p.name) edit.mutate({ id: p.id, body: { name: name.trim() } })
          }}
        />
      }
      context={
        <>
          {p.is_active ? <Badge tone="accent">active</Badge> : null}
          {p.reserve_assets ? <Badge tone="info">reserves · priority {p.priority}</Badge> : null}
          {total != null ? (
            <span title="materials to buy plus job fees">
              total <Mono className="text-fg">{Math.round(total).toLocaleString('en-US')}</Mono> ISK
            </span>
          ) : null}
          {days != null ? (
            <span title="wall-clock until the last scheduled job ends">
              <Mono className="text-fg">{days.toFixed(1)}</Mono> days
            </span>
          ) : null}
          {computing ? <span className="text-label">computing</span> : null}
        </>
      }
      actions={
        <>
          {p.is_active ? (
            <Button small onClick={() => deactivate.mutate(p.id)} testId="plan.deactivate">
              Deactivate
            </Button>
          ) : (
            <Button small variant="primary" onClick={() => activate.mutate(p.id)} testId="plan.activate" title="the tracker attributes new jobs to the active plan; only one plan is active">
              Make active
            </Button>
          )}
          <Button
            small
            variant="danger"
            testId="plan.delete"
            onClick={() => {
              if (window.confirm(`Delete plan ${p.name}? Its lines and settings go with it.`))
                remove.mutate(p.id, { onSuccess: () => void navigate({ to: '/plans' }) })
            }}
          >
            Delete
          </Button>
        </>
      }
    />
  )
}

function LinesPanel({ plan: p }: { plan: PlanOut }) {
  const { setLines } = usePlanMutations()
  const [q, setQ] = useState('')
  const [picking, setPicking] = useState(false)
  const search = useTypeSearch(useDebouncedValue(q), 'buildable')
  const lines: LineIO[] = p.lines.map((l) => ({ type_id: l.type_id, quantity: l.quantity, blueprint_item_ids: l.blueprint_item_ids }))
  const save = (next: LineIO[], onSuccess?: () => void) => setLines.mutate({ id: p.id, lines: next }, { onSuccess })
  return (
    <Panel
      title="Build"
      testId="plan.lines"
      actions={
        <Button small variant="ghost" onClick={() => setPicking(!picking)} testId="plan.pick-bpcs" title="run specific BPCs you own">
          {picking ? 'Close' : 'Pick BPCs'}
        </Button>
      }
    >
      <ul className="mb-2 flex flex-col gap-1">
        {p.lines.map((l, i) => (
          <li key={l.id} className="flex items-center gap-2" data-testid={`plan.line.${l.type_id}`}>
            {l.blueprint_item_ids?.length ? (
              <span className="w-16 text-right" title="set by the runs of the picked BPCs">
                <Mono>{l.quantity}</Mono>
              </span>
            ) : (
              <QtyInput
                value={l.quantity}
                onSave={(qty) => save(lines.map((x, j) => (j === i ? { ...x, quantity: qty } : x)))}
                testId={`plan.line.${l.type_id}.qty`}
              />
            )}
            <span className="min-w-0 flex-1 truncate">
              {l.name}
              {l.blueprint_item_ids?.length ? (
                <span className="text-label text-muted" data-testid={`plan.line.${l.type_id}.bpcs`}>
                  {' '}
                  · {l.blueprint_item_ids.length} picked BPC{l.blueprint_item_ids.length === 1 ? '' : 's'}
                </span>
              ) : null}
            </span>
            <Button small variant="ghost" onClick={() => save(lines.filter((_, j) => j !== i))} title="remove this line">
              ×
            </Button>
          </li>
        ))}
      </ul>
      <SearchPicker<TypeOut>
        value={q}
        onValue={setQ}
        results={search.data}
        loading={search.isFetching}
        render={(t) => t.name}
        onPick={(t) => {
          // Adding an item already in the plan raises its line; lines of picked BPCs are left alone.
          const at = lines.findIndex((l) => l.type_id === t.id && !l.blueprint_item_ids?.length)
          save(at >= 0 ? lines.map((l, j) => (j === at ? { ...l, quantity: l.quantity + 1 } : l)) : [...lines, { type_id: t.id, quantity: 1, blueprint_item_ids: [] }])
          setQ('')
        }}
        placeholder="add item to build"
        testId="plan.add-line"
      />
      {picking ? <BpcPicker planId={p.id} onAdd={(line) => save([...lines, line], () => setPicking(false))} /> : null}
    </Panel>
  )
}

/** Owned BPCs not picked by any plan yet; tick copies of one blueprint and add them as a line. */
function BpcPicker({ planId, onAdd }: { planId: number; onAdd: (line: LineIO) => void }) {
  const lib = useLibrary()
  const [q, setQ] = useState('')
  const [ticked, setTicked] = useState<number[]>([])
  const term = useDebouncedValue(q).trim().toLowerCase()
  // BPCs in a job are left out: the plan cannot use them until the job is delivered.
  const free = (lib.data ?? []).filter((b) => b.kind === 'bpc' && b.product_type_id != null && b.plan_id == null && !b.job_status)
  const pickedType = free.find((b) => b.item_id === ticked[0])?.type_id
  const rows = free.filter((b) => (pickedType ? b.type_id === pickedType : !term || b.name.toLowerCase().includes(term)))
  const chosen = ticked.map((id) => free.find((b) => b.item_id === id)).filter((b): b is BlueprintRow => !!b)
  const runs = chosen.reduce((n, b) => n + b.runs, 0)
  const toggle = (id: number) => setTicked(ticked.includes(id) ? ticked.filter((x) => x !== id) : [...ticked, id])
  return (
    <div className="mt-3 border-t border-line pt-2" data-testid="plan.bpc-picker">
      {pickedType ? (
        <div className="mb-1 text-label text-muted">copies of {chosen[0]?.name}; untick all to pick another blueprint</div>
      ) : (
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search BPCs" testId="plan.bpc-search" className="mb-1 w-full" />
      )}
      {lib.isLoading ? <div className="text-label text-muted">loading library</div> : null}
      {!lib.isLoading && rows.length === 0 ? <div className="text-label text-muted">No unpicked BPCs match.</div> : null}
      <ul className="flex max-h-64 flex-col gap-0.5 overflow-y-auto">
        {rows.slice(0, 100).map((b) => (
          <li key={b.item_id} data-testid={`plan.bpc.${b.item_id}`}>
            <Checkbox
              checked={ticked.includes(b.item_id)}
              onChange={() => toggle(b.item_id)}
              testId={`plan.bpc.${b.item_id}.tick`}
              label={
                <span className="truncate" title={`${b.location_name} · ${b.hangar}`}>
                  {b.name} · <Mono>{b.runs}</Mono> runs · ME <Mono>{b.me}</Mono> / TE <Mono>{b.te}</Mono>
                </span>
              }
            />
          </li>
        ))}
      </ul>
      <Button
        small
        variant="primary"
        className="mt-2"
        disabled={!chosen.length}
        testId="plan.bpc-add"
        onClick={() => onAdd({ type_id: chosen[0].product_type_id!, quantity: Math.max(1, runs), blueprint_item_ids: chosen.map((b) => b.item_id) })}
      >
        {chosen.length ? `Add ${chosen.length} BPC${chosen.length === 1 ? '' : 's'} (${runs} runs)` : 'Tick BPCs to add'}
      </Button>
      <span className="ml-2 text-label text-muted" hidden={!planId}>
        picked BPCs are kept out of your other plans
      </span>
    </div>
  )
}

function QtyInput({ value, onSave, testId }: { value: number; onSave: (v: number) => void; testId: string }) {
  const [v, setV] = useState(String(value))
  useEffect(() => setV(String(value)), [value])
  const commit = () => {
    const n = Math.floor(Number(v))
    if (n >= 1 && n !== value) onSave(n)
    else setV(String(value))
  }
  return (
    <Input
      type="number"
      min={1}
      value={v}
      testId={testId}
      className="w-20 text-right mono"
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit()
      }}
    />
  )
}

function SettingsPanel({ plan: p }: { plan: PlanOut }) {
  const { edit } = usePlanMutations()
  const stations = useStations()
  const [priority, setPriority] = useState(String(p.priority))
  useEffect(() => setPriority(String(p.priority)), [p.priority])
  const save = (body: Parameters<typeof edit.mutate>[0]['body']) => edit.mutate({ id: p.id, body })
  // Local copies so toggles change at once; they follow the server after each save.
  const [reserve, setReserve] = useLocalCopy(p.reserve_assets)
  const [stationIds, setStationIds] = useLocalCopy(p.station_ids)
  const [overrides, setOverrides] = useLocalCopy(p.category_overrides as Record<string, string>)
  const saveStations = (ids: number[]) => {
    setStationIds(ids)
    save({ station_ids: ids })
  }
  const enabled = (stations.data ?? []).filter((s) => s.enabled)
  const allStations = stationIds.length === 0
  return (
    <Panel title="Settings" testId="plan.settings">
      <div className="flex flex-col gap-3">
        <div className="flex items-end gap-3">
          <Checkbox
            label="Reserve assets"
            checked={reserve}
            testId="plan.reserve"
            title="claim hangar stock before plans that do not reserve, in priority order"
            onChange={(e) => {
              setReserve(e.target.checked)
              save({ reserve_assets: e.target.checked })
            }}
          />
          <Field label="Priority (lower first)">
            <Input
              type="number"
              value={priority}
              className="w-20 mono"
              testId="plan.priority"
              onChange={(e) => setPriority(e.target.value)}
              onBlur={() => {
                const n = Math.floor(Number(priority))
                if (!Number.isNaN(n) && n !== p.priority) save({ priority: n })
              }}
            />
          </Field>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-label font-semibold uppercase tracking-wide text-muted">Stations</span>
          <Checkbox
            label="All enabled stations"
            checked={allStations}
            testId="plan.stations.all"
            onChange={(e) => saveStations(e.target.checked ? [] : enabled.map((s) => s.id))}
          />
          {!allStations
            ? enabled.map((s) => (
                <Checkbox
                  key={s.id}
                  label={s.name}
                  testId={`plan.stations.${s.id}`}
                  checked={stationIds.includes(s.id)}
                  onChange={(e) => saveStations(e.target.checked ? [...stationIds, s.id] : stationIds.filter((x) => x !== s.id))}
                />
              ))
            : null}
          <Field label="Hangars that count (empty: all)" hint="e.g. CorpSAG2 Hangar">
            <HangarInput value={p.hangar_flags} onSave={(flags) => save({ hangar_flags: flags })} />
          </Field>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-label font-semibold uppercase tracking-wide text-muted">Rules for this plan</span>
          {Object.entries(BUILD_CATEGORY_LABELS).map(([key, label]) => (
            <label key={key} className="flex items-center justify-between gap-2 text-ui">
              {label}
              <Select
                value={overrides[key] ?? ''}
                testId={`plan.rule.${key}`}
                onChange={(e) => {
                  const next: Record<string, 'buy' | 'build'> = {}
                  for (const [k, mode] of Object.entries(overrides)) if (mode === 'buy' || mode === 'build') next[k] = mode
                  if (e.target.value === 'buy' || e.target.value === 'build') next[key] = e.target.value
                  else delete next[key]
                  setOverrides(next)
                  save({ category_overrides: next })
                }}
              >
                <option value="">account default</option>
                <option value="buy">buy</option>
                <option value="build">build</option>
              </Select>
            </label>
          ))}
        </div>
      </div>
    </Panel>
  )
}

/** Who else can see the plan: nobody, the corporation (log in), or anyone with the link. */
function SharingPanel({ plan: p }: { plan: PlanOut }) {
  const { edit, newShareLink } = usePlanMutations()
  const corps = useCorporations(p.visibility === 'corp')
  const { copied, copy } = useCopy()
  const url = p.share_token ? `${window.location.origin}/shared/${p.share_token}` : ''
  return (
    <Panel title="Sharing" testId="plan.sharing">
      <div className="flex flex-col gap-2">
        <Select
          value={p.visibility}
          testId="plan.visibility"
          onChange={(e) => edit.mutate({ id: p.id, body: { visibility: e.target.value as 'private' | 'corp' | 'link' } })}
        >
          <option value="private">Only me</option>
          <option value="corp">My corporation (they log in)</option>
          <option value="link">Anyone with the link (names hidden)</option>
        </Select>
        {p.visibility === 'corp' ? (
          <Field label="Corporation">
            <Select
              value={p.share_corporation_id ?? ''}
              testId="plan.share-corp"
              onChange={(e) => edit.mutate({ id: p.id, body: { share_corporation_id: e.target.value ? Number(e.target.value) : null } })}
            >
              <option value="">my main's corporation</option>
              {(corps.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
        ) : null}
        {p.visibility === 'link' && url ? (
          <div className="flex items-center gap-2">
            <Input value={url} readOnly className="mono min-w-0 flex-1" testId="plan.share-url" onFocus={(e) => e.target.select()} />
            <Button small onClick={() => void copy(url, true, 'link')} testId="plan.share-copy">
              {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button
              small
              variant="ghost"
              testId="plan.share-renew"
              title="make a new link; the old one stops working"
              onClick={() => {
                if (window.confirm('Make a new link? The current one will stop working.')) newShareLink.mutate(p.id)
              }}
            >
              New link
            </Button>
          </div>
        ) : null}
        {p.visibility !== 'private' ? (
          <p className="text-label text-muted">
            Viewers see the lines, shopping list, schedule and progress, read-only. They never see your settings, other plans or Library.{' '}
            <Link to="/plans/$planId/view" params={{ planId: String(p.id) }} className="text-accent hover:underline" data-testid="plan.share-preview">
              Preview
            </Link>
          </p>
        ) : null}
      </div>
    </Panel>
  )
}

function HangarInput({ value, onSave }: { value: string[]; onSave: (v: string[]) => void }) {
  const [v, setV] = useState(value.join(' '))
  useEffect(() => setV(value.join(' ')), [value])
  return (
    <Input
      value={v}
      className="mono"
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        const next = v.split(/[\s,]+/).filter(Boolean)
        if (next.join(' ') !== value.join(' ')) onSave(next)
      }}
    />
  )
}

function WarningsPanel({ data }: { data: PlanResultOut }) {
  const warnings = data.result?.warnings ?? []
  return (
    <Panel title={`Warnings · ${warnings.length}`} testId="plan.warnings">
      <ul className="flex flex-col gap-1 text-ui">
        {warnings.map((w, i) => (
          <li key={i} className="text-warn">
            {w.text}
          </li>
        ))}
      </ul>
    </Panel>
  )
}
