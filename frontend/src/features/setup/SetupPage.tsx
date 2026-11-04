import { useState } from 'react'
import { usePageTitle } from '@/hooks/usePageTitle'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import {
  useBuildRules,
  useCharacterMutations,
  useMe,
  useRefreshNow,
  useSaveBuildRules,
  useStationMutations,
  useStations,
  useSyncStatus,
  useSystemSearch,
  useTypeNames,
  useTypeSearch,
} from '@/lib/api/hooks'
import type { Activity, DiscoverOut, StationOut, SystemOut, TypeOut } from '@/lib/api/client'
import { ACTIVITIES, BUILD_CATEGORY_LABELS, securityTone, since } from '@/lib/format'
import {
  Badge,
  Button,
  Checkbox,
  Empty,
  ErrorText,
  Input,
  LinkButton,
  Mono,
  PageHeader,
  Panel,
  SearchPicker,
  Table,
} from '@/components/ui'

export function SetupPage() {
  usePageTitle('Setup')
  return (
    <>
      <PageHeader title="Setup" context="characters, stations and build rules every plan uses" />
      <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
        <div className="flex min-w-0 flex-col gap-4">
          <StationsPanel />
          <SyncPanel />
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <CharactersPanel />
          <RulesPanel />
        </div>
      </div>
    </>
  )
}

// --- characters --------------------------------------------------------------------------

