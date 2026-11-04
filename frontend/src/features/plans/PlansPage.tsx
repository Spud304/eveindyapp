import { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { usePageTitle } from '@/hooks/usePageTitle'
import { usePlanMutations, usePlans } from '@/lib/api/hooks'
import { since } from '@/lib/format'
import { Badge, Button, Empty, ErrorText, Input, Mono, PageHeader, Panel, Table } from '@/components/ui'

export function PlansPage() {
  usePageTitle('Plans')
  const plans = usePlans()
  const { create } = usePlanMutations()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const rows = plans.data ?? []
  const add = () =>
    create.mutate(
      { name: name.trim(), lines: [], reserve_assets: false, priority: 100 },
      { onSuccess: (p) => void navigate({ to: '/plans/$planId', params: { planId: String(p.id) } }) },
    )
  return (
    <>
      <PageHeader
        title="Plans"
        count={rows.length}
        context="what to build, and where each batch stands"
        actions={
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (name.trim()) add()
            }}
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="new plan name" testId="plans.new-name" />
            <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending} testId="plans.create">
              New plan
            </Button>
          </form>
        }
      />
      <ErrorText error={plans.error} />
      <Panel flush testId="plans.list">
        {rows.length === 0 && !plans.isLoading ? (
          <Empty hint="Name a batch (e.g. indy 1) and add what you want built.">No plans yet.</Empty>
        ) : (
          <Table hover>
            <thead>
              <tr>
                <th>Plan</th>
                <th>Status</th>
                <th className="text-right" title="reserving plans claim stock in this order, lowest first">
                  Priority
                </th>
                <th className="text-right">Lines</th>
                <th>Changed</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} data-testid={`plans.row.${p.id}`}>
                  <td>
                    <Link to="/plans/$planId" params={{ planId: String(p.id) }} className="font-medium text-accent hover:underline">
                      {p.name}
                    </Link>
                  </td>
                  <td className="flex gap-1">
                    {p.is_active ? (
                      <Badge tone="accent" title="new jobs are attributed to this plan">
                        active
                      </Badge>
                    ) : null}
                    {p.reserve_assets ? (
                      <Badge tone="info" title="claims hangar stock before other plans">
                        reserves
                      </Badge>
                    ) : null}
                  </td>
                  <td className="text-right">
                    <Mono>{p.priority}</Mono>
                  </td>
                  <td className="text-right">
                    <Mono>{p.line_count}</Mono>
                  </td>
                  <td className="text-muted">{since(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>
    </>
  )
}
