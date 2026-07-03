<script lang="ts">
import 'virtual:uno.css';
import '../app.css';
import '@fontsource-variable/inter/index.css';
import '@fontsource-variable/jetbrains-mono/index.css';
import { ModeWatcher } from 'mode-watcher';
import { goto } from '$app/navigation';
import { page } from '$app/state';
import { getTelemetryHealth } from '$lib/api/endpoints';
import Logo from '$lib/components/logo.svelte';
import ThemeToggle from '$lib/components/theme-toggle.svelte';
import { session } from '$lib/state/session.svelte';
import { sse } from '$lib/state/sse.svelte';
import { createTelemetryState } from '$lib/state/telemetry.svelte';

let { children } = $props();

const PUBLIC_ROUTES = new Set(['/login', '/setup']);

const NAV_ITEMS = [
	{ href: '/', label: 'Dashboard' },
	{ href: '/plan', label: 'Plan' },
	{ href: '/queue', label: 'Queue' },
	{ href: '/library', label: 'Library' },
	{ href: '/history', label: 'History' },
	{ href: '/stats', label: 'Stats' },
	{ href: '/doctor', label: 'Doctor' },
	{ href: '/settings/instances', label: 'Settings' }
];

// Telemetry degradation indicator (P3-T4/T7, NFR-7): live websockets vs the
// polling fallback, refreshed on stream-health SSE.
const telemetry = createTelemetryState(() => getTelemetryHealth());

$effect(() => {
	if (session.user === null) {
		return;
	}
	void telemetry.load();
	const unsubscribe = sse.subscribe('telemetry.health', () => void telemetry.load());
	sse.connect();
	return unsubscribe;
});

// Theme mode: follow the system preference; when the platform reports none,
// fall back to dark (project directive). matchMedia('(prefers-color-scheme)')
// matches nothing on such platforms, so ModeWatcher's system tracking would
// otherwise silently resolve light.
const systemPreferenceAvailable =
	typeof window !== 'undefined' &&
	window.matchMedia('(prefers-color-scheme: dark)').media !== 'not all';

// Highlight by top-level section so nested routes (/library/series/…,
// /settings/…) keep their nav item active.
function isActive(href: string, pathname: string): boolean {
	if (href === '/') {
		return pathname === '/';
	}
	const section = `/${href.split('/')[1]}`;
	return pathname === section || pathname.startsWith(`${section}/`);
}

// Pure SPA (ssr = false): one initialize per app mount.
void session.initialize();

$effect(() => {
	if (!session.initialized || session.loading) {
		return;
	}
	const path = page.url.pathname;
	if (session.setupRequired) {
		if (path !== '/setup') {
			void goto('/setup');
		}
		return;
	}
	if (session.user === null && !PUBLIC_ROUTES.has(path)) {
		void goto('/login');
		return;
	}
	if (session.user !== null && PUBLIC_ROUTES.has(path)) {
		void goto('/');
	}
});

async function signOut() {
	await session.logout();
	void goto('/login');
}
</script>

<svelte:head>
	<link rel="icon" href="/perevoditarr-logo.svg" />
	<title>Perevoditarr</title>
</svelte:head>

<ModeWatcher defaultMode={systemPreferenceAvailable ? 'system' : 'dark'} />
{#if !session.initialized}
	<div class="flex min-h-screen items-center justify-center bg-background text-foreground">
		<div
			class="size-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent"
			role="status"
			aria-label="Loading"
		></div>
	</div>
{:else if session.user !== null && !session.setupRequired}
	<div class="min-h-screen bg-background text-foreground">
		<header class="flex items-center justify-between border-b px-6 py-3">
			<div class="flex items-center gap-6">
				<a
					href="/"
					class="flex items-center rounded-sm outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
				>
					<Logo size={24} />
				</a>
				<nav class="flex items-center gap-1">
					{#each NAV_ITEMS as item (item.href)}
						<a
							href={item.href}
							class="rounded-md px-3 py-1.5 text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
							class:bg-accent={isActive(item.href, page.url.pathname)}
							aria-current={isActive(item.href, page.url.pathname) ? 'page' : undefined}
						>
							{item.label}
						</a>
					{/each}
				</nav>
			</div>
			<div class="flex items-center gap-2">
				{#if telemetry.degraded}
					<span
						class="rounded-full border border-amber-500/40 px-2 py-0.5 text-xs text-amber-600 dark:text-amber-400"
						title="Live telemetry is on the polling fallback (websockets unavailable). Progress still updates, just less instantly."
					>
						polling
					</span>
				{:else if telemetry.live}
					<span
						class="rounded-full border border-emerald-500/40 px-2 py-0.5 text-xs text-emerald-600 dark:text-emerald-400"
						title="Live telemetry connected over websockets."
					>
						live
					</span>
				{/if}
				<span class="text-sm text-muted-foreground">{session.user.username}</span>
				<button
					type="button"
					class="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
					onclick={() => void signOut()}
				>
					Sign out
				</button>
				<ThemeToggle />
			</div>
		</header>
		<main class="p-6">
			{@render children()}
		</main>
	</div>
{:else}
	<div class="min-h-screen bg-background text-foreground">
		{@render children()}
	</div>
{/if}
