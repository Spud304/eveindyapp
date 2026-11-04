import { useMemo } from 'react'
import { useCopy } from '@/hooks/useCopy'
import type { PlanResultOut } from '@/lib/api/client'
import { duration, isk, iskExact, pct, qty } from '@/lib/format'
import { Badge, Button, Empty, Mono, Num, Panel, Table, Why } from '@/components/ui'

export type Lookups = { characters: Map<number, string>; stations: Map<number, string> }

const SOURCE_TONE = { bpo: 'ok', bpc: 'info', invention: 'accent', missing: 'bad' } as const

function names(data: PlanResultOut) {
  const r = data.result!
  const out = new Map<number, string>()
  for (const i of r.items) out.set(i.type_id, i.name)
  for (const b of r.blueprints) out.set(b.type_id, b.name)
  return out
}

// --- shopping list -------------------------------------------------------------------------

export function ShoppingTab({ data }: { data: PlanResultOut }) {
  const r = data.result!
  const held = data.reservation.held_elsewhere
  const { copied, copy } = useCopy()
  // EVE multibuy / Janice paste: "name<TAB>quantity" per line.
  const paste = r.shopping_list.map((s) => `${s.name}\t${s.quantity}`).join('\n')
  const onHand = r.items.filter((i) => i.on_hand_used > 0)
  return (
    <div className="flex flex-col gap-4">
      <Panel
        title={`To buy · ${r.shopping_list.length}`}
        testId="plan.shopping"
        flush
        actions={
          <>
            <span className="text-ui text-muted">
              <Mono className="text-fg">{isk(r.costs.materials + r.costs.invention_inputs)}</Mono>
            </span>
            <Button small onClick={() => void copy(paste, true, 'shopping list')} disabled={!paste} testId="plan.shopping.copy" title="copy as name and quantity per line (EVE multibuy, Janice)">
              {copied ? 'Copied' : 'Copy list'}
            </Button>
          </>
        }
      >
        {r.shopping_list.length === 0 ? (
          <Empty>Everything comes from your hangars or is built.</Empty>
        ) : (
          <Table hover>
            <thead>
              <tr>
                <th>Item</th>
                <th className="text-right">Quantity</th>
                <th className="text-right" title="CCP average price until a buy-price source exists">
                  Unit
                </th>
                <th className="text-right">Total</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {r.shopping_list.map((s) => (
                <tr key={s.type_id} data-testid={`plan.shopping.${s.type_id}`}>
                  <td>{s.name}</td>
                  <Num>{qty(s.quantity)}</Num>
                  <Num className="text-muted">{s.unit_price == null ? <span className="text-warn">no price</span> : isk(s.unit_price)}</Num>
                  <Num title={iskExact(s.total_price)}>{isk(s.total_price)}</Num>
                  <td>
                    <Why text={s.reason.text} />
                    {held[s.type_id] ? (
                      <span className="ml-1 text-label text-warn">
                        {held[s.type_id].map((h) => `${qty(h.quantity)} held by ${h.plan_name}`).join('; ')}
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>
      {onHand.length ? (
        <Panel title={`From hangars · ${onHand.length}`} testId="plan.on-hand" flush>
          <Table hover>
            <thead>
              <tr>
                <th>Item</th>
                <th className="text-right">Used</th>
                <th className="text-right">Needed</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {onHand.map((i) => (
                <tr key={i.type_id}>
                  <td>{i.name}</td>
                  <Num>{qty(i.on_hand_used)}</Num>
                  <Num className="text-muted">{qty(i.input_quantity)}</Num>
                  <td>
                    {data.reservation.claims[i.type_id] ? <Badge tone="info">reserved</Badge> : null}{' '}
                    {held[i.type_id] ? <span className="text-label text-warn">{held[i.type_id].map((h) => `${qty(h.quantity)} held by ${h.plan_name}`).join('; ')}</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>
      ) : null}
    </div>
  )
}

// --- blueprints ----------------------------------------------------------------------------

export function BlueprintsTab({ data, lookups }: { data: PlanResultOut; lookups: Lookups }) {
  const r = data.result!
  const jobsById = useMemo(() => new Map(r.jobs.map((j) => [j.job_id, j])), [r.jobs])
  const productNames = names(data)
  return (
    <Panel title={`Blueprints · ${r.blueprints.length}`} testId="plan.blueprints" flush>
      <Table hover>
        <thead>
          <tr>
            <th>Blueprint</th>
            <th className="text-right">Runs</th>
            <th>Source</th>
            <th>ME / TE</th>
            <th>Station</th>
          </tr>
        </thead>
        <tbody>
          {r.blueprints.map((b) => {
            const jobs = b.job_ids.map((id) => jobsById.get(id)).filter((j) => j && j.activity === b.activity)
            const first = jobs[0]
            return (
              <tr key={b.type_id} data-testid={`plan.blueprint.${b.type_id}`} className="align-top">
                <td>
                  <div>{b.name}</div>
                  <Why text={`${b.activity} · makes ${productNames.get(b.product_type_id) ?? b.product_type_id}${jobs.length > 1 ? ` · ${jobs.length} jobs` : ''}`} />
                </td>
                <Num>{qty(b.runs)}</Num>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {b.sources.map((s) => (
                      <Badge key={s} tone={SOURCE_TONE[s]}>
                        {s}
                      </Badge>
                    ))}
                  </div>
                  <Why text={b.source_reason.text} />
                  {b.invention ? (
                    <div className="mt-0.5 text-label text-muted">
                      chance <Mono className="text-fg">{pct(b.invention.probability * 100, 1)}</Mono> · {b.invention.attempts} attempts ·{' '}
                      {b.invention.reason.text}
                    </div>
                  ) : null}
                </td>
                <td>
                  {first ? (
                    <>
                      <Mono>
                        {first.me} / {first.te}
                      </Mono>
                      <div>
                        <Why text={first.me_reason.text} />
                      </div>
                    </>
                  ) : null}
                </td>
                <td className="max-w-80">
                  <div>{b.station.station_id != null ? (lookups.stations.get(b.station.station_id) ?? `station ${b.station.station_id}`) : <span className="text-bad">none</span>}</div>
                  <Why text={b.station.reason.text} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </Table>
    </Panel>
  )
}

// --- schedule ------------------------------------------------------------------------------

export function ScheduleTab({ data, lookups }: { data: PlanResultOut; lookups: Lookups }) {
  const r = data.result!
  const productNames = names(data)
  const unscheduled = r.jobs.filter((j) => j.schedule.character_id == null).length
  return (
    <Panel
      title={`Jobs · ${r.jobs.length}`}
      testId="plan.schedule"
      flush
      actions={
        <span className="text-ui text-muted">
          finishes after <Mono className="text-fg">{duration(r.total_seconds)}</Mono>
          {unscheduled ? <span className="ml-2 text-bad">{unscheduled} jobs have no character</span> : null}
        </span>
      }
    >
      <Table hover>
        <thead>
          <tr>
            <th className="text-right" title="time from plan start">
              Start
            </th>
            <th className="text-right">Takes</th>
            <th>Activity</th>
            <th>Blueprint</th>
            <th className="text-right">Runs</th>
            <th>Character</th>
            <th>Station</th>
          </tr>
        </thead>
        <tbody>
          {r.jobs.map((j) => (
            <tr key={j.job_id} data-testid={`plan.job.${j.job_id}`}>
              <Num>{duration(j.schedule.start_seconds)}</Num>
              <Num>{duration(j.schedule.end_seconds - j.schedule.start_seconds)}</Num>
              <td>{j.activity}</td>
              <td>
                {productNames.get(j.blueprint_type_id) ?? j.blueprint_type_id}
                {j.copies > 1 ? <span className="text-muted"> × {j.copies} copies</span> : null}
              </td>
              <Num>{qty(j.runs)}</Num>
              <td title={j.schedule.reason.text}>
                {j.schedule.character_id != null ? (lookups.characters.get(j.schedule.character_id) ?? j.schedule.character_id) : <span className="text-bad">nobody</span>}
              </td>
              <td className="text-muted">{j.station_id != null ? lookups.stations.get(j.station_id) : ''}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  )
}

// --- cost ----------------------------------------------------------------------------------

export function CostTab({ data }: { data: PlanResultOut }) {
  const r = data.result!
  const c = r.costs
  const productNames = names(data)
  const fees = Object.entries(c.job_fees)
  const feeTotal = fees.reduce((sum, [, v]) => sum + (v ?? 0), 0)
  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Panel title="Total" testId="plan.cost.summary">
        <table className="w-full text-ui [&_td]:py-0.5">
          <tbody>
            <tr>
              <td className="text-muted">Materials to buy</td>
              <td className="mono text-right">{isk(c.materials)}</td>
            </tr>
            <tr>
              <td className="text-muted">Invention inputs</td>
              <td className="mono text-right">{isk(c.invention_inputs)}</td>
            </tr>
            {fees.map(([activity, v]) => (
              <tr key={activity}>
                <td className="text-muted">{activity} fees</td>
                <td className="mono text-right">{isk(v)}</td>
              </tr>
            ))}
            <tr className="border-t border-line font-semibold">
              <td>Total</td>
              <td className="mono text-right" title={iskExact(c.total)}>
                {isk(c.total)}
              </td>
            </tr>
          </tbody>
        </table>
        {c.unpriced_type_ids.length ? <p className="mt-2 text-label text-warn">{c.unpriced_type_ids.length} items have no price and are left out.</p> : null}
        <p className="mt-2 text-label text-muted">Prices are CCP average prices. Job fees total {isk(feeTotal)}.</p>
      </Panel>
      <Panel title="Job fees" testId="plan.cost.jobs" flush>
        <Table hover>
          <thead>
            <tr>
              <th>Job</th>
              <th className="text-right">Base</th>
              <th className="text-right">Job cost</th>
              <th className="text-right">Tax</th>
              <th className="text-right">SCC</th>
              <th className="text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {r.jobs.map((j) => (
              <tr key={j.job_id} title={j.cost.reason.text}>
                <td>
                  {productNames.get(j.blueprint_type_id) ?? j.blueprint_type_id} <span className="text-muted">· {j.activity}</span>
                </td>
                <Num className="text-muted">{isk(j.cost.base)}</Num>
                <Num>{isk(j.cost.job_cost)}</Num>
                <Num>{isk(j.cost.facility_tax)}</Num>
                <Num>{isk(j.cost.scc_surcharge + j.cost.security_tax)}</Num>
                <Num>{j.cost.fee == null ? <span className="text-warn">unknown</span> : isk(j.cost.fee)}</Num>
              </tr>
            ))}
          </tbody>
        </Table>
      </Panel>
    </div>
  )
}
