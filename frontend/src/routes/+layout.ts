// Static SPA served same-origin by the backend (ADR-0004): no SSR, no prerender —
// every route is client-rendered against /api/v1 through the adapter-static fallback.
export const ssr = false;
export const prerender = false;
