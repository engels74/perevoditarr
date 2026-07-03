<script lang="ts">
import { page } from '$app/state';
import { session } from '$lib/state/session.svelte';

let { children } = $props();

const BASE_NAV = [
	{ href: '/settings/instances', label: 'Instances' },
	{ href: '/settings/policy', label: 'Policy' },
	{ href: '/settings/notifications', label: 'Notifications' }
];
// Management surfaces are admin-only (FR-A6): the API enforces it; hiding the
// tabs for viewers is defense in depth.
const ADMIN_NAV = [
	{ href: '/settings/integrations', label: 'Integrations' },
	{ href: '/settings/access', label: 'Access' }
];

const nav = $derived(session.isAdmin ? [...BASE_NAV, ...ADMIN_NAV] : BASE_NAV);
</script>

<div class="space-y-5">
	<nav class="flex flex-wrap gap-1 border-b pb-2">
		{#each nav as item (item.href)}
			<a
				href={item.href}
				class="rounded-md px-3 py-1.5 text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
				class:bg-accent={page.url.pathname === item.href}
				aria-current={page.url.pathname === item.href ? 'page' : undefined}
			>
				{item.label}
			</a>
		{/each}
	</nav>
	{@render children()}
</div>
