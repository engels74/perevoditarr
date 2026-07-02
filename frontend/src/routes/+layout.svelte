<script lang="ts">
import 'virtual:uno.css';
import '../app.css';
import { ModeWatcher } from 'mode-watcher';
import { goto } from '$app/navigation';
import { page } from '$app/state';
import favicon from '$lib/assets/favicon.svg';
import ThemeToggle from '$lib/components/theme-toggle.svelte';
import { session } from '$lib/state/session.svelte';

let { children } = $props();

const PUBLIC_ROUTES = new Set(['/login', '/setup']);

const NAV_ITEMS = [
	{ href: '/', label: 'Dashboard' },
	{ href: '/library', label: 'Library' },
	{ href: '/doctor', label: 'Doctor' },
	{ href: '/settings/instances', label: 'Settings' }
];

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
	<link rel="icon" href={favicon} />
	<title>Perevoditarr</title>
</svelte:head>

<ModeWatcher />
{#if !session.initialized}
	<div class="flex min-h-screen items-center justify-center bg-background text-foreground">
		<div
			class="size-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent"
			role="status"
			aria-label="Loading"
		></div>
	</div>
{:else if session.user !== null}
	<div class="min-h-screen bg-background text-foreground">
		<header class="flex items-center justify-between border-b px-6 py-3">
			<div class="flex items-center gap-6">
				<span class="text-lg font-semibold">Perevoditarr</span>
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
