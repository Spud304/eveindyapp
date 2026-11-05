import { Fragment, useMemo, useState } from 'react'
import { useCopy } from '@/hooks/useCopy'
import { useBlueprintOptions, usePlanMutations } from '@/lib/api/hooks'
import type { BlueprintChoice, BlueprintPlan, ChoiceIO, MoveOut, PlanOut, PlanResultOut, PurchaseOption } from '@/lib/api/client'
import { duration, isk, iskExact, m3, pct, qty } from '@/lib/format'
import { Badge, Button, Empty, Input, Mono, Num, Panel, Select, Table, Why } from '@/components/ui'

export type Lookups = { characters: Map<number, string>; stations: Map<number, string> }

const SOURCE_TONE = { bpo: 'ok', bpc: 'info', copy: 'info', bought: 'warn', invention: 'accent', missing: 'bad' } as const

function names(data: PlanResultOut) {
  const r = data.result!
  const out = new Map<number, string>()
  for (const i of r.items) out.set(i.type_id, i.name)
  for (const b of r.blueprints) out.set(b.type_id, b.name)
  return out
}

// --- shopping list -------------------------------------------------------------------------

export function ShoppingTab({ data, stale = false }: { data: PlanResultOut; stale?: boolean }) {
  const r = data.result!
  const held = data.reservation.held_elsewhere
  const { copied, copy } = useCopy()
  // EVE multibuy / Janice paste: "name<TAB>quantity" per line.
  const paste = r.shopping_list.map((s) => `${s.name}\t${s.quantity}`).join('\n')
  const onHand = r.items.filter((i) => i.on_hand_used > 0)
  const volume = r.shopping_list.reduce((sum, s) => sum + s.volume, 0)
  const moved = new Map<number, number>()
  for (const m of data.moves) if (m.kind === 'stock') moved.set(m.type_id, (moved.get(m.type_id) ?? 0) + m.quantity)
  return (
    <div className="flex flex-col gap-4">
      <Panel
        title={`To buy · ${r.shopping_list.length}`}
        testId="plan.shopping"
        flush
        actions={
          <>
            <span className="text-ui text-muted" data-testid="plan.shopping.volume" title="packaged volume of everything to buy">
              <Mono className="text-fg">{m3(volume)}</Mono>
            </span>
            <span className="text-ui text-muted">
              <Mono className="text-fg">{isk(r.costs.materials + r.costs.invention_inputs)}</Mono>
            </span>
            <Button
              small
              onClick={() => void copy(paste, true, 'shopping list')}
              disabled={!paste || stale}
              testId="plan.shopping.copy"
              title={stale ? 'recomputing' : 'copy as name and quantity per line (EVE multibuy, Janice)'}
            >
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
                <th className="text-right" title={data.prices === 'jita' ? 'average paid per unit, buying Jita 4-4 sell orders cheapest first' : 'CCP average price'}>
                  Unit
                </th>
                <th className="text-right">Total</th>
                <th className="text-right" title="packaged volume">
                  Volume
                </th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {r.shopping_list.map((s) => (
                <tr key={s.type_id} data-testid={`plan.shopping.${s.type_id}`}>
                  <td>{s.name}</td>
                  <Num>{qty(s.quantity)}</Num>
                  <Num className="text-muted">
                    {s.unit_price == null ? <span className="text-warn">no price</span> : isk(s.unit_price)}
                    {data.prices === 'jita' && s.price_source === 'average' && s.unit_price != null ? (
                      <span className="ml-1 text-label text-warn" title={s.on_sale === 0 ? 'nothing on sale at Jita 4-4: CCP average price' : 'not looked up at Jita: CCP average price'}>
                        avg
                      </span>
                    ) : null}
                    {s.on_sale != null && s.on_sale > 0 && s.on_sale < s.quantity ? (
                      <span className="ml-1 text-label text-warn" title="the rest is priced at the dearest order">
                        only {qty(s.on_sale)} on sale
                      </span>
                    ) : null}
                  </Num>
                  <Num title={iskExact(s.total_price)}>{isk(s.total_price)}</Num>
                  <Num className="text-muted">{m3(s.volume)}</Num>
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
                    {moved.get(i.type_id) ? (
                      <Badge tone="warn" title="not where the jobs that use it run; see To move">
                        move {qty(moved.get(i.type_id)!)}
                      </Badge>
                    ) : null}{' '}
                    {held[i.type_id] ? <span className="text-label text-warn">{held[i.type_id].map((h) => `${qty(h.quantity)} held by ${h.plan_name}`).join('; ')}</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>
      ) : null}
      {data.moves.length ? <MovesPanel moves={data.moves} /> : null}
    </div>
  )
}

/** What the plan's jobs use that is not at the station they run at: hangar stock elsewhere,
 *  or items another station builds. One table per trip (from a hangar or a station's job
 *  output to a station). */
function MovesPanel({ moves }: { moves: MoveOut[] }) {
  const trips = new Map<string, MoveOut[]>()
  for (const m of moves) {
    const key = m.kind === 'built' ? `built|${m.from_station_id}|${m.to_station_id}` : `stock|${m.from_location_id}|${m.from_hangar}|${m.to_station_id}`
    trips.set(key, [...(trips.get(key) ?? []), m])
  }
  const total = moves.reduce((sum, m) => sum + m.volume, 0)
  return (
    <Panel
      title={`To move · ${moves.length}`}
      testId="plan.moves"
      actions={
        <span className="text-ui text-muted" data-testid="plan.moves.volume">
          <Mono className="text-fg">{m3(total)}</Mono>
        </span>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-label text-muted">
          Items the jobs use that are not where they run: stock in another hangar, or made at another station. What a station makes and holds is used there first.
        </p>
        {[...trips.entries()].map(([key, ms]) => (
          <div key={key} data-testid="plan.moves.trip">
            <div className="mb-1 flex flex-wrap items-baseline gap-x-2 text-ui">
              <span>
                {ms[0].from_name} <span className="text-muted">· {ms[0].kind === 'built' ? 'built there' : ms[0].from_hangar}</span>
              </span>
              <span className="text-muted">→</span>
              <span>{ms[0].to_name}</span>
              <Mono className="ml-auto text-muted">{m3(ms.reduce((sum, m) => sum + m.volume, 0))}</Mono>
            </div>
            <Table hover>
              <thead>
                <tr>
                  <th>Item</th>
                  <th className="text-right">Quantity</th>
                  <th className="text-right">Volume</th>
                </tr>
              </thead>
              <tbody>
                {ms.map((m) => (
                  <tr key={m.type_id} data-testid={`plan.moves.${m.type_id}`}>
                    <td>{m.name}</td>
                    <Num>{qty(m.quantity)}</Num>
                    <Num className="text-muted">{m3(m.volume)}</Num>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        ))}
      </div>
    </Panel>
  )
}

// --- blueprints ----------------------------------------------------------------------------

export function BlueprintsTab({ data, lookups, plan }: { data: PlanResultOut; lookups: Lookups; plan: PlanOut }) {
  const r = data.result!
  const jobsById = useMemo(() => new Map(r.jobs.map((j) => [j.job_id, j])), [r.jobs])
  const productNames = names(data)
  const [buying, setBuying] = useState<number | null>(null)
  const [adjusting, setAdjusting] = useState<number | null>(null)
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
              <Fragment key={b.type_id}>
                <tr data-testid={`plan.blueprint.${b.type_id}`} className="align-top">
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
                  {b.activity === 'manufacturing' ? (
                    <Button
                      small
                      variant="ghost"
                      className="mt-0.5"
                      testId={`plan.blueprint.${b.type_id}.buy`}
                      onClick={() => setBuying(buying === b.type_id ? null : b.type_id)}
                      title="what buying BPCs or an extra BPO would save and cost"
                    >
                      {buying === b.type_id ? 'Hide buy options' : 'Buy options'}
                    </Button>
                  ) : null}
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
                  {b.activity === 'manufacturing' ? (
                    <Button
                      small
                      variant="ghost"
                      className="mt-0.5"
                      testId={`plan.blueprint.${b.type_id}.adjust`}
                      onClick={() => setAdjusting(adjusting === b.type_id ? null : b.type_id)}
                      title={b.invention ? 'set ME / TE or the decryptor for this plan' : 'set ME / TE for this plan'}
                    >
                      {adjusting === b.type_id ? 'Close' : b.invention ? 'ME / TE / decryptor' : 'ME / TE'}
                    </Button>
                  ) : null}
                </td>
                <td className="max-w-80">
                  <div>{b.station.station_id != null ? (lookups.stations.get(b.station.station_id) ?? `station ${b.station.station_id}`) : <span className="text-bad">none</span>}</div>
                  <Why text={b.station.reason.text} />
                </td>
                </tr>
                {adjusting === b.type_id ? (
                  <tr>
                    <td colSpan={5} className="bg-panel-2">
                      <OverridePanel plan={plan} bp={b} />
                    </td>
                  </tr>
                ) : null}
                {buying === b.type_id ? (
                  <tr>
                    <td colSpan={5} className="bg-panel-2">
                      <PurchasePanel plan={plan} bp={b} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            )
          })}
        </tbody>
      </Table>
    </Panel>
  )
}

/** ME / TE overrides (blank: what the blueprint or invention gives) and, for invented
 * blueprints, the decryptor. For when ESI's ME is wrong or the automatic decryptor is unwanted. */
function OverridePanel({ plan, bp }: { plan: PlanOut; bp: BlueprintPlan }) {
  const { setChoice } = usePlanMutations()
  const current = storedChoice(plan, bp.type_id)
  const [me, setMe] = useState(current.me != null ? String(current.me) : '')
  const [te, setTe] = useState(current.te != null ? String(current.te) : '')
  const num = (v: string) => (v.trim() === '' ? null : Number(v))
  const valid = (v: string, lo: number, hi: number) => v.trim() === '' || (Number.isInteger(Number(v)) && Number(v) >= lo && Number(v) <= hi)
  const ok = valid(me, -10, 10) && valid(te, 0, 20)
  const decryptor = String(current.decryptor ?? 'auto')
  const save = (change: Partial<ChoiceIO>) => setChoice.mutate({ id: plan.id, blueprintId: bp.type_id, choice: { ...current, ...change } })
  return (
    <div className="flex flex-wrap items-end gap-3 p-1" data-testid={`plan.blueprint.${bp.type_id}.override`}>
      <label className="flex flex-col gap-0.5 text-label text-muted">
        ME
        <Input value={me} onChange={(e) => setMe(e.target.value)} placeholder="auto" className="w-16 text-right mono" testId={`plan.blueprint.${bp.type_id}.me`} />
      </label>
      <label className="flex flex-col gap-0.5 text-label text-muted">
        TE
        <Input value={te} onChange={(e) => setTe(e.target.value)} placeholder="auto" className="w-16 text-right mono" testId={`plan.blueprint.${bp.type_id}.te`} />
      </label>
      <Button small disabled={!ok} onClick={() => save({ me: num(me), te: num(te) })} testId={`plan.blueprint.${bp.type_id}.save-me`} title={ok ? 'blank means the blueprint’s own value' : 'ME -10 to 10, TE 0 to 20'}>
        Save ME / TE
      </Button>
      {bp.invention ? (
        <label className="flex flex-col gap-0.5 text-label text-muted">
          Decryptor
          <Select
            value={decryptor}
            testId={`plan.blueprint.${bp.type_id}.decryptor`}
            onChange={(e) => {
              const v = e.target.value
              save({ decryptor: v === 'auto' || v === 'none' ? v : Number(v) })
            }}
          >
            <option value="auto">automatic (lowest total cost)</option>
            <option value="none">none</option>
            {bp.invention.options
              .filter((o) => o.decryptor_type_id != null)
              .map((o) => (
                <option key={o.decryptor_type_id} value={String(o.decryptor_type_id)}>
                  {o.name}
                </option>
              ))}
          </Select>
        </label>
      ) : null}
    </div>
  )
}

/** The stored choice for a blueprint, as the API takes it back. */
function storedChoice(plan: PlanOut, bpId: number): ChoiceIO {
  return (plan.choices[String(bpId)] ?? {}) as ChoiceIO
}

function toChoiceIO(c: BlueprintChoice): ChoiceIO {
  return {
    me: c.me_override ?? null,
    te: c.te_override ?? null,
    decryptor: c.decryptor,
    buy_bpcs: c.buy_bpcs,
    bpc_runs: c.bpc_runs ?? null,
    bpc_me: c.bpc_me,
    bpc_te: c.bpc_te,
    bpc_price: c.bpc_price ?? null,
    extra_bpos: c.extra_bpos,
    bpo_me: c.bpo_me,
    bpo_te: c.bpo_te,
  }
}

function PurchasePanel({ plan, bp }: { plan: PlanOut; bp: BlueprintPlan }) {
  const opts = useBlueprintOptions(plan.id, bp.type_id, true)
  const { setChoice } = usePlanMutations()
  const current = storedChoice(plan, bp.type_id)
  const [price, setPrice] = useState(current.bpc_price != null ? String(current.bpc_price) : '')
  const save = (choice: ChoiceIO) => setChoice.mutate({ id: plan.id, blueprintId: bp.type_id, choice })
  const buyingNow = (current.buy_bpcs ?? 0) > 0 || (current.extra_bpos ?? 0) > 0
  const apply = (o: PurchaseOption) => {
    const choice = toChoiceIO(o.choice)
    if (o.kind === 'bpcs' && price.trim() !== '' && Number(price) >= 0) choice.bpc_price = Number(price)
    save(choice)
  }
  return (
    <div className="flex flex-col gap-2 py-1" data-testid={`plan.blueprint.${bp.type_id}.options`}>
      {buyingNow ? (
        <div className="flex items-center gap-2">
          <span>
            Buying{(current.buy_bpcs ?? 0) > 0 ? ` ${current.buy_bpcs} BPC(s) of ${current.bpc_runs ?? 'max'} runs` : ''}
            {(current.extra_bpos ?? 0) > 0 ? ` ${current.extra_bpos} extra BPO(s)` : ''}.
          </span>
          <Button small testId={`plan.blueprint.${bp.type_id}.unbuy`} onClick={() => save({ ...current, buy_bpcs: 0, bpc_runs: null, extra_bpos: 0 })}>
            Stop buying
          </Button>
        </div>
      ) : null}
      {opts.isFetching && !opts.data ? <span className="text-label text-muted">working out options (one plan run each)</span> : null}
      {opts.data?.note ? <span className="text-label text-muted">{opts.data.note}</span> : null}
      {opts.data?.options.map((o) => (
        <div key={o.kind} className="flex flex-wrap items-center gap-2" data-testid={`plan.blueprint.${bp.type_id}.option.${o.kind}`}>
          <Badge tone={o.seconds_saved > 0 ? 'ok' : 'muted'}>{o.seconds_saved > 0 ? `${duration(o.seconds_saved)} sooner` : 'no faster'}</Badge>
          <span className="min-w-0 flex-1">{o.reason.text}</span>
          {o.kind === 'bpcs' ? (
            <Input
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="ISK per BPC"
              inputMode="numeric"
              className="w-32"
              testId={`plan.blueprint.${bp.type_id}.bpc-price`}
              title="BPCs sell on contracts, so there is no market price; enter what you would pay"
            />
          ) : null}
          <Button small variant="primary" testId={`plan.blueprint.${bp.type_id}.apply.${o.kind}`} onClick={() => apply(o)}>
            Buy
          </Button>
        </div>
      ))}
    </div>
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
              <td className="max-w-80">
                <div>{j.schedule.character_id != null ? (lookups.characters.get(j.schedule.character_id) ?? j.schedule.character_id) : <span className="text-bad">nobody</span>}</div>
                <Why text={j.schedule.reason.text} />
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

// --- items ---------------------------------------------------------------------------------

/** Every item in the merged tree: built or bought and why, how much is needed, on hand, made
 * and left over. Each built or blacklisted item can be flipped for this plan only. */
export function ItemsTab({ data, plan }: { data: PlanResultOut; plan: PlanOut }) {
  const r = data.result!
  const { setItemRule } = usePlanMutations()
  const buyHere = new Set(plan.blacklist_add)
  const buildHere = new Set(plan.blacklist_remove)
  const lines = new Set(plan.lines.map((l) => l.type_id))
  const items = [...r.items].sort((a, b) => Number(lines.has(b.type_id)) - Number(lines.has(a.type_id)) || a.decision.localeCompare(b.decision) || a.name.localeCompare(b.name))
  const set = (typeId: number, mode: 'buy' | 'build' | 'default') => setItemRule.mutate({ id: plan.id, typeId, mode })
  return (
    <Panel title={`Items · ${r.items.length}`} testId="plan.items" flush>
      <Table hover>
        <thead>
          <tr>
            <th>Item</th>
            <th>Decision</th>
            <th className="text-right" title="plan lines plus what the plan's jobs consume">
              Needed
            </th>
            <th className="text-right" title="from hangars in this plan's scope">
              On hand
            </th>
            <th className="text-right" title="covered by jobs already running for this plan">
              Started
            </th>
            <th className="text-right">Made</th>
            <th className="text-right" title="made beyond what is needed (whole runs)">
              Left over
            </th>
            <th className="text-right">To buy</th>
            <th>This plan</th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => {
            const isLine = lines.has(i.type_id)
            const override = buyHere.has(i.type_id) ? 'buy' : buildHere.has(i.type_id) ? 'build' : null
            return (
              <tr key={i.type_id} data-testid={`plan.item.${i.type_id}`} className="align-top">
                <td>
                  {i.name}
                  {isLine ? <span className="text-label text-muted"> · plan line</span> : null}
                </td>
                <td className="max-w-80">
                  <Badge tone={i.decision === 'build' ? 'build' : 'muted'}>{i.decision}</Badge>
                  <div>
                    <Why text={i.reason.text} />
                  </div>
                </td>
                <Num>{qty(i.line_quantity + i.input_quantity)}</Num>
                <Num className="text-muted">{i.on_hand_used ? qty(i.on_hand_used) : ''}</Num>
                <Num className="text-muted">{i.started ? qty(i.started) : ''}</Num>
                <Num>{i.produced ? qty(i.produced) : ''}</Num>
                <Num className={i.surplus ? 'text-warn' : 'text-muted'}>{i.surplus ? qty(i.surplus) : ''}</Num>
                <Num>{i.to_buy ? qty(i.to_buy) : ''}</Num>
                <td>
                  {override ? (
                    <Button small variant="ghost" testId={`plan.item.${i.type_id}.default`} onClick={() => set(i.type_id, 'default')} title="follow the account's build rules again">
                      Undo {override}
                    </Button>
                  ) : isLine ? null : i.decision === 'build' ? (
                    <Button small variant="ghost" testId={`plan.item.${i.type_id}.buy`} onClick={() => set(i.type_id, 'buy')} title="buy this item instead of building it, in this plan only">
                      Buy here
                    </Button>
                  ) : i.reason.code === 'buy_blacklist' ? (
                    <Button small variant="ghost" testId={`plan.item.${i.type_id}.build`} onClick={() => set(i.type_id, 'build')} title="build this item although the account blacklist buys it, in this plan only">
                      Build here
                    </Button>
                  ) : null}
                </td>
              </tr>
            )
          })}
        </tbody>
      </Table>
    </Panel>
  )
}

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
            {c.blueprints ? (
              <tr>
                <td className="text-muted">Blueprints bought</td>
                <td className="mono text-right">{isk(c.blueprints)}</td>
              </tr>
            ) : null}
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
        <p className="mt-2 text-label text-muted" data-testid="plan.cost.prices">
          {data.prices === 'jita' ? 'Prices: Jita 4-4 sell orders, cheapest first (refreshed every 5 minutes).' : 'Prices: CCP average prices.'}
          {data.priced_at_average ? ` ${data.priced_at_average} item(s) could not be fetched and use the CCP average.` : ''} Job fees total {isk(feeTotal)}.
        </p>
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
