import { useState } from 'react'
import { useCopy } from '@/hooks/useCopy'
import { useCompressedOre, type OreQuery } from '@/lib/api/hooks'
import type { PlanResultOut } from '@/lib/api/client'
import { isk, m3, pct, qty } from '@/lib/format'
import { Badge, Button, Checkbox, Empty, ErrorText, Field, Mono, Num, Panel, Select, Table } from '@/components/ui'

const CLASSES = [
  { key: 'asteroid', label: 'asteroid ore' },
  { key: 'moon', label: 'moon ore' },
  { key: 'ice', label: 'ice' },
] as const

/** Minerals on the shopping list bought as compressed ore and reprocessed: the cheapest mix. */
export function OrePanel({ planId, data }: { planId: number; data: PlanResultOut }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState<OreQuery>({ ore_classes: 'asteroid' })
  const ore = useCompressedOre(planId, q, open)
  const { copied, copy } = useCopy<'ore' | 'all'>()
  const d = ore.data
  const mix = d?.mix
  const classes = q.ore_classes.split(',').filter(Boolean)
  const toggleClass = (key: string, on: boolean) => {
    const next = on ? [...classes, key] : classes.filter((c) => c !== key)
    if (next.length) setQ({ ...q, ore_classes: next.join(',') })
  }
  const oreText = (mix?.ores ?? []).map((o) => `${o.name}\t${o.quantity}`).join('\n')
  // The whole shopping list with the covered minerals replaced by the ore.
  const covered = new Set((mix?.minerals ?? []).filter((m) => m.needed > 0).map((m) => m.type_id))
  const allText = [...data.result!.shopping_list.filter((s) => !covered.has(s.type_id)).map((s) => `${s.name}\t${s.quantity}`), oreText].filter(Boolean).join('\n')
  const saving = mix && mix.mineral_cost != null ? mix.mineral_cost - mix.ore_cost : null
  // Everything to buy with ore in place of the covered minerals.
  const allVolume = data.result!.shopping_list.filter((s) => !covered.has(s.type_id)).reduce((sum, s) => sum + s.volume, 0) + (mix?.ore_volume ?? 0)
  return (
    <Panel
      title="Minerals as compressed ore"
      testId="plan.ore"
      actions={
        <Button small variant={open ? 'ghost' : 'primary'} onClick={() => setOpen(!open)} testId="plan.ore.toggle">
          {open ? 'Hide' : 'Work it out'}
        </Button>
      }
    >
      {!open ? (
        <p className="text-ui text-muted">The cheapest compressed ore that reprocesses into the minerals above, with your reprocessing skills and a station's rigs.</p>
      ) : (
        <div className="flex flex-col gap-3">
          <ErrorText error={ore.error} />
          {d ? (
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Reprocess at">
                <Select value={d.station_id ?? ''} testId="plan.ore.station" onChange={(e) => setQ({ ...q, station_id: Number(e.target.value) })}>
                  {d.stations.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.detail})
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Character">
                <Select value={d.character_id ?? ''} testId="plan.ore.character" onChange={(e) => setQ({ ...q, character_id: Number(e.target.value) })}>
                  {d.characters.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Prices">
                <Select value={d.prices} testId="plan.ore.prices" onChange={(e) => setQ({ ...q, prices: e.target.value as 'jita' | 'average' })}>
                  <option value="jita">Jita 4-4 sell orders</option>
                  <option value="average">CCP average price</option>
                </Select>
              </Field>
              <div className="flex gap-3 pb-1">
                {CLASSES.map((c) => (
                  <Checkbox key={c.key} label={c.label} checked={classes.includes(c.key)} testId={`plan.ore.class.${c.key}`} onChange={(e) => toggleClass(c.key, e.target.checked)} />
                ))}
              </div>
            </div>
          ) : null}
          {ore.isFetching && !d ? <span className="text-label text-muted">working out the cheapest mix</span> : null}
          {d?.note ? <Empty>{d.note}</Empty> : null}
          {mix && mix.minerals.length ? (
            <>
              <div className="flex flex-wrap items-center gap-3 text-ui" data-testid="plan.ore.summary">
                <span>
                  ore <Mono className="text-fg">{isk(mix.ore_cost)}</Mono> · <Mono className="text-fg" testId="plan.ore.volume">{m3(mix.ore_volume)}</Mono>
                </span>
                <span>
                  vs minerals <Mono className="text-fg">{mix.mineral_cost != null ? isk(mix.mineral_cost) : 'no price'}</Mono> ·{' '}
                  <Mono className="text-fg" testId="plan.ore.mineral-volume">{m3(mix.mineral_volume)}</Mono>
                </span>
                <span title="the whole shopping list with these minerals bought as ore" data-testid="plan.ore.all-volume">
                  whole list with ore <Mono className="text-fg">{m3(allVolume)}</Mono>
                </span>
                {saving != null ? (
                  <Badge tone={saving > 0 ? 'ok' : 'warn'} testId="plan.ore.saving">
                    {saving > 0 ? `ore saves ${isk(saving)}` : `ore costs ${isk(-saving)} more`}
                  </Badge>
                ) : null}
                <span className="ml-auto flex gap-2">
                  <Button small onClick={() => void copy(oreText, 'ore', 'ore list')} disabled={!oreText} testId="plan.ore.copy">
                    {copied === 'ore' ? 'Copied' : 'Copy ore'}
                  </Button>
                  <Button small onClick={() => void copy(allText, 'all', 'shopping list')} disabled={!allText} testId="plan.ore.copy-all" title="the shopping list with these minerals replaced by the ore">
                    {copied === 'all' ? 'Copied' : 'Copy list with ore'}
                  </Button>
                </span>
              </div>
              <p className="text-label text-muted" data-testid="plan.ore.price-note">
                {mix.station_reason.text}.{' '}
                {d?.prices === 'jita'
                  ? 'Prices: Jita 4-4 sell orders, cheapest first, as many as each buy needs (refreshed every 5 minutes).'
                  : 'Prices: CCP average price, no limit on what can be bought.'}
                {d?.priced_at_average ? ` ${d.priced_at_average} item(s) could not be fetched from Jita and use the CCP average price.` : ''}
              </p>
              {mix.warnings.map((w) => (
                <p key={w} className="text-label text-warn">
                  {w}
                </p>
              ))}
              <Table hover>
                <thead>
                  <tr>
                    <th>Ore</th>
                    <th className="text-right">Units</th>
                    <th className="text-right">Yield</th>
                    <th className="text-right" title="average paid per unit">
                      Avg
                    </th>
                    <th className="text-right" title="the dearest sell order bought from">
                      Up to
                    </th>
                    <th className="text-right" title="units on sale at Jita 4-4">
                      On sale
                    </th>
                    <th className="text-right">ISK</th>
                    <th className="text-right">Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {mix.ores.map((o) => (
                    <tr key={o.type_id} data-testid={`plan.ore.line.${o.type_id}`}>
                      <td title={o.reason.text}>{o.name}</td>
                      <Num>{qty(o.quantity)}</Num>
                      <Num>{pct(o.efficiency * 100, 1)}</Num>
                      <Num className="text-muted">{isk(o.unit_price)}</Num>
                      <Num className="text-muted">{o.top_price != null ? isk(o.top_price) : ''}</Num>
                      <Num className="text-muted">{o.on_sale != null ? qty(o.on_sale) : ''}</Num>
                      <Num>{isk(o.total)}</Num>
                      <Num className="text-muted">{m3(o.volume)}</Num>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <Table hover>
                <thead>
                  <tr>
                    <th>Mineral</th>
                    <th className="text-right">Needed</th>
                    <th className="text-right">Made</th>
                    <th className="text-right" title="made beyond what the plan needs">
                      Spare
                    </th>
                    <th className="text-right" title="average per unit when bought as minerals">
                      Avg
                    </th>
                    <th className="text-right" title="units on sale at Jita 4-4">
                      On sale
                    </th>
                    <th className="text-right" title="volume of the needed amount, bought as minerals">
                      Volume
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {mix.minerals.map((m) => (
                    <tr key={m.type_id} data-testid={`plan.ore.mineral.${m.type_id}`}>
                      <td>{d?.names[m.type_id] ?? m.type_id}</td>
                      <Num>{qty(m.needed)}</Num>
                      <Num>{qty(m.produced)}</Num>
                      <Num className="text-muted">{m.surplus ? qty(m.surplus) : ''}</Num>
                      <Num className="text-muted">{m.needed && m.unit_price != null ? isk(m.unit_price) : ''}</Num>
                      <Num className={m.on_sale != null && m.on_sale < m.needed ? 'text-warn' : 'text-muted'}>{m.on_sale != null ? qty(m.on_sale) : ''}</Num>
                      <Num className="text-muted">{m.volume ? m3(m.volume) : ''}</Num>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </>
          ) : null}
        </div>
      )}
    </Panel>
  )
}
