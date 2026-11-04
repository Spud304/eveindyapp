import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import './index.css'
import { router } from './router'
import { Toasts, notify } from './components/toast'
import { applyTheme, readTheme } from './lib/theme'

applyTheme(readTheme())

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
  mutationCache: new MutationCache({
    // Mutations that set `meta.toast` confirm themselves in one line; failures always say why.
    onSuccess: (_data, _vars, _ctx, mutation) => {
      if (mutation.meta?.toast) notify(mutation.meta.toast)
    },
    onError: (error) => notify(error instanceof Error ? error.message : String(error), 'bad'),
  }),
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toasts />
    </QueryClientProvider>
  </StrictMode>,
)