function CharactersPanel() {
  const me = useMe()
  const { setMain, unlink } = useCharacterMutations()
  const chars = me.data?.characters ?? []
  return (
    <Panel
      title="Characters"
      testId="setup.characters"
      actions={
        <LinkButton href="/auth/login?mode=link&next=/setup" variant="default" testId="setup.link-character" title="log in with a character to grant this app read access to its skills, assets, blueprints and jobs">
          Link a character
        </LinkButton>
      }
    >
      {chars.length === 0 ? <Empty>No characters.</Empty> : null}
      <ul className="flex flex-col gap-2">
        {chars.map((c) => {
          const esi = c.esi
          return (
            <li key={c.character_id} className="flex flex-wrap items-center gap-2" data-testid={`setup.character.${c.character_id}`}>
              <span className="font-medium">{c.name}</span>
              {c.is_main ? <Badge tone="accent">main</Badge> : null}
              {!esi ? (
                <Badge tone="warn" title="this character has not granted ESI access; link it to use its data">
                  no esi
                </Badge>
              ) : esi.rejected ? (
                <Badge tone="bad" title={esi.error}>
                  token rejected
                </Badge>
              ) : esi.missing_scopes.length ? (
                <Badge tone="warn" title={`missing: ${esi.missing_scopes.join(', ')}`}>
                  {esi.missing_scopes.length} scopes missing
                </Badge>
              ) : (
                <Badge tone="ok">esi ok</Badge>
              )}
              <span className="ml-auto flex gap-1">
                {!esi || esi.rejected || esi.missing_scopes.length ? (
                  <LinkButton href="/auth/login?mode=link&next=/setup" variant="ghost" title="log in with this character again to grant the missing access">
                    Re-link
                  </LinkButton>
                ) : null}
                {!c.is_main ? (
                  <>
                    <Button small variant="ghost" onClick={() => setMain.mutate(c.character_id)} title="name the account after this character">
                      Make main
                    </Button>
                    <Button
                      small
                      variant="ghost"
                      onClick={() => {
                        if (window.confirm(`Remove ${c.name}? Its token is deleted and its skills, assets and blueprints stop counting.`)) unlink.mutate(c.character_id)
                      }}
                    >
                      Remove
                    </Button>
                  </>
                ) : null}
              </span>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}

// --- sync --------------------------------------------------------------------------------

function SyncPanel() {
  const status = useSyncStatus()
  const refresh = useRefreshNow()
  const feeds = status.data?.feeds ?? []
  return (
    <Panel
      title="ESI data"
      testId="setup.sync"
      flush
      actions={
        <>
          {status.data?.queued ? <Badge tone="info">syncing</Badge> : null}
          <Button small onClick={() => refresh.mutate()} disabled={refresh.isPending || status.data?.queued} testId="setup.refresh" title="fetch every linked character and corp now; otherwise jobs refresh every 10 min and the rest hourly">
            Refresh now
          </Button>
        </>
      }
    >
      {feeds.length === 0 ? (
        <Empty hint="Link a character, then refresh.">Nothing fetched yet.</Empty>
      ) : (
        <Table hover>
          <thead>
            <tr>
              <th>Owner</th>
              <th>Feed</th>
              <th>Status</th>
              <th className="text-right">Rows</th>
              <th>Fetched</th>
            </tr>
          </thead>
          <tbody>
            {feeds.map((f) => (
              <tr key={`${f.owner_kind}.${f.owner_id}.${f.feed}`}>
                <td>
                  {f.owner_kind} <Mono className="text-muted">{f.owner_id}</Mono>
                </td>
                <td>{f.feed}</td>
                <td>{f.ok ? <Badge tone="ok">ok</Badge> : <span className="text-bad">{f.error}</span>}</td>
                <td className="mono text-right">{f.rows}</td>
                <td className="text-muted" title={f.fetched_at ?? ''}>
                  {since(f.fetched_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Panel>
  )
}

// --- stations ----------------------------------------------------------------------------

function StationsPanel() {
  const stations = useStations()
  const { discover } = useStationMutations()
  const [found, setFound] = useState<DiscoverOut | null>(null)
  const [adding, setAdding] = useState(false)
  const rows = stations.data ?? []
  return (
    <Panel
      title="Stations"
      testId="setup.stations"
      flush
      actions={
        <>
          <Button small onClick={() => discover.mutate(undefined, { onSuccess: setFound })} disabled={discover.isPending} testId="setup.discover" title="add the structures and stations where your characters and corp have jobs or assets">
            {discover.isPending ? 'Looking' : 'Find from jobs and assets'}
          </Button>
          <Button small variant="ghost" onClick={() => setAdding((a) => !a)} testId="setup.add-station">
            Add by hand
          </Button>
        </>
      }
    >
      {found ? <DiscoverReport found={found} onClose={() => setFound(null)} /> : null}
      {adding ? <AddStation onDone={() => setAdding(false)} /> : null}
      {rows.length === 0 ? (
        <Empty hint="Plans pick the best station for each job. Find yours from your jobs and assets.">No stations.</Empty>
      ) : (
        <Table>
          <thead>
            <tr>
              <th>On</th>
              <th>Station</th>
              <th>Activities</th>
              <th>Rigs</th>
              <th className="text-right" title="facility tax set by the structure owner; ESI cannot read it">
                Tax %
              </th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <StationRow key={s.id} station={s} />
            ))}
          </tbody>
        </Table>
      )}
    </Panel>
  )
}

function DiscoverReport({ found, onClose }: { found: DiscoverOut; onClose: () => void }) {
  const unresolved = Object.entries(found.unresolved)
  const npc = Object.keys(found.asset_only_npc).length
  return (
    <div className="flex flex-wrap items-start gap-2 border-b border-line bg-panel-2 px-3 py-2 text-ui" data-testid="setup.discover-report">
      <span>
        Added <Mono>{found.added.length}</Mono>, already known <Mono>{found.already_known.length}</Mono>.
      </span>
      {unresolved.length ? (
        <span className="text-warn" title={unresolved.map(([id, why]) => `${id}: ${why}`).join('\n')}>
          {unresolved.length} structures could not be read (no docking access).
        </span>
      ) : null}
      {npc ? <span className="text-muted">{npc} NPC stations only hold assets and were not added.</span> : null}
      <Button small variant="ghost" className="ml-auto" onClick={onClose}>
        Close
      </Button>
    </div>
  )
}

function StationRow({ station: s }: { station: StationOut }) {
  const { edit, remove } = useStationMutations()
  const [tax, setTax] = useState(String(s.facility_tax))
  const [rigQuery, setRigQuery] = useState('')
  const rigSearch = useTypeSearch(useDebouncedValue(rigQuery), 'rig')
  const save = (body: Parameters<typeof edit.mutate>[0]['body']) => edit.mutate({ id: s.id, body })
  // StationOut.activities is plain strings; the server only stores Activity values.
  const toggleActivity = (a: Activity) =>
    save({ activities: (s.activities.includes(a) ? s.activities.filter((x) => x !== a) : [...s.activities, a]) as Activity[] })
  return (
    <tr data-testid={`setup.station.${s.id}`} className={s.enabled ? '' : 'opacity-60'}>
      <td>
        <Checkbox checked={s.enabled} onChange={(e) => save({ enabled: e.target.checked })} title="plans only use enabled stations" />
      </td>
      <td className="min-w-56">
        <div className="font-medium">{s.name}</div>
        <div className="flex items-center gap-1.5 text-label text-muted">
          {s.structure_type_name ?? 'NPC station'}
          <span>·</span>
          {s.system_name}
          <Badge tone={securityTone(s.security)}>{s.security?.toFixed(2)}</Badge>
        </div>
      </td>
      <td>
        <div className="flex flex-wrap gap-x-2 gap-y-0.5">
          {ACTIVITIES.map((a) => (
            <Checkbox key={a} label={a} checked={s.activities.includes(a)} onChange={() => toggleActivity(a)} />
          ))}
        </div>
      </td>
      <td className="min-w-72">
        <div className="flex flex-col gap-0.5">
          {s.rig_type_ids.map((id, i) => (
            <span key={id} className="flex items-center gap-1 text-ui">
              {s.rig_names[i]}
              <Button small variant="ghost" title="remove this rig" onClick={() => save({ rig_type_ids: s.rig_type_ids.filter((r) => r !== id) })}>
                ×
              </Button>
            </span>
          ))}
          {s.rig_type_ids.length < 3 ? (
            <SearchPicker<TypeOut>
              value={rigQuery}
              onValue={setRigQuery}
              results={rigSearch.data}
              loading={rigSearch.isFetching}
              render={(t) => t.name}
              onPick={(t) => {
                save({ rig_type_ids: [...s.rig_type_ids, t.id] })
                setRigQuery('')
              }}
              placeholder="add rig"
              testId={`setup.station.${s.id}.rig`}
            />
          ) : null}
        </div>
      </td>
      <td className="text-right">
        <Input
          type="number"
          step="0.1"
          min={0}
          max={100}
          value={tax}
          invalid={!s.tax_confirmed}
          title={s.tax_confirmed ? 'facility tax' : 'not set yet: enter the tax the owner charges'}
          className="w-16 text-right"
          onChange={(e) => setTax(e.target.value)}
          onBlur={() => {
            const v = Number(tax)
            if (!Number.isNaN(v) && (v !== s.facility_tax || !s.tax_confirmed)) save({ facility_tax: v })
          }}
        />
      </td>
      <td>
        <Button
          small
          variant="ghost"
          onClick={() => {
            if (window.confirm(`Remove ${s.name}? Plans stop using it.`)) remove.mutate(s.id)
          }}
        >
          Remove
        </Button>
      </td>
    </tr>
  )
}

function AddStation({ onDone }: { onDone: () => void }) {
  const { add } = useStationMutations()
  const [name, setName] = useState('')
  const [sysQuery, setSysQuery] = useState('')
  const [system, setSystem] = useState<SystemOut | null>(null)
  const [hullQuery, setHullQuery] = useState('')
  const [hull, setHull] = useState<TypeOut | null>(null)
  const systems = useSystemSearch(useDebouncedValue(sysQuery))
  const hulls = useTypeSearch(useDebouncedValue(hullQuery), 'structure')
  return (
    <form
      className="flex flex-wrap items-end gap-2 border-b border-line bg-panel-2 px-3 py-2"
      data-testid="setup.add-station.form"
      onSubmit={(e) => {
        e.preventDefault()
        if (!system || !name) return
        add.mutate(
          { name, system_id: system.id, structure_type_id: hull?.id ?? null, rig_type_ids: [], activities: ['manufacturing'], facility_tax: 0 },
          { onSuccess: onDone },
        )
      }}
    >
      <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="name" testId="setup.add-station.name" />
      <SearchPicker<SystemOut>
        value={system ? system.name : sysQuery}
        onValue={(v) => {
          setSystem(null)
          setSysQuery(v)
        }}
        results={systems.data}
        render={(s) => `${s.name} (${s.security.toFixed(2)})`}
        onPick={setSystem}
        placeholder="solar system"
        testId="setup.add-station.system"
        className="w-44"
      />
      <SearchPicker<TypeOut>
        value={hull ? hull.name : hullQuery}
        onValue={(v) => {
          setHull(null)
          setHullQuery(v)
        }}
        results={hulls.data}
        render={(t) => t.name}
        onPick={setHull}
        placeholder="structure (empty: npc station)"
        testId="setup.add-station.hull"
        className="w-56"
      />
      <Button type="submit" variant="primary" disabled={!system || !name || add.isPending}>
        Add
      </Button>
      <ErrorText error={add.error} />
    </form>
  )
}

// --- build rules -------------------------------------------------------------------------

function RulesPanel() {
  const rules = useBuildRules()
  const save = useSaveBuildRules()
  const [q, setQ] = useState('')
  const search = useTypeSearch(useDebouncedValue(q), 'buildable')
  const blacklist = rules.data?.item_blacklist ?? []
  const buy = rules.data?.buy_categories ?? []
  const names = useTypeNames(blacklist)
  const put = (next: { item_blacklist?: number[]; buy_categories?: string[] }) =>
    save.mutate({ item_blacklist: next.item_blacklist ?? blacklist, buy_categories: (next.buy_categories ?? buy) as typeof buy })
  return (
    <Panel title="Build rules" testId="setup.rules">
      <p className="mb-2 text-ui text-muted">Account defaults. Each plan can flip them for itself. Anything bought stops the tree there.</p>
      <div className="mb-3 flex flex-col gap-1">
        <span className="text-label font-semibold uppercase tracking-wide text-muted">Always buy</span>
        {Object.entries(BUILD_CATEGORY_LABELS).map(([key, label]) => (
          <Checkbox
            key={key}
            label={label}
            checked={buy.includes(key as (typeof buy)[number])}
            testId={`setup.rules.${key}`}
            onChange={(e) => put({ buy_categories: e.target.checked ? [...buy, key] : buy.filter((c) => c !== key) })}
          />
        ))}
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-label font-semibold uppercase tracking-wide text-muted">Item blacklist (always buy)</span>
        {blacklist.map((id) => (
          <span key={id} className="flex items-center gap-1">
            {names.data?.get(id) ?? <Mono>{id}</Mono>}
            <Button small variant="ghost" onClick={() => put({ item_blacklist: blacklist.filter((b) => b !== id) })} title="build this again">
              ×
            </Button>
          </span>
        ))}
        <SearchPicker<TypeOut>
          value={q}
          onValue={setQ}
          results={search.data}
          loading={search.isFetching}
          render={(t) => t.name}
          onPick={(t) => {
            if (!blacklist.includes(t.id)) put({ item_blacklist: [...blacklist, t.id] })
            setQ('')
          }}
          placeholder="add item"
          testId="setup.rules.blacklist"
        />
      </div>
    </Panel>
  )
}
