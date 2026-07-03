<script lang="ts">
import RefreshCwIcon from '@lucide/svelte/icons/refresh-cw';
import Trash2Icon from '@lucide/svelte/icons/trash-2';
import {
	checkWatchSourceHealth,
	createWatchSource,
	createWebhookSource,
	deleteWatchSource,
	deleteWebhookSource,
	listBazarrInstances,
	listWatchSources,
	listWebhookSources,
	refreshWatchScores,
	testWatchSource,
	updateWatchSource,
	updateWebhookSource
} from '$lib/api/endpoints';
import type { BazarrInstanceRead, WatchSourceCreate } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import { Input } from '$lib/components/ui/input';
import { Label } from '$lib/components/ui/label';
import { session } from '$lib/state/session.svelte';
import { createWatchSourcesState } from '$lib/state/watchSources.svelte';
import { createWebhooksState } from '$lib/state/webhooks.svelte';

type WatchType = WatchSourceCreate['sourceType'];

const watch = createWatchSourcesState({
	list: () => listWatchSources(),
	create: (body) => createWatchSource(body),
	update: (id, body) => updateWatchSource(id, body),
	remove: (id) => deleteWatchSource(id),
	test: (body) => testWatchSource(body),
	checkHealth: (id) => checkWatchSourceHealth(id),
	refresh: () => refreshWatchScores()
});

const webhooks = createWebhooksState({
	list: () => listWebhookSources(),
	create: (body) => createWebhookSource(body),
	update: (id, body) => updateWebhookSource(id, body),
	remove: (id) => deleteWebhookSource(id)
});

let bazarr = $state<BazarrInstanceRead[]>([]);

// Watch add-form
let wName = $state('');
let wType = $state<WatchType>('tautulli');
let wUrl = $state('');
let wCredential = $state('');
let wJellyfinUser = $state('');
let wIncludeWatchlist = $state(true);

// Webhook add-form
let hName = $state('');
let hInstance = $state('');
let hKind = $state<'bazarr' | 'sonarr'>('bazarr');

const canEdit = $derived(session.isAdmin);

$effect(() => {
	void watch.load();
	void webhooks.load();
	void listBazarrInstances().then((rows) => {
		bazarr = rows;
	});
});

function watchConfig(): WatchSourceCreate['config'] {
	return {
		jellyfinUser: wType === 'jellyfin' && wJellyfinUser ? wJellyfinUser : null,
		includeWatchlist: wType === 'plex' ? wIncludeWatchlist : true
	};
}

async function addWatch(event: SubmitEvent): Promise<void> {
	event.preventDefault();
	const ok = await watch.create({
		name: wName,
		sourceType: wType,
		url: wUrl,
		credential: wCredential,
		enabled: true,
		config: watchConfig()
	});
	if (ok) {
		wName = '';
		wUrl = '';
		wCredential = '';
		wJellyfinUser = '';
	}
}

function runWatchTest(): void {
	void watch.test({
		sourceType: wType,
		url: wUrl,
		credential: wCredential,
		config: watchConfig()
	});
}

async function addWebhook(event: SubmitEvent): Promise<void> {
	event.preventDefault();
	const ok = await webhooks.create({
		name: hName,
		bazarrInstanceId: hInstance,
		kind: hKind
	});
	if (ok) {
		hName = '';
	}
}

function instanceName(id: string): string {
	return bazarr.find((b) => b.id === id)?.name ?? id;
}
</script>

