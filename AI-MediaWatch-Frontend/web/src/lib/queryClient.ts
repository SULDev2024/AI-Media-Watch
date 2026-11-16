import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

// Query key factories — keeps keys consistent across pages
export const qk = {
  videos: (limit?: number) => ['videos', limit ?? 100] as const,
  video: (id: string) => ['video', id] as const,
  report: (id: string) => ['report', id] as const,
  graph: () => ['graph'] as const,
  campaigns: () => ['campaigns'] as const,
  metrics: () => ['metrics', 'precision-recall'] as const,
  usage: () => ['usage', 'today'] as const,
  validation: () => ['validation', 'summary'] as const,
  collector: () => ['collector', 'status'] as const,
}
