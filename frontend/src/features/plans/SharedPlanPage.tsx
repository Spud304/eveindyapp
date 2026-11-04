import { useState } from 'react'
import { useParams } from '@tanstack/react-router'
import { usePageTitle } from '@/hooks/usePageTitle'
import { usePlanView, useSharedLink } from '@/lib/api/hooks'
import { ApiError, type PlanResultOut, type SharedPlanOut } from '@/lib/api/client'
import { Badge, Empty, ErrorText, Mono, PageHeader, Panel, Tabs } from '@/components/ui'
import { ScheduleTab, ShoppingTab, type Lookups } from './tabs'
import { ProgressView } from './progress'

type TabKey = 'shopping' | 'schedule' | 'progress'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'shopping', label: 'Shopping list' },
  { key: 'schedule', label: 'Schedule' },
  { key: 'progress', label: 'Progress' },
]

/** A plan shared by link: /shared/<token>, no login. Station and character names are aliases. */
export function SharedLinkPage() {
  const { token } = useParams({ from: '/shared/$token' })
  const view = useSharedLink(token)
  if (isNotFound(view.error)) return <Empty testId="shared.missing">This link does not lead to a shared plan. It may have been replaced or turned off.</Empty>
  if (view.error) return <ErrorText error={view.error} />
  return view.data ? <SharedView data={view.data} /> : <Loading />
}

/** The read-only view for corp members of a corp-shared plan, and for the owner as a preview. */
export function PlanViewPage() {
  const { planId } = useParams({ from: '/plans/$planId/view' })
  const view = usePlanView(Number(planId))
  if (isNotFound(view.error)) return <Empty testId="shared.missing">This plan is not shared with you.</Empty>
  if (view.error) return <ErrorText error={view.error} />
  return view.data ? <SharedView data={view.data} /> : <Loading />
}

/** Only a 404 means "not shared"; any other failure is shown as the error it is. */
function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

function Loading() {
  return <p className="text-ui text-muted">Loading plan</p>
}

function SharedView({ data }: { data: SharedPlanOut }) {
  usePageTitle(data.name)
  const [tab, setTab] = useState<TabKey>('shopping')
  const r = data.result
  // The tabs take a plan result; viewers get no reservation details or feed health (it names
  // the owner's characters).
  const asResult = {
    plan_id: data.plan_id ?? 0,
    error: data.error,
    prices: 'jita',
    priced_at_average: 0,
    result: r,
    effective_rules: { item_blacklist: [], buy_categories: [], overrides: { blacklist_add: [], blacklist_remove: [], categories: {} } },
    reservation: { reserves: false, claims: {}, held_elsewhere: {} },
    inputs: { as_of: null, problems: [] },
  } as PlanResultOut
  const lookups: Lookups = {
    characters: new Map(Object.entries(data.characters).map(([k, v]) => [Number(k), v])),
    stations: new Map(Object.entries(data.stations).map(([k, v]) => [Number(k), v])),
  }
  return (
    <>
      <PageHeader
        title={<span data-testid="shared.name">{data.name}</span>}
        context={
          <>
            <Badge tone="muted" title="shared with you; only the owner can change it">
              read-only
            </Badge>
            {data.anonymized ? (
              <Badge tone="info" testId="shared.anonymized" title="shared by link: station and character names are replaced">
                names hidden
              </Badge>
            ) : null}
            {data.owner_name ? <span>by {data.owner_name}</span> : null}
            {r ? (
              <>
                <span title="materials to buy plus job fees">
                  total <Mono className="text-fg">{Math.round(r.costs.total).toLocaleString('en-US')}</Mono> ISK
                </span>
                <span title="wall-clock until the last scheduled job ends">
                  <Mono className="text-fg">{(r.total_seconds / 86400).toFixed(1)}</Mono> days
                </span>
              </>
            ) : null}
          </>
        }
      />
      <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
        <div className="min-w-0">
          <Tabs tabs={TABS} value={tab} onChange={setTab} testId="shared.tabs" />
          {data.error ? <ErrorText error={new Error(data.error)} /> : null}
          {r ? (
            <>
              {tab === 'shopping' ? <ShoppingTab data={asResult} /> : null}
              {tab === 'schedule' ? <ScheduleTab data={asResult} lookups={lookups} /> : null}
            </>
          ) : null}
          {tab === 'progress' ? <ProgressView d={data.progress} /> : null}
        </div>
        <Panel title="Build" testId="shared.lines">
          <ul className="flex flex-col gap-1">
            {data.lines.map((l) => (
              <li key={l.type_id} className="flex items-center gap-2" data-testid={`shared.line.${l.type_id}`}>
                <Mono className="w-16 text-right">{l.quantity}</Mono>
                <span className="min-w-0 flex-1 truncate">{l.name}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </>
  )
}
