import { describe, expect, it } from 'vitest'
import type { PlannedJob } from '@/lib/api/client'
import { bucketOf, groupSchedule } from './schedule'

let nextId = 0

function job(character: number | null, blueprint: number, start: number, end: number, extra: Partial<PlannedJob> = {}): PlannedJob {
  nextId += 1
  return {
    job_id: `job${String(nextId).padStart(3, '0')}`,
    activity: 'manufacturing',
    blueprint_type_id: blueprint,
    runs: 10,
    copies: 0,
    station_id: 1,
    schedule: { character_id: character, start_seconds: start, end_seconds: end, reason: { code: 'scheduled', text: '' } },
    ...extra,
  } as PlannedJob
}

const characters: Record<number, string> = { 1: 'Starch Man', 2: 'Industrial Fryer' }
const products: Record<number, string> = { 10: 'Capital Siege Array Blueprint', 11: 'Capital Armor Plates Blueprint' }
const group = (jobs: PlannedJob[]) =>
  groupSchedule(
    jobs,
    (id) => characters[id],
    (bp) => products[bp],
  )

describe('bucketOf', () => {
  it('splits now, within a day and later', () => {
    expect(bucketOf(0)).toBe('now')
    expect(bucketOf(1)).toBe('soon')
    expect(bucketOf(86400)).toBe('soon')
    expect(bucketOf(86401)).toBe('later')
  })
})

describe('groupSchedule', () => {
  it('puts jobs no character may run first, then characters by name', () => {
    const groups = group([job(1, 10, 0, 100), job(null, 10, 0, 100), job(2, 10, 0, 100)])
    expect(groups.map((g) => g.name)).toEqual(['nobody', 'Industrial Fryer', 'Starch Man'])
  })

  it('orders a character’s jobs by start, then activity and product name', () => {
    const [g] = group([job(1, 10, 500, 900), job(1, 10, 0, 100), job(1, 11, 0, 100), job(1, 10, 0, 50, { activity: 'copying' })])
    expect(g.now.map((r) => [r.job.activity, r.job.blueprint_type_id])).toEqual([
      ['copying', 10],
      ['manufacturing', 11],
      ['manufacturing', 10],
    ])
    expect(g.soon.map((r) => r.job.schedule.start_seconds)).toEqual([500])
  })

  it('collapses identical jobs and keeps different ones apart', () => {
    const [g] = group([
      job(1, 10, 0, 100),
      job(1, 10, 0, 100),
      job(1, 10, 0, 100),
      job(1, 10, 0, 300, { runs: 30 }), // other runs
      job(1, 10, 100, 200), // other start: a blueprint used in turn
    ])
    expect(g.now.map((r) => [r.job.runs, r.count])).toEqual([
      [30, 1],
      [10, 3],
    ])
    expect(g.soon.map((r) => r.count)).toEqual([1])
  })

  it('does not collapse the same job across characters', () => {
    const groups = group([job(1, 10, 0, 100), job(2, 10, 0, 100)])
    expect(groups.map((g) => g.now[0].count)).toEqual([1, 1])
  })

  it('files jobs a day or more out under later', () => {
    const [g] = group([job(1, 10, 2 * 86400, 3 * 86400)])
    expect([g.now.length, g.soon.length, g.later.length]).toEqual([0, 0, 1])
  })
})
