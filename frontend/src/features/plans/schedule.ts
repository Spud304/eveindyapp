import type { PlannedJob } from '@/lib/api/client'

const DAY = 86400

/** When a job starts, from plan start: now (a slot and its inputs are free), within a day, or later. */
export type Bucket = 'now' | 'soon' | 'later'

export function bucketOf(startSeconds: number): Bucket {
  if (startSeconds <= 0) return 'now'
  return startSeconds <= DAY ? 'soon' : 'later'
}

/** One table row: identical jobs (same blueprint, activity, runs, station and times) shown once. */
export type JobRow = { key: string; job: PlannedJob; count: number }

/** A character's jobs (null: jobs no character may run), split by when they start. */
export type CharacterGroup = { characterId: number | null; name: string } & Record<Bucket, JobRow[]>

export function groupSchedule(jobs: PlannedJob[], characterName: (id: number) => string, productName: (blueprintTypeId: number) => string): CharacterGroup[] {
  const sorted = [...jobs].sort(
    (a, b) =>
      a.schedule.start_seconds - b.schedule.start_seconds ||
      a.activity.localeCompare(b.activity) ||
      productName(a.blueprint_type_id).localeCompare(productName(b.blueprint_type_id)) ||
      b.runs - a.runs ||
      a.job_id.localeCompare(b.job_id),
  )
  const groups = new Map<number | null, CharacterGroup>()
  const rows = new Map<string, JobRow>()
  for (const j of sorted) {
    const id = j.schedule.character_id ?? null
    let group = groups.get(id)
    if (!group) {
      group = { characterId: id, name: id == null ? 'nobody' : characterName(id), now: [], soon: [], later: [] }
      groups.set(id, group)
    }
    const s = j.schedule
    const key = [id, j.activity, j.blueprint_type_id, j.runs, j.copies, j.station_id, s.start_seconds, s.end_seconds].join('|')
    const row = rows.get(key)
    if (row) {
      row.count += 1
      continue
    }
    const fresh = { key, job: j, count: 1 }
    rows.set(key, fresh)
    group[bucketOf(s.start_seconds)].push(fresh)
  }
  return [...groups.values()].sort((a, b) => Number(b.characterId == null) - Number(a.characterId == null) || a.name.localeCompare(b.name))
}
