import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './schema'

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

// Session-cookie auth: Django needs the CSRF token on every unsafe method.
const csrf: Middleware = {
  async onRequest({ request }) {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) {
      const token = readCookie('csrftoken')
      if (token) request.headers.set('X-CSRFToken', token)
    }
    return request
  },
}

export const api = createClient<paths>({ baseUrl: '', credentials: 'same-origin' })
api.use(csrf)

/** Logout is POST-only (a GET link could be triggered by any page); the server then redirects home. */
export async function logout() {
  const token = readCookie('csrftoken')
  await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin', headers: token ? { 'X-CSRFToken': token } : {} })
  window.location.assign('/')
}

/** The server's message: a string from our HttpErrors, or django-ninja's list of field errors on a 422. */
function messageOf(status: number, detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => {
        const item = d as { loc?: unknown[]; msg?: string }
        const where = (item.loc ?? []).filter((p) => p !== 'body' && p !== 'payload' && p !== 'query' && p !== 'path').join('.')
        return where ? `${where}: ${item.msg ?? 'invalid'}` : (item.msg ?? 'invalid')
      })
      .join('; ')
  }
  return `API error ${status}`
}

export class ApiError extends Error {
  status: number
  constructor(status: number, detail: unknown) {
    super(messageOf(status, detail))
    this.status = status
  }
}

/** Unwrap an openapi-fetch result, throwing ApiError on non-2xx. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok) {
    const detail =
      result.error && typeof result.error === 'object' && 'detail' in result.error
        ? (result.error as { detail: unknown }).detail
        : result.error
    throw new ApiError(result.response.status, detail)
  }
  return result.data as T
}

export type Schemas = components['schemas']
export type MeOut = Schemas['MeOut']
export type CharacterOut = Schemas['CharacterOut']
export type StationOut = Schemas['StationOut']
export type StationIn = Schemas['StationIn']
export type StationPatch = Schemas['StationPatch']
export type BuildRulesIO = Schemas['BuildRulesIO']
export type PlanSummary = Schemas['PlanSummary']
export type PlanOut = Schemas['PlanOut']
export type PlanCreate = Schemas['PlanCreate']
export type PlanSettings = Schemas['PlanSettings']
export type ChoiceIO = Schemas['ChoiceIO']
export type SharedPlanOut = Schemas['SharedPlanOut']
export type SharedSummary = Schemas['SharedSummary']
export type CorporationOption = Schemas['CorporationOption']
export type CompressedOreOut = Schemas['CompressedOreOut']
export type OreClass = Schemas['OreClass']
export type BlueprintChoice = Schemas['BlueprintChoice']
export type BlueprintOptions = Schemas['BlueprintOptions']
export type PurchaseOption = Schemas['PurchaseOption']
export type LineIO = Schemas['LineIO']
export type PlanResultOut = Schemas['PlanResultOut']
export type MoveOut = Schemas['MoveOut']
export type PlanResult = Schemas['PlanResult']
export type PlannedJob = Schemas['PlannedJob']
export type ItemPlan = Schemas['ItemPlan']
export type BlueprintPlan = Schemas['BlueprintPlan']
export type ShoppingItem = Schemas['ShoppingItem']
export type Reason = Schemas['Reason']
export type Activity = Schemas['Activity']
export type BuildCategory = Schemas['BuildCategory']
export type TypeOut = Schemas['TypeOut']
export type SystemOut = Schemas['SystemOut']
export type FeedOut = Schemas['FeedOut']
export type DiscoverOut = Schemas['DiscoverOut']
export type BlueprintRow = Schemas['BlueprintRow']
export type DashboardOut = Schemas['DashboardOut']
export type JobRow = Schemas['JobRow']
export type ProgressOut = Schemas['ProgressOut']
export type ProgressRow = Schemas['ProgressRow']
export type LinkedJob = Schemas['LinkedJob']
