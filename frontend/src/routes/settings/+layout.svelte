<script lang="ts">
import { page } from '$app/state';

let { children } = $props();

const SETTINGS_NAV = [
	{ href: '/settings/instances', label: 'Instances' },
	{ href: '/settings/policy', label: 'Policy' },
	{ href: '/settings/notifications', label: 'Notifications' }
];
</script>

<div class="space-y-5">
	<nav class="flex flex-wrap gap-1 border-b pb-2">
		{#each SETTINGS_NAV as item (item.href)}
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
