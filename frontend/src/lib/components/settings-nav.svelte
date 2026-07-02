<script lang="ts">
import { page } from '$app/state';

const SECTIONS = [
	{ href: '/settings/instances', label: 'Instances' },
	{ href: '/settings/policy', label: 'Policy' }
];
</script>

<nav class="flex items-center gap-1 border-b pb-2">
	{#each SECTIONS as section (section.href)}
		<a
			href={section.href}
			class="rounded-md px-3 py-1.5 text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
			class:bg-accent={page.url.pathname.startsWith(section.href)}
			aria-current={page.url.pathname.startsWith(section.href) ? 'page' : undefined}
		>
			{section.label}
		</a>
	{/each}
</nav>
