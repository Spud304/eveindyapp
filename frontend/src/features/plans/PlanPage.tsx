import { useEffect, useState } from 'react'
import { useNavigate, useParams } from '@tanstack/react-router'
import { usePageTitle } from '@/hooks/usePageTitle'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useLocalCopy } from '@/hooks/useLocalCopy'
import { useMe, usePlan, usePlanMutations, usePlanResult, useStations, useTypeSearch } from '@/lib/api/hooks'
import type { PlanOut, PlanResultOut, TypeOut } from '@/lib/api/client'
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
              {tab === 'blueprints' ? <BlueprintsTab data={r} lookups={lookups} /> : null}
              {tab === 'schedule' ? <ScheduleTab data={r} lookups={lookups} /> : null}
              {tab === 'cost' ? <CostTab data={r} /> : null}
            </>
          ) : null}
          {tab === 'progress' ? (
            <Empty hint="The tracker (step 5) matches your ESI jobs to this plan once it is active.">Progress tracking is not built yet.</Empty>
          ) : null}
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <LinesPanel plan={p} />
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
  const search = useTypeSearch(useDebouncedValue(q), 'buildable')
  const lines = p.lines.map((l) => ({ type_id: l.type_id, quantity: l.quantity }))
  const save = (next: typeof lines) => setLines.mutate({ id: p.id, lines: next })
  return (
    <Panel title="Build" testId="plan.lines">
      <ul className="mb-2 flex flex-col gap-1">
        {p.lines.map((l, i) => (
          <li key={l.id} className="flex items-center gap-2" data-testid={`plan.line.${l.type_id}`}>
            <QtyInput
              value={l.quantity}
              onSave={(qty) => save(lines.map((x, j) => (j === i ? { ...x, quantity: qty } : x)))}
              testId={`plan.line.${l.type_id}.qty`}
            />
            <span className="min-w-0 flex-1 truncate">{l.name}</span>
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
          const at = lines.findIndex((l) => l.type_id === t.id)
          save(at >= 0 ? lines.map((l, j) => (j === at ? { ...l, quantity: l.quantity + 1 } : l)) : [...lines, { type_id: t.id, quantity: 1 }])
          setQ('')
        }}
        placeholder="add item to build"
        testId="plan.add-line"
      />
    </Panel>
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
