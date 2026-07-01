<script lang="ts">
import 'virtual:uno.css';
import '../app.css';
import { ModeWatcher } from 'mode-watcher';
import favicon from '$lib/assets/favicon.svg';
import ThemeToggle from '$lib/components/theme-toggle.svelte';

let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Perevoditarr</title>
</svelte:head>

<ModeWatcher />
<div class="min-h-screen bg-background text-foreground">
	<header class="flex items-center justify-between border-b px-6 py-3">
		<span class="text-lg font-semibold">Perevoditarr</span>
		<ThemeToggle />
	</header>
	<main class="p-6">
		{@render children()}
	</main>
</div>
