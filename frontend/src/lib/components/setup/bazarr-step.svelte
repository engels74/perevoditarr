<script lang="ts">
import { createBazarrInstance, listBazarrInstances, testConnection } from '$lib/api/endpoints';
import type { BazarrInstanceRead, ConnectionTestResult } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import { Input } from '$lib/components/ui/input';
import { Label } from '$lib/components/ui/label';
import { session } from '$lib/state/session.svelte';

let { onBack, onNext }: { onBack: () => void; onNext: () => void } = $props();

let name = $state('');
let url = $state('');
let apiKey = $state('');
let instances = $state<BazarrInstanceRead[]>([]);
let testResult = $state<ConnectionTestResult | null>(null);
let localError = $state<string | null>(null);
let testBusy = $state(false);
let saveBusy = $state(false);

const canAdvance = $derived((session.setupChecklist?.bazarrCount ?? 0) >= 1);

function message(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

async function loadInstances(): Promise<void> {
	try {
		instances = await listBazarrInstances();
	} catch (cause) {
		localError = message(cause);
	}
}

$effect(() => {
	void loadInstances();
});

async function runTest(): Promise<void> {
	testBusy = true;
	localError = null;
	testResult = null;
	try {
		testResult = await testConnection({ kind: 'bazarr', url, apiKey: apiKey || null });
	} catch (cause) {
		localError = message(cause);
	} finally {
		testBusy = false;
	}
}

async function add(): Promise<void> {
	saveBusy = true;
	localError = null;
	try {
		await createBazarrInstance({ name, url, apiKey, enabled: true });
		name = '';
		url = '';
		apiKey = '';
		testResult = null;
		await loadInstances();
		await session.refreshSetup();
	} catch (cause) {
		localError = message(cause);
	} finally {
		saveBusy = false;
	}
}
</script>

<div class="space-y-4">
	<p class="text-sm text-muted-foreground">
		Connect at least one Bazarr instance. Perevoditarr mirrors your library from Bazarr to plan
		translations. This step is required.
	</p>

	<form
		class="space-y-3"
		onsubmit={(event) => {
			event.preventDefault();
			void add();
		}}
	>
		<div class="grid gap-3 sm:grid-cols-2">
			<div class="space-y-1">
				<Label for="bazarr-name">Name</Label>
				<Input id="bazarr-name" bind:value={name} placeholder="Main Bazarr" required />
			</div>
			<div class="space-y-1">
				<Label for="bazarr-url">URL</Label>
				<Input id="bazarr-url" bind:value={url} placeholder="http://bazarr:6767" required />
			</div>
		</div>
		<div class="space-y-1">
			<Label for="bazarr-apikey">API key</Label>
			<Input id="bazarr-apikey" bind:value={apiKey} placeholder="API key" required />
		</div>
		{#if testResult}
			<p class="text-sm {testResult.reachable ? 'text-muted-foreground' : 'text-destructive'}">
				{#if testResult.reachable}
					Reachable — v{testResult.version ?? '?'}{testResult.versionSupported === false
						? ' (unsupported version)'
						: ''}
				{:else}
					Unreachable{testResult.error ? `: ${testResult.error}` : ''}
				{/if}
			</p>
		{/if}
		{#if localError}
			<p class="text-sm text-destructive">{localError}</p>
		{/if}
		<div class="flex gap-2">
			<Button
				type="button"
				variant="outline"
				disabled={testBusy || url.trim() === ''}
				onclick={() => void runTest()}
			>
				{testBusy ? 'Testing…' : 'Test connection'}
			</Button>
			<Button type="submit" disabled={saveBusy || !name || !url || !apiKey}>
				{saveBusy ? 'Adding…' : 'Add'}
			</Button>
		</div>
	</form>

	<div class="space-y-2">
		<h3 class="text-sm font-medium">Connected instances</h3>
		{#each instances as instance (instance.id)}
			<div class="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
				<span class="font-medium">{instance.name}</span>
				<span class="flex items-center gap-2 text-muted-foreground">
					<span class="font-mono text-xs">{instance.url}</span>
					<Badge variant="outline">v{instance.version ?? '?'}</Badge>
				</span>
			</div>
		{:else}
			<p class="text-sm text-muted-foreground">No Bazarr instances yet.</p>
		{/each}
	</div>

	<div class="flex justify-between">
		<Button variant="ghost" onclick={onBack}>Back</Button>
		<Button disabled={!canAdvance} onclick={onNext}>Next</Button>
	</div>
</div>
