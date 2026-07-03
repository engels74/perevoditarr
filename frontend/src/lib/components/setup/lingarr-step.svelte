<script lang="ts">
import {
	confirmLingarrDiscovery,
	createLingarrInstance,
	getLingarrDiscovery,
	listBazarrInstances,
	listLingarrInstances,
	testConnection
} from '$lib/api/endpoints';
import type {
	BazarrInstanceRead,
	ConnectionTestResult,
	LingarrDiscoveryResult,
	LingarrInstanceRead
} from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import { Input } from '$lib/components/ui/input';
import { Label } from '$lib/components/ui/label';
import { session } from '$lib/state/session.svelte';

let { onBack, onNext, onSkip }: { onBack: () => void; onNext: () => void; onSkip: () => void } =
	$props();

let mode = $state<'discover' | 'manual'>('discover');
let bazarrInstances = $state<BazarrInstanceRead[]>([]);
let lingarrInstances = $state<LingarrInstanceRead[]>([]);
let localError = $state<string | null>(null);

// Discovery
let discoveryFor = $state<string | null>(null);
let discovery = $state<LingarrDiscoveryResult | null>(null);
let discoveryName = $state('');
let discoveryBusy = $state(false);

// Manual
let name = $state('');
let url = $state('');
let apiKey = $state('');
let testResult = $state<ConnectionTestResult | null>(null);
let testBusy = $state(false);
let saveBusy = $state(false);

function message(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

async function loadInstances(): Promise<void> {
	try {
		[bazarrInstances, lingarrInstances] = await Promise.all([
			listBazarrInstances(),
			listLingarrInstances()
		]);
	} catch (cause) {
		localError = message(cause);
	}
}

$effect(() => {
	void loadInstances();
});

async function openDiscovery(bazarrId: string): Promise<void> {
	discoveryFor = bazarrId;
	discovery = null;
	discoveryName = '';
	localError = null;
	discoveryBusy = true;
	try {
		discovery = await getLingarrDiscovery(bazarrId);
	} catch (cause) {
		localError = message(cause);
	} finally {
		discoveryBusy = false;
	}
}

async function confirmDiscovery(): Promise<void> {
	if (discoveryFor === null) {
		return;
	}
	discoveryBusy = true;
	localError = null;
	try {
		await confirmLingarrDiscovery(discoveryFor, discoveryName);
		discoveryFor = null;
		await loadInstances();
		await session.refreshSetup();
	} catch (cause) {
		localError = message(cause);
	} finally {
		discoveryBusy = false;
	}
}

async function runTest(): Promise<void> {
	testBusy = true;
	localError = null;
	testResult = null;
	try {
		testResult = await testConnection({ kind: 'lingarr', url, apiKey: apiKey || null });
	} catch (cause) {
		localError = message(cause);
	} finally {
		testBusy = false;
	}
}

async function addManual(): Promise<void> {
	saveBusy = true;
	localError = null;
	try {
		await createLingarrInstance({ name, url, apiKey: apiKey || null, enabled: true });
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
		Optionally connect Lingarr for automatic translation dispatch. You can skip this and add it
		later from Settings.
	</p>

	<div class="flex gap-2">
		<Button
			size="sm"
			variant={mode === 'discover' ? 'default' : 'outline'}
			onclick={() => (mode = 'discover')}
		>
			Auto-discover
		</Button>
		<Button
			size="sm"
			variant={mode === 'manual' ? 'default' : 'outline'}
			onclick={() => (mode = 'manual')}
		>
			Manual
		</Button>
	</div>

	{#if localError}
		<p class="text-sm text-destructive">{localError}</p>
	{/if}

	{#if mode === 'discover'}
		<div class="space-y-2">
			{#each bazarrInstances as instance (instance.id)}
				<div class="rounded-md border p-3 text-sm">
					<div class="flex items-center justify-between">
						<span class="font-medium">{instance.name}</span>
						{#if instance.lingarrInstanceId !== null}
							<Badge variant="outline">linked</Badge>
						{:else}
							<Button
								size="sm"
								variant="outline"
								disabled={discoveryBusy}
								onclick={() => void openDiscovery(instance.id)}
							>
								Discover Lingarr
							</Button>
						{/if}
					</div>
					{#if discoveryFor === instance.id}
						{#if discoveryBusy && discovery === null}
							<p class="mt-2 text-muted-foreground">Looking for a Lingarr provider…</p>
						{:else if discovery !== null && !discovery.configured}
							<p class="mt-2 text-muted-foreground">
								No Lingarr provider is configured in this Bazarr instance.
							</p>
						{:else if discovery !== null}
							<div class="mt-2 space-y-2">
								<p>
									Found Lingarr at <span class="font-mono">{discovery.url ?? '?'}</span>
									{discovery.hasApiKey ? '(with API key)' : '(no API key)'}
								</p>
								<div class="flex flex-wrap items-center gap-2">
									<Input class="max-w-48" placeholder="Instance name" bind:value={discoveryName} />
									<Button
										size="sm"
										disabled={discoveryBusy || discoveryName.trim() === ''}
										onclick={() => void confirmDiscovery()}
									>
										Confirm &amp; link
									</Button>
									<Button variant="ghost" size="sm" onclick={() => (discoveryFor = null)}>
										Cancel
									</Button>
								</div>
							</div>
						{/if}
					{/if}
				</div>
			{:else}
				<p class="text-sm text-muted-foreground">Add a Bazarr instance first to discover Lingarr.</p>
			{/each}
		</div>
	{:else}
		<form
			class="space-y-3"
			onsubmit={(event) => {
				event.preventDefault();
				void addManual();
			}}
		>
			<div class="grid gap-3 sm:grid-cols-2">
				<div class="space-y-1">
					<Label for="lingarr-name">Name</Label>
					<Input id="lingarr-name" bind:value={name} placeholder="Main Lingarr" required />
				</div>
				<div class="space-y-1">
					<Label for="lingarr-url">URL</Label>
					<Input id="lingarr-url" bind:value={url} placeholder="http://lingarr:9876" required />
				</div>
			</div>
			<div class="space-y-1">
				<Label for="lingarr-apikey">API key (optional)</Label>
				<Input id="lingarr-apikey" bind:value={apiKey} placeholder="API key" />
			</div>
			{#if testResult}
				<p class="text-sm {testResult.reachable ? 'text-muted-foreground' : 'text-destructive'}">
					{#if testResult.reachable}
						Reachable — v{testResult.version ?? '?'}
					{:else}
						Unreachable{testResult.error ? `: ${testResult.error}` : ''}
					{/if}
				</p>
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
				<Button type="submit" disabled={saveBusy || !name || !url}>
					{saveBusy ? 'Adding…' : 'Add'}
				</Button>
			</div>
		</form>
	{/if}

	<div class="space-y-2">
		<h3 class="text-sm font-medium">Connected Lingarr instances</h3>
		{#each lingarrInstances as instance (instance.id)}
			<div class="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
				<span class="font-medium">{instance.name}</span>
				<span class="font-mono text-xs text-muted-foreground">{instance.url}</span>
			</div>
		{:else}
			<p class="text-sm text-muted-foreground">No Lingarr instances yet.</p>
		{/each}
	</div>

	<div class="flex items-center justify-between">
		<Button variant="ghost" onclick={onBack}>Back</Button>
		<div class="flex gap-2">
			<Button variant="outline" onclick={onSkip}>Skip</Button>
			<Button onclick={onNext}>Next</Button>
		</div>
	</div>
</div>
