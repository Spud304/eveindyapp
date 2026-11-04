import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  unwrap,
  type BuildRulesIO,
  type LineIO,
  type PlanCreate,
  type PlanSettings,
  type ProgressOut,
  type StationIn,
  type StationOut,
  type StationPatch,
} from './client'

export const keys = {
  me: ['me'] as const,
  stations: ['stations'] as const,
  rules: ['build-rules'] as const,
  syncStatus: ['sync', 'status'] as const,
  plans: ['plans'] as const,
  plan: (id: number) => ['plans', id] as const,
  planResult: (id: number) => ['plans', id, 'result'] as const,
  planProgress: (id: number) => ['plans', id, 'progress'] as const,
  typeSearch: (q: string, kind: string) => ['types', 'search', kind, q] as const,
  systemSearch: (q: string) => ['systems', 'search', q] as const,
  typeNames: (ids: number[]) => ['types', 'names', ids] as const,
  library: ['library'] as const,
  dashboard: ['dashboard'] as const,
}

// --- account -----------------------------------------------------------------------------

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: async () => unwrap(await api.GET('/api/me')), staleTime: 60_000 })
}

export function useCharacterMutations() {
  const qc = useQueryClient()
  const done = () => qc.invalidateQueries({ queryKey: keys.me })
  return {
    setMain: useMutation({
      mutationFn: async (id: number) => unwrap(await api.POST('/api/characters/{character_id}/main', { params: { path: { character_id: id } } })),
      onSuccess: done,
      meta: { toast: 'Main character set' },
    }),
    unlink: useMutation({
      mutationFn: async (id: number) => unwrap(await api.DELETE('/api/characters/{character_id}', { params: { path: { character_id: id } } })),
      onSuccess: done,
      meta: { toast: 'Character removed' },
    }),
  }
}

// --- sync --------------------------------------------------------------------------------

/** Polls every 5 s while a sync is queued or running, so the table fills in as feeds land. */
export function useSyncStatus() {
  return useQuery({
    queryKey: keys.syncStatus,
    queryFn: async () => unwrap(await api.GET('/api/sync/status')),
    refetchInterval: (q) => (q.state.data?.queued ? 5_000 : false),
  })
}

export function useRefreshNow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => unwrap(await api.POST('/api/sync')),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.syncStatus }),
    meta: { toast: 'Sync queued' },
  })
}

// --- stations and rules ------------------------------------------------------------------

export function useStations() {
  return useQuery({ queryKey: keys.stations, queryFn: async () => unwrap(await api.GET('/api/stations')) })
}

export function useStationMutations() {
  const qc = useQueryClient()
  const done = () => {
    void qc.invalidateQueries({ queryKey: keys.stations })
    void qc.invalidateQueries({ queryKey: keys.plans })
  }
  return {
    discover: useMutation({
      mutationFn: async () => unwrap(await api.POST('/api/stations/discover')),
      onSuccess: done,
    }),
    add: useMutation({
      mutationFn: async (body: StationIn) => unwrap(await api.POST('/api/stations', { body })),
      onSuccess: done,
      meta: { toast: 'Station added' },
    }),
    edit: useMutation({
      mutationFn: async ({ id, body }: { id: number; body: StationPatch }) =>
        unwrap(await api.PATCH('/api/stations/{station_id}', { params: { path: { station_id: id } }, body })),
      // Optimistic: checkboxes and inputs reflect the change at once, and roll back if refused.
      // The cache is written before the first await, so the input changes within the same event.
      onMutate: async ({ id, body }) => {
        const before = qc.getQueryData<StationOut[]>(keys.stations)
        if (before) {
          // Rig changes wait for the server, which supplies the rig names.
          const patch = Object.fromEntries(Object.entries(body).filter(([k, v]) => v != null && k !== 'rig_type_ids'))
          qc.setQueryData<StationOut[]>(keys.stations, before.map((s) => (s.id === id ? { ...s, ...patch } : s)))
        }
        await qc.cancelQueries({ queryKey: keys.stations }) // an older refetch must not overwrite it
        return { before }
      },
      onError: (_err, _vars, ctx) => {
        if (ctx?.before) qc.setQueryData(keys.stations, ctx.before)
      },
      onSettled: done,
      meta: { toast: 'Station saved' },
    }),
    remove: useMutation({
      mutationFn: async (id: number) => unwrap(await api.DELETE('/api/stations/{station_id}', { params: { path: { station_id: id } } })),
      onSuccess: done,
      meta: { toast: 'Station removed' },
    }),
  }
}

