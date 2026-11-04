import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import clsx from 'clsx'
import { usePageTitle } from '@/hooks/usePageTitle'
import { useDashboard, usePlans } from '@/lib/api/hooks'
import type { JobRow } from '@/lib/api/client'
import { duration, qty } from '@/lib/format'
import { Badge, Checkbox, Empty, ErrorText, Mono, Num, PageHeader, Panel, Table } from '@/components/ui'

const STATUS_TONE = { active: 'info', paused: 'warn', ready: 'ok', delivered: 'muted' } as const
const SOON = 24 * 3600 * 1000

function left(job: JobRow, now: number): number {
  return new Date(job.end_date).getTime() - now
}

export function DashboardPage() {
  usePageTitle('Dashboard')
  const dash = useDashboard()
  const plans = usePlans()
  const [mineOnly, setMineOnly] = useState(false)
  const now = Date.now()
  const d = dash.data
  // Ready first (they need delivering), then running by end time, delivered last.
  const order = { ready: 0, active: 1, paused: 2, delivered: 3 } as Record<string, number>
  const jobs = (d?.jobs ?? [])
    .filter((j) => !mineOnly || j.mine)
    .sort((a, b) => (order[a.status] ?? 4) - (order[b.status] ?? 4) || a.end_date.localeCompare(b.end_date))
  const open = jobs.filter((j) => j.status !== 'delivered')
  const soon = open.filter((j) => j.status === 'active' && left(j, now) < SOON)
  const ready = open.filter((j) => j.status === 'ready')
  const active = plans.data?.find((p) => p.is_active)
  return (
    <>
      <PageHeader
        title="Dashboard"
        context={
          <>
            <span>
              <Mono className="text-fg">{open.length}</Mono> jobs open
            </span>
            {ready.length ? (
              <Badge tone="ok" title="finished, waiting to be delivered">
                {ready.length} ready
              </Badge>
            ) : null}
            {soon.length ? <Badge tone="info">{soon.length} finish within 24 h</Badge> : null}
          </>
        }
        actions={<Checkbox label="Only my characters' jobs" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} testId="dashboard.mine" />}
      />
      <ErrorText error={dash.error} />
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Panel title={`Jobs · ${jobs.length}`} flush testId="dashboard.jobs">
          {jobs.length === 0 && !dash.isLoading ? (
            <Empty hint="Jobs arrive with the next sync (every 10 min, or Refresh now in Setup).">No open jobs.</Empty>
          ) : (
            <Table hover>
              <thead>
                <tr>
                  <th>Status</th>
                  <th className="text-right" title="time until the job ends">
                    Left
                  </th>
                  <th>Activity</th>
                  <th>Making</th>
                  <th className="text-right">Runs</th>
                  <th>Installer</th>
                  <th>Where</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => {
                  const ms = left(j, now)
                  return (
                    <tr key={j.job_id} data-testid={`dashboard.job.${j.job_id}`} className={clsx(j.status === 'delivered' && 'text-muted')}>
                      <td>
                        <Badge tone={STATUS_TONE[j.status as keyof typeof STATUS_TONE] ?? 'muted'}>{j.status}</Badge>
                      </td>
                      <Num className={clsx(j.status === 'active' && ms < SOON && 'text-info')} title={new Date(j.end_date).toLocaleString()}>
                        {j.status === 'active' ? duration(ms / 1000) : ''}
                      </Num>
                      <td>{j.activity}</td>
                      <td>{j.product_name ?? j.blueprint_name}</td>
                      <Num>{qty(j.runs)}</Num>
                      <td className={j.mine ? '' : 'text-muted'}>{j.installer_name}</td>
                      <td className="max-w-72 truncate text-muted" title={j.facility_name}>
                        {j.facility_name}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
          )}
        </Panel>
        <div className="flex min-w-0 flex-col gap-4">
          <Panel title="Active plan" testId="dashboard.plan">
            {active ? (
              <div className="flex flex-col gap-1">
                <Link to="/plans/$planId" params={{ planId: String(active.id) }} className="font-medium text-accent hover:underline">
                  {active.name}
                </Link>
                <span className="text-ui text-muted">Progress against your jobs comes with the tracker (step 5).</span>
              </div>
            ) : (
              <span className="text-ui text-muted">
                No active plan. Make one active from its page; new jobs are attributed to it.
              </span>
            )}
          </Panel>
          <Panel title="Slots" testId="dashboard.slots" flush>
            <Table>
              <thead>
                <tr>
                  <th>Character</th>
                  <th className="text-right" title="running / slots from skills">
                    Manufacturing
                  </th>
                  <th className="text-right">Science</th>
                  <th className="text-right">Reactions</th>
                </tr>
              </thead>
              <tbody>
                {(d?.characters ?? []).map((c) => (
                  <tr key={c.character_id}>
                    <td>
                      {c.name}
                      {!c.skills_known ? (
                        <Badge tone="warn" title="skills not synced yet; slot counts assume none">
                          no skills
                        </Badge>
                      ) : null}
                    </td>
                    {c.slots.map((s) => {
                      // Idle reaction slots are not flagged: many builders never run reactions.
                      const idle = s.kind === 'reaction' ? 0 : s.max - s.running - s.ready
                      return (
                        <Num key={s.kind} title={`${s.running} running, ${s.ready} ready to deliver, ${s.max} slots. Whether ready jobs still hold a slot is not confirmed.`}>
                          <span className={clsx(idle > 0 && 'text-warn')}>
                            {s.running}
                            {s.ready ? <span className="text-ok">+{s.ready}</span> : null}/{s.max}
                          </span>
                          {idle > 0 ? <div className="text-label text-warn">{idle} idle</div> : null}
                        </Num>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </Table>
          </Panel>
          {d?.problems.length ? (
            <Panel title={`Needs attention · ${d.problems.length}`} testId="dashboard.problems">
              <ul className="flex flex-col gap-1 text-ui">
                {d.problems.map((p, i) => (
                  <li key={i} className={p.severity === 'bad' ? 'text-bad' : 'text-warn'}>
                    {p.text}{' '}
                    <Link to="/setup" className="text-accent hover:underline">
                      Setup
                    </Link>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>
      </div>
    </>
  )
}
