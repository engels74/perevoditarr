<script lang="ts">
import { getLingarrDiscovery, testConnection } from '$lib/api/endpoints';
import type { ConnectionTestResult, LingarrDiscoveryResult } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import * as Dialog from '$lib/components/ui/dialog';
import { Input } from '$lib/components/ui/input';
import { formatLatency, healthBadgeVariant } from '$lib/format';
import { instances } from '$lib/state/instances.svelte';

$effect(() => {
	void instances.load();
});

function message(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

// --- Add-instance dialog (shared between Bazarr and Lingarr) ---------------
let dialogOpen = $state(false);
let dialogKind = $state<'bazarr' | 'lingarr'>('bazarr');
let formName = $state('');
let formUrl = $state('');
let formApiKey = $state('');
let formError = $state<string | null>(null);
let testResult = $state<ConnectionTestResult | null>(null);
let testBusy = $state(false);
let saveBusy = $state(false);

function openDialog(kind: 'bazarr' | 'lingarr'): void {
	dialogKind = kind;
	formName = '';
	formUrl = '';
	formApiKey = '';
	formError = null;
	testResult = null;
	dialogOpen = true;
}

async function runTest(): Promise<void> {
	testBusy = true;
	formError = null;
	testResult = null;
	try {
		testResult = await testConnection({
			kind: dialogKind,
			url: formUrl,
			apiKey: formApiKey || null
		});
	} catch (cause) {
		formError = message(cause);
	} finally {
		testBusy = false;
	}
}

async function save(): Promise<void> {
	saveBusy = true;
	formError = null;
	try {
		if (dialogKind === 'bazarr') {
			await instances.addBazarr({
				name: formName,
				url: formUrl,
				apiKey: formApiKey,
				enabled: true
			});
		} else {
			await instances.addLingarr({
				name: formName,
				url: formUrl,
				apiKey: formApiKey || null,
				enabled: true
			});
		}
		dialogOpen = false;
	} catch (cause) {
		// Problem detail carries the readable reason (422 unsupported-version,
		// 502 unreachable, 409 duplicate name).
		formError = message(cause);
	} finally {
		saveBusy = false;
	}
}

// --- Per-row actions ---------------------------------------------------------
let rowError = $state<string | null>(null);
let busyIds = $state<ReadonlySet<string>>(new Set());

function markBusy(id: string, busy: boolean): void {
	const next = new Set(busyIds);
	if (busy) {
		next.add(id);
	} else {
		next.delete(id);
	}
	busyIds = next;
}

async function rowAction(id: string, action: () => Promise<void>): Promise<void> {
	markBusy(id, true);
	rowError = null;
	try {
		await action();
	} catch (cause) {
		rowError = message(cause);
	} finally {
		markBusy(id, false);
	}
}

function confirmDelete(kind: 'bazarr' | 'lingarr', id: string, name: string): void {
	if (!window.confirm(`Delete ${kind} instance "${name}"? The mirrored data is removed too.`)) {
		return;
	}
	void rowAction(id, () =>
		kind === 'bazarr' ? instances.removeBazarr(id) : instances.removeLingarr(id)
	);
}

// --- Lingarr discovery --------------------------------------------------------
let discoveryFor = $state<string | null>(null);
let discovery = $state<LingarrDiscoveryResult | null>(null);
let discoveryName = $state('');
let discoveryError = $state<string | null>(null);
let discoveryBusy = $state(false);

async function openDiscovery(bazarrId: string): Promise<void> {
	discoveryFor = bazarrId;
	discovery = null;
	discoveryName = '';
	discoveryError = null;
	discoveryBusy = true;
	try {
		discovery = await getLingarrDiscovery(bazarrId);
	} catch (cause) {
		discoveryError = message(cause);
	} finally {
		discoveryBusy = false;
	}
}

async function confirmDiscovery(): Promise<void> {
	if (discoveryFor === null) {
		return;
	}
	discoveryBusy = true;
	discoveryError = null;
	try {
		await instances.confirmDiscovery(discoveryFor, discoveryName);
		discoveryFor = null;
	} catch (cause) {
		discoveryError = message(cause);
	} finally {
		discoveryBusy = false;
	}
}
</script>

<div class="space-y-6">
	<h1 class="text-2xl font-semibold">Instances</h1>

	{#if instances.error}
		<p class="text-sm text-destructive">{instances.error}</p>
	{/if}
	{#if rowError}
		<p class="text-sm text-destructive">{rowError}</p>
	{/if}

	<section class="space-y-3">
		<div class="flex items-center justify-between">
			<h2 class="text-lg font-medium">Bazarr</h2>
			<Button size="sm" onclick={() => openDialog('bazarr')}>Add Bazarr instance</Button>
		</div>
		{#if instances.bazarr.length === 0}
			<Card.Root>
				<Card.Content class="py-6 text-sm text-muted-foreground">
					No Bazarr instances yet. Perevoditarr needs at least one to mirror your library.
				</Card.Content>
			</Card.Root>
		{/if}
		{#each instances.bazarr as instance (instance.id)}
			{@const busy = busyIds.has(instance.id)}
			<Card.Root>
				<Card.Content class="space-y-3 py-4">
					<div class="flex flex-wrap items-center justify-between gap-3">
						<div class="space-y-1">
							<div class="flex items-center gap-2">
								<span class="font-medium">{instance.name}</span>
								<Badge variant={healthBadgeVariant(instance.health?.status)}>
									{instance.health?.status ?? 'unknown'}
								</Badge>
								{#if !instance.enabled}
									<Badge variant="outline">disabled</Badge>
								{/if}
							</div>
							<p class="text-sm text-muted-foreground">
								{instance.url} · v{instance.version ?? '?'} · {formatLatency(
									instance.health?.latencyMs
								)}
							</p>
						</div>
						<div class="flex flex-wrap gap-2">
							<Button
								variant="outline"
								size="sm"
								disabled={busy}
								onclick={() =>
									void rowAction(instance.id, () =>
										instances.setBazarrEnabled(instance.id, !instance.enabled)
									)}
							>
								{instance.enabled ? 'Disable' : 'Enable'}
							</Button>
							<Button
								variant="outline"
								size="sm"
								disabled={busy}
								onclick={() =>
									void rowAction(instance.id, () => instances.refreshBazarrHealth(instance.id))}
							>
								Check health
							</Button>
							<Button
								variant="destructive"
								size="sm"
								disabled={busy}
								onclick={() => confirmDelete('bazarr', instance.id, instance.name)}
							>
								Delete
							</Button>
						</div>
					</div>

					<div class="rounded-md border border-dashed p-3 text-sm">
						{#if instance.lingarrInstanceId !== null}
							<div class="flex flex-wrap items-center justify-between gap-2">
								<span>
									Linked Lingarr:
									<span class="font-medium">
										{instances.lingarrName(instance.lingarrInstanceId) ??
											instance.lingarrInstanceId}
									</span>
								</span>
								<Button
									variant="outline"
									size="sm"
									disabled={busy}
									onclick={() =>
										void rowAction(instance.id, () => instances.unlinkLingarr(instance.id))}
								>
									Unlink
								</Button>
							</div>
						{:else if discoveryFor === instance.id}
							{#if discoveryBusy && discovery === null}
								<p class="text-muted-foreground">Looking for a Lingarr provider in Bazarr…</p>
							{:else if discoveryError}
								<p class="text-destructive">{discoveryError}</p>
							{:else if discovery !== null && !discovery.configured}
								<p class="text-muted-foreground">
									No Lingarr provider is configured in this Bazarr instance.
								</p>
							{:else if discovery !== null}
								<div class="space-y-2">
									<p>
										Found Lingarr at <span class="font-mono">{discovery.url ?? '?'}</span>
										{discovery.hasApiKey ? '(with API key)' : '(no API key)'}
									</p>
									<div class="flex flex-wrap items-center gap-2">
										<Input
											class="max-w-48"
											placeholder="Instance name"
											bind:value={discoveryName}
										/>
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
						{:else}
							<div class="flex flex-wrap items-center justify-between gap-2">
								<span class="text-muted-foreground">No Lingarr linked.</span>
								<Button
									variant="outline"
									size="sm"
									onclick={() => void openDiscovery(instance.id)}
								>
									Discover Lingarr
								</Button>
							</div>
						{/if}
					</div>
				</Card.Content>
			</Card.Root>
		{/each}
	</section>

	<section class="space-y-3">
		<div class="flex items-center justify-between">
			<h2 class="text-lg font-medium">Lingarr</h2>
			<Button size="sm" variant="outline" onclick={() => openDialog('lingarr')}>
				Add Lingarr instance
			</Button>
		</div>
		{#if instances.lingarr.length === 0}
			<Card.Root>
				<Card.Content class="py-6 text-sm text-muted-foreground">
					No Lingarr instances yet. Link one via discovery on a Bazarr instance, or add it
					manually.
				</Card.Content>
			</Card.Root>
		{/if}
		{#each instances.lingarr as instance (instance.id)}
			{@const busy = busyIds.has(instance.id)}
			<Card.Root>
				<Card.Content class="flex flex-wrap items-center justify-between gap-3 py-4">
					<div class="space-y-1">
						<div class="flex items-center gap-2">
							<span class="font-medium">{instance.name}</span>
							<Badge variant={healthBadgeVariant(instance.health?.status)}>
								{instance.health?.status ?? 'unknown'}
							</Badge>
							{#if !instance.enabled}
								<Badge variant="outline">disabled</Badge>
							{/if}
						</div>
						<p class="text-sm text-muted-foreground">
							{instance.url} · v{instance.version ?? '?'} ·
							{instance.hasApiKey ? 'API key set' : 'no API key'}
						</p>
					</div>
					<div class="flex flex-wrap gap-2">
						<Button
							variant="outline"
							size="sm"
							disabled={busy}
							onclick={() =>
								void rowAction(instance.id, () =>
									instances.setLingarrEnabled(instance.id, !instance.enabled)
								)}
						>
							{instance.enabled ? 'Disable' : 'Enable'}
						</Button>
						<Button
							variant="outline"
							size="sm"
							disabled={busy}
							onclick={() =>
								void rowAction(instance.id, () => instances.refreshLingarrHealth(instance.id))}
						>
							Check health
						</Button>
						<Button
							variant="destructive"
							size="sm"
							disabled={busy}
							onclick={() => confirmDelete('lingarr', instance.id, instance.name)}
						>
							Delete
						</Button>
					</div>
				</Card.Content>
			</Card.Root>
		{/each}
	</section>
</div>

<Dialog.Root bind:open={dialogOpen}>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Add {dialogKind === 'bazarr' ? 'Bazarr' : 'Lingarr'} instance</Dialog.Title>
			<Dialog.Description>
				Test the connection before saving — the version must be supported.
			</Dialog.Description>
		</Dialog.Header>
		<div class="space-y-3">
			<Input placeholder="Name" bind:value={formName} />
			<Input placeholder="URL (e.g. http://bazarr:6767)" bind:value={formUrl} />
			<Input
				placeholder={dialogKind === 'bazarr' ? 'API key' : 'API key (optional)'}
				type="password"
				bind:value={formApiKey}
			/>
			{#if testResult}
				<div class="rounded-md border p-3 text-sm">
					{#if testResult.reachable}
						<div class="flex flex-wrap items-center gap-2">
							<Badge variant="secondary">reachable</Badge>
							<span>v{testResult.version ?? '?'}</span>
							{#if testResult.versionSupported === false}
								<Badge variant="destructive">unsupported version</Badge>
							{:else if testResult.versionSupported === true}
								<Badge variant="default">supported</Badge>
							{/if}
							<span class="text-muted-foreground">{formatLatency(testResult.latencyMs)}</span>
						</div>
					{:else}
						<p class="text-destructive">Unreachable: {testResult.error ?? 'unknown error'}</p>
					{/if}
				</div>
			{/if}
			{#if formError}
				<p class="text-sm text-destructive">{formError}</p>
			{/if}
		</div>
		<Dialog.Footer>
			<Button
				variant="outline"
				disabled={testBusy || formUrl.trim() === ''}
				onclick={() => void runTest()}
			>
				{testBusy ? 'Testing…' : 'Test connection'}
			</Button>
			<Button
				disabled={saveBusy ||
					formName.trim() === '' ||
					formUrl.trim() === '' ||
					(dialogKind === 'bazarr' && formApiKey.trim() === '')}
				onclick={() => void save()}
			>
				{saveBusy ? 'Saving…' : 'Save'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