export function useBuildRules() {
  return useQuery({ queryKey: keys.rules, queryFn: async () => unwrap(await api.GET('/api/build-rules')) })
}

export function useSaveBuildRules() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: BuildRulesIO) => unwrap(await api.PUT('/api/build-rules', { body })),
    // Optimistic, so a ticked box stays ticked while the save is in flight.
    onMutate: async (body) => {
      const before = qc.getQueryData<BuildRulesIO>(keys.rules)
      qc.setQueryData(keys.rules, body) // before the first await: the box changes within the click
      await qc.cancelQueries({ queryKey: keys.rules })
      return { before }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.before) qc.setQueryData(keys.rules, ctx.before)
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: keys.rules })
      void qc.invalidateQueries({ queryKey: keys.plans })
    },
    meta: { toast: 'Build rules saved' },
  })
}

// --- plans -------------------------------------------------------------------------------

export function usePlans() {
  return useQuery({ queryKey: keys.plans, queryFn: async () => unwrap(await api.GET('/api/plans')) })
}

export function usePlan(id: number) {
  return useQuery({
    queryKey: keys.plan(id),
    queryFn: async () => unwrap(await api.GET('/api/plans/{plan_id}', { params: { path: { plan_id: id } } })),
  })
}

/** Buy-BPC / extra-BPO options for one blueprint: one plan run per candidate, so on request
 * only. Under the plans key, so any plan change refreshes them. */
export function useBlueprintOptions(planId: number, bpId: number, enabled: boolean) {
  return useQuery({
    queryKey: [...keys.plans, planId, 'options', bpId],
    queryFn: async () =>
      unwrap(await api.GET('/api/plans/{plan_id}/blueprints/{bp_id}/options', { params: { path: { plan_id: planId, bp_id: bpId } } })),
    enabled,
    staleTime: 30_000,
  })
}

