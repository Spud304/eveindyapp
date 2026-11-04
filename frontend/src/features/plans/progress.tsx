import clsx from 'clsx'
import { useNow } from '@/hooks/useNow'
import { useJobLinkMutations, usePlanProgress } from '@/lib/api/hooks'
import type { JobRow, ProgressOut, ProgressRow } from '@/lib/api/client'
import { duration, qty, since } from '@/lib/format'
import { Badge, Button, Empty, ErrorText, Mono, Num, Panel, Table } from '@/components/ui'

const STATUS_TONE = { active: 'info', paused: 'warn', ready: 'ok', delivered: 'muted' } as const

/** Delivered, ready, running and still-to-start runs as one bar, so the state reads at a glance. */
function Bar({ row }: { row: ProgressRow }) {
  const parts = [
    { n: row.delivered_runs, cls: 'bg-stock', label: 'delivered' },
    { n: row.ready_runs, cls: 'bg-ok/60', label: 'ready' },
    { n: row.running_runs, cls: 'bg-info', label: 'running' },
    { n: row.remaining_runs, cls: 'bg-panel-2', label: 'to start' },
  ]
  const total = parts.reduce((s, p) => s + p.n, 0)
  if (!total) return null
  return (
    <div className="flex h-2 w-40 overflow-hidden rounded border border-line" title={parts.map((p) => `${p.n} ${p.label}`).join(', ')}>
      {parts.map((p) => (p.n ? <div key={p.label} className={p.cls} style={{ width: `${(100 * p.n) / total}%` }} /> : null))}
    </div>
  )
}

function JobTable({ jobs, action, testId }: { jobs: (JobRow & { source?: string })[]; action: (j: JobRow) => React.ReactNode; testId: string }) {
  const now = useNow()
  return (
    <Table hover>
      <thead>
        <tr>
          <th>Status</th>
          <th className="text-right">Left</th>
          <th>Activity</th>
          <th>Making</th>
          <th className="text-right">Runs</th>
          <th>Installer</th>
          <th>Started</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {jobs.map((j) => {
          const ms = new Date(j.end_date).getTime() - now
          return (
            <tr key={j.job_id} data-testid={`${testId}.${j.job_id}`}>
              <td>
                <Badge tone={STATUS_TONE[j.status as keyof typeof STATUS_TONE] ?? 'muted'}>{j.status}</Badge>
                {j.source === 'manual' ? (
                  <Badge tone="accent" title="linked by you">
                    manual
                  </Badge>
                ) : null}
              </td>
              <Num>{j.status === 'active' ? duration(ms / 1000) : ''}</Num>
              <td>{j.activity}</td>
              <td>{j.product_name ?? j.blueprint_name}</td>
              <Num>{qty(j.runs)}</Num>
              <td className={j.mine ? '' : 'text-muted'}>{j.installer_name}</td>
              <td className="text-muted" title={new Date(j.start_date).toLocaleString()}>
                {since(j.start_date)}
              </td>
              <td className="text-right">{action(j)}</td>
            </tr>
          )
        })}
      </tbody>
    </Table>
  )
}

export function ProgressTab({ planId }: { planId: number }) {
  const progress = usePlanProgress(planId)
  const { link, unlink } = useJobLinkMutations(planId)
  const d = progress.data
  if (progress.error) return <ErrorText error={progress.error} />
  if (!d) return <p className="text-ui text-muted">Loading progress</p>
  const busy = link.isPending || unlink.isPending
  return <ProgressView d={d} actions={{ busy, link: (id) => link.mutate(id), unlink: (id) => unlink.mutate(id) }} />
}

type LinkActions = { busy: boolean; link: (jobId: number) => void; unlink: (jobId: number) => void }

/** Progress rows and linked jobs. Without `actions` it is read-only (a shared plan). */
export function ProgressView({ d, actions }: { d: ProgressOut; actions?: LinkActions }) {
  const busy = actions?.busy ?? false
  return (
    <div className="flex flex-col gap-4">
      {!actions ? null : !d.active ? (
        <p className="text-ui text-warn" data-testid="plan.progress.inactive">
          This plan is not active, so new jobs are not matched to it. Make it active, or link jobs below by hand.
        </p>
      ) : (
        <p className="text-ui text-muted">
          New jobs for these blueprints started since <Mono className="text-fg">{d.activated_at ? new Date(d.activated_at).toLocaleString() : ''}</Mono> are linked
          automatically after each sync.
        </p>
      )}
      <Panel title="By blueprint" flush testId="plan.progress.rows">
        {d.rows.length === 0 ? (
          <Empty>Nothing to build yet.</Empty>
        ) : (
          <Table hover>
            <thead>
              <tr>
                <th>Blueprint</th>
                <th>Activity</th>
                <th />
                <th className="text-right" title="runs still to start">
                  To start
                </th>
                <th className="text-right">Running</th>
                <th className="text-right">Ready</th>
                <th className="text-right">Delivered</th>
                <th className="text-right" title="units made beyond what the plan needs">
                  Over plan
                </th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => {
                const done = r.remaining_runs === 0 && r.running_runs + r.ready_runs + r.delivered_runs > 0
                return (
                  <tr key={`${r.blueprint_type_id}.${r.activity}`} data-testid={`plan.progress.row.${r.blueprint_type_id}.${r.activity}`}>
                    <td>
                      {r.name}
                      {done ? (
                        <Badge tone="ok" title="every run needed is started or done">
                          all started
                        </Badge>
                      ) : null}
                    </td>
                    <td className="text-muted">{r.activity}</td>
                    <td>
                      <Bar row={r} />
                    </td>
                    <Num className={clsx(r.remaining_runs === 0 && 'text-muted')}>{qty(r.remaining_runs)}</Num>
                    <Num>{r.running_runs ? qty(r.running_runs) : ''}</Num>
                    <Num>{r.ready_runs ? qty(r.ready_runs) : ''}</Num>
                    <Num>{r.delivered_runs ? qty(r.delivered_runs) : ''}</Num>
                    <Num className={r.over_plan ? 'text-warn' : ''}>{r.over_plan ? qty(r.over_plan) : ''}</Num>
                  </tr>
                )
              })}
            </tbody>
          </Table>
        )}
      </Panel>
      <Panel title={`Linked jobs · ${d.jobs.length}`} flush testId="plan.progress.jobs">
        {d.jobs.length === 0 ? (
          <Empty hint="Jobs for this plan's blueprints are linked after the next sync once the plan is active.">No jobs linked yet.</Empty>
        ) : (
          <JobTable
            jobs={d.jobs}
            testId="plan.progress.job"
            action={(j) =>
              actions ? (
              <Button small variant="ghost" disabled={busy} onClick={() => actions.unlink(j.job_id)} title="stop counting this job toward the plan; it is not matched again" testId={`plan.progress.unlink.${j.job_id}`}>
                Unlink
              </Button>
              ) : null
            }
          />
        )}
      </Panel>
      {actions && d.candidates.length ? (
        <Panel title={`Other recent jobs for these blueprints · ${d.candidates.length}`} flush testId="plan.progress.candidates">
          <JobTable
            jobs={d.candidates}
            testId="plan.progress.candidate"
            action={(j) => (
              <Button small disabled={busy} onClick={() => actions.link(j.job_id)} title="count this job toward the plan" testId={`plan.progress.link.${j.job_id}`}>
                Link
              </Button>
            )}
          />
        </Panel>
      ) : null}
    </div>
  )
}