<div class="space-y-8">
	<!-- Watch integrations -->
	<section class="space-y-4">
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div>
				<h1 class="text-2xl font-semibold">Watch integrations</h1>
				<p class="text-sm text-muted-foreground">
					Tautulli, Plex, and Jellyfin raise the priority of recently or frequently watched
					titles (and Plex watchlist items). Optional and independent.
				</p>
			</div>
			{#if canEdit}
				<Button
					variant="outline"
					size="sm"
					disabled={watch.busy}
					onclick={() => void watch.refresh()}
				>
					<RefreshCwIcon class="size-4" /> Refresh scores
				</Button>
			{/if}
		</div>

		{#if watch.error}
			<p class="text-sm text-destructive">{watch.error}</p>
		{/if}
		{#if watch.lastRefresh}
			<p class="text-sm text-muted-foreground">
				Refreshed {watch.lastRefresh.titlesScored} title(s) from
				{watch.lastRefresh.sourcesPolled} source(s)
				({watch.lastRefresh.sourcesFailed} failed).
			</p>
		{/if}
		{#if watch.lastTest}
			<p class="text-sm {watch.lastTest.reachable ? 'text-muted-foreground' : 'text-destructive'}">
				Test: {watch.lastTest.reachable
					? `reachable — ${watch.lastTest.identity ?? 'unknown'} ${watch.lastTest.version ?? ''}`
					: (watch.lastTest.detail ?? 'unreachable')}
			</p>
		{/if}

		{#if canEdit}
			<Card.Root>
				<Card.Header class="pb-3">
					<Card.Title class="text-base">Add a watch source</Card.Title>
					<Card.Description>
						The API key/token is encrypted at rest and never shown again after saving.
					</Card.Description>
				</Card.Header>
				<Card.Content>
					<form class="space-y-3" onsubmit={addWatch}>
						<div class="grid gap-3 sm:grid-cols-2">
							<div class="space-y-1">
								<Label for="w-name">Name</Label>
								<Input id="w-name" bind:value={wName} placeholder="Living-room Plex" required />
							</div>
							<div class="space-y-1">
								<Label for="w-type">Type</Label>
								<select
									id="w-type"
									bind:value={wType}
									class="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
								>
									<option value="tautulli">Tautulli</option>
									<option value="plex">Plex</option>
									<option value="jellyfin">Jellyfin</option>
								</select>
							</div>
							<div class="space-y-1">
								<Label for="w-url">URL</Label>
								<Input id="w-url" bind:value={wUrl} placeholder="http://plex:32400" required />
							</div>
							<div class="space-y-1">
								<Label for="w-credential">API key / token</Label>
								<Input id="w-credential" bind:value={wCredential} type="password" required />
							</div>
							{#if wType === 'jellyfin'}
								<div class="space-y-1">
									<Label for="w-user">Jellyfin user (optional)</Label>
									<Input id="w-user" bind:value={wJellyfinUser} placeholder="first user" />
								</div>
							{/if}
							{#if wType === 'plex'}
								<label class="flex items-center gap-2 self-end text-sm">
									<input
										type="checkbox"
										class="size-4 rounded border-input"
										bind:checked={wIncludeWatchlist}
									/>
									Include account watchlist
								</label>
							{/if}
						</div>
						<div class="flex gap-2">
							<Button type="submit" disabled={watch.busy || !wName || !wUrl || !wCredential}>
								Add source
							</Button>
							<Button
								type="button"
								variant="outline"
								disabled={watch.busy || !wUrl || !wCredential}
								onclick={runWatchTest}
							>
								Test connection
							</Button>
						</div>
					</form>
				</Card.Content>
			</Card.Root>
		{/if}

		<div class="space-y-2">
			{#each watch.sources as source (source.id)}
				<Card.Root>
					<Card.Content class="flex flex-wrap items-center justify-between gap-3 py-4">
						<div class="space-y-1">
							<div class="flex items-center gap-2">
								<span class="font-medium">{source.name}</span>
								<Badge variant="outline" class="font-mono text-xs">{source.sourceType}</Badge>
								{#if !source.enabled}<Badge variant="secondary">disabled</Badge>{/if}
								{#if source.health}
									<Badge variant={source.health.reachable ? 'outline' : 'destructive'}>
										{source.health.reachable ? 'reachable' : 'unreachable'}
									</Badge>
								{/if}
							</div>
							<span class="font-mono text-xs text-muted-foreground">{source.url}</span>
						</div>
						{#if canEdit}
							<div class="flex items-center gap-1">
								<Button
									size="sm"
									variant="outline"
									disabled={watch.busy}
									onclick={() => void watch.checkHealth(source.id)}
								>
									Check
								</Button>
								<Button
									size="sm"
									variant="outline"
									disabled={watch.busy}
									onclick={() => void watch.update(source.id, { enabled: !source.enabled })}
								>
									{source.enabled ? 'Disable' : 'Enable'}
								</Button>
								<Button
									size="sm"
									variant="ghost"
									disabled={watch.busy}
									onclick={() => void watch.remove(source.id)}
									aria-label="Delete watch source"
								>
									<Trash2Icon class="size-4" />
								</Button>
							</div>
						{/if}
					</Card.Content>
				</Card.Root>
			{:else}
				<p class="text-sm text-muted-foreground">
					{watch.loading ? 'Loading…' : 'No watch sources configured.'}
				</p>
			{/each}
		</div>
	</section>

	<!-- Webhook ingestion -->
	<section class="space-y-4">
		<div>
			<h2 class="text-xl font-semibold">Webhook triggers</h2>
			<p class="text-sm text-muted-foreground">
				Bazarr/Sonarr can POST to a per-instance URL to trigger discovery immediately,
				complementing the polling loop.
			</p>
		</div>

		{#if webhooks.error}
			<p class="text-sm text-destructive">{webhooks.error}</p>
		{/if}

		{#if webhooks.lastCreated}
			<div class="rounded-md border border-primary/40 bg-primary/5 p-3 text-sm">
				<p class="font-medium">Webhook URL (shown once — copy it now):</p>
				<code class="mt-1 block break-all font-mono text-xs">{webhooks.lastCreated.ingestPath}</code>
				<Button
					size="sm"
					variant="ghost"
					class="mt-2"
					onclick={() => webhooks.dismissCreated()}
				>
					Dismiss
				</Button>
			</div>
		{/if}

		{#if canEdit}
			<Card.Root>
				<Card.Header class="pb-3">
					<Card.Title class="text-base">Add a webhook</Card.Title>
				</Card.Header>
				<Card.Content>
					<form class="space-y-3" onsubmit={addWebhook}>
						<div class="grid gap-3 sm:grid-cols-3">
							<div class="space-y-1">
								<Label for="h-name">Name</Label>
								<Input id="h-name" bind:value={hName} placeholder="Bazarr notify" required />
							</div>
							<div class="space-y-1">
								<Label for="h-instance">Bazarr instance</Label>
								<select
									id="h-instance"
									bind:value={hInstance}
									class="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
									required
								>
									<option value="" disabled>Select…</option>
									{#each bazarr as inst (inst.id)}
										<option value={inst.id}>{inst.name}</option>
									{/each}
								</select>
							</div>
							<div class="space-y-1">
								<Label for="h-kind">Source</Label>
								<select
									id="h-kind"
									bind:value={hKind}
									class="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
								>
									<option value="bazarr">Bazarr</option>
									<option value="sonarr">Sonarr</option>
								</select>
							</div>
						</div>
						<Button type="submit" disabled={webhooks.busy || !hName || !hInstance}>
							Create webhook
						</Button>
					</form>
				</Card.Content>
			</Card.Root>
		{/if}

		<div class="space-y-2">
			{#each webhooks.sources as source (source.id)}
				<Card.Root>
					<Card.Content class="flex flex-wrap items-center justify-between gap-3 py-4">
						<div class="space-y-1">
							<div class="flex items-center gap-2">
								<span class="font-medium">{source.name}</span>
								<Badge variant="outline" class="font-mono text-xs">{source.kind}</Badge>
								{#if !source.enabled}<Badge variant="secondary">disabled</Badge>{/if}
							</div>
							<span class="text-xs text-muted-foreground">
								{instanceName(source.bazarrInstanceId)}
								{#if source.lastReceivedAt}· last hit {source.lastReceivedAt}{/if}
							</span>
						</div>
						{#if canEdit}
							<div class="flex items-center gap-1">
								<Button
									size="sm"
									variant="outline"
									disabled={webhooks.busy}
									onclick={() => void webhooks.update(source.id, { enabled: !source.enabled })}
								>
									{source.enabled ? 'Disable' : 'Enable'}
								</Button>
								<Button
									size="sm"
									variant="ghost"
									disabled={webhooks.busy}
									onclick={() => void webhooks.remove(source.id)}
									aria-label="Delete webhook"
								>
									<Trash2Icon class="size-4" />
								</Button>
							</div>
						{/if}
					</Card.Content>
				</Card.Root>
			{:else}
				<p class="text-sm text-muted-foreground">
					{webhooks.loading ? 'Loading…' : 'No webhooks configured.'}
				</p>
			{/each}
		</div>
	</section>
</div>