/** The engine's result. Recomputed on the server each time; kept while a new one loads. */
export function usePlanResult(id: number) {
  return useQuery({
    queryKey: keys.planResult(id),
    queryFn: async () => unwrap(await api.GET('/api/plans/{plan_id}/result', { params: { path: { plan_id: id } } })),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function usePlanMutations() {
  const qc = useQueryClient()
  // Any plan change can change every plan's result (reservations), so refresh them all.
  const done = () => qc.invalidateQueries({ queryKey: keys.plans })
  const path = (id: number) => ({ params: { path: { plan_id: id } } })
  return {
    create: useMutation({
      mutationFn: async (body: PlanCreate) => unwrap(await api.POST('/api/plans', { body })),
      onSuccess: done,
      meta: { toast: 'Plan created' },
    }),
    edit: useMutation({
      mutationFn: async ({ id, body }: { id: number; body: PlanSettings }) =>
        unwrap(await api.PATCH('/api/plans/{plan_id}', { ...path(id), body })),
      onSuccess: done,
      meta: { toast: 'Plan saved' },
    }),
    setLines: useMutation({
      mutationFn: async ({ id, lines }: { id: number; lines: LineIO[] }) =>
        unwrap(await api.PUT('/api/plans/{plan_id}/lines', { ...path(id), body: lines })),
      onSuccess: () => {
        void done()
        void qc.invalidateQueries({ queryKey: keys.library }) // picked BPCs show their plan
      },
      meta: { toast: 'Lines saved' },
    }),
    activate: useMutation({
      mutationFn: async (id: number) => unwrap(await api.POST('/api/plans/{plan_id}/activate', path(id))),
      onSuccess: done,
      meta: { toast: 'Plan is now active' },
    }),
    deactivate: useMutation({
      mutationFn: async (id: number) => unwrap(await api.POST('/api/plans/{plan_id}/deactivate', path(id))),
      onSuccess: done,
      meta: { toast: 'Plan deactivated' },
    }),
    remove: useMutation({
      mutationFn: async (id: number) => unwrap(await api.DELETE('/api/plans/{plan_id}', path(id))),
      onSuccess: done,
      meta: { toast: 'Plan deleted' },
    }),
  }
}

// --- lookups -----------------------------------------------------------------------------

export function useTypeSearch(q: string, kind: 'buildable' | 'structure' | 'rig' | 'any') {
  return useQuery({
    queryKey: keys.typeSearch(q, kind),
    queryFn: async () => unwrap(await api.GET('/api/types/search', { params: { query: { q, kind, limit: 15 } } })),
    enabled: q.trim().length >= 2,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  })
}

export function useSystemSearch(q: string) {
  return useQuery({
    queryKey: keys.systemSearch(q),
    queryFn: async () => unwrap(await api.GET('/api/systems/search', { params: { query: { q, limit: 15 } } })),
    enabled: q.trim().length >= 2,
    staleTime: 5 * 60_000,
  })
}

/** Names for type ids the page already holds (e.g. a blacklist). */
export function useTypeNames(ids: number[]) {
  const sorted = [...new Set(ids)].sort((a, b) => a - b)
  return useQuery({
    queryKey: keys.typeNames(sorted),
    queryFn: async () => {
      const rows = unwrap(await api.GET('/api/types', { params: { query: { ids: sorted.join(',') } } }))
      return new Map(rows.map((t) => [t.id, t.name]))
    },
    enabled: sorted.length > 0,
    staleTime: 10 * 60_000,
  })
}

// --- overview ----------------------------------------------------------------------------

export function useLibrary() {
  return useQuery({ queryKey: keys.library, queryFn: async () => unwrap(await api.GET('/api/library/blueprints')), staleTime: 60_000 })
}

/** Refreshes every minute so "ready" and "finishing soon" follow the clock. */
export function useDashboard() {
  return useQuery({ queryKey: keys.dashboard, queryFn: async () => unwrap(await api.GET('/api/dashboard')), refetchInterval: 60_000 })
}

// --- progress ----------------------------------------------------------------------------

/** Jobs linked to a plan; the server matches new jobs first. Refreshes every minute. */
export function usePlanProgress(id: number, enabled = true) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: keys.planProgress(id),
    queryFn: async () => {
      const before = qc.getQueryData<ProgressOut>(keys.planProgress(id))
      const data = unwrap(await api.GET('/api/plans/{plan_id}/progress', { params: { path: { plan_id: id } } }))
      // The server matches new jobs on this call; when the links change, every plan result
      // (this plan's progress, the others' reservations) is out of date.
      const ids = (p: ProgressOut | undefined) => (p?.jobs ?? []).map((j) => `${j.job_id}:${j.status}`).join(',')
      if (ids(before) !== ids(data)) void qc.invalidateQueries({ queryKey: keys.plans, predicate: (q) => q.queryKey[2] === 'result' || q.queryKey.length === 1 })
      return data
    },
    enabled,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  })
}

export function useJobLinkMutations(planId: number) {
  const qc = useQueryClient()
  const path = (jobId: number) => ({ params: { path: { plan_id: planId, job_id: jobId } } })
  const done = (data: unknown) => {
    qc.setQueryData(keys.planProgress(planId), data)
    void qc.invalidateQueries({ queryKey: keys.plans }) // links change every plan's result
  }
  return {
    link: useMutation({
      mutationFn: async (jobId: number) => unwrap(await api.POST('/api/plans/{plan_id}/jobs/{job_id}', path(jobId))),
      onSuccess: done,
      meta: { toast: 'Job linked to this plan' },
    }),
    unlink: useMutation({
      mutationFn: async (jobId: number) => unwrap(await api.DELETE('/api/plans/{plan_id}/jobs/{job_id}', path(jobId))),
      onSuccess: done,
      meta: { toast: 'Job unlinked' },
    }),
  }
}
