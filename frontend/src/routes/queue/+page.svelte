<script lang="ts">
import PauseIcon from '@lucide/svelte/icons/pause';
import PlayIcon from '@lucide/svelte/icons/play';
import RefreshCwIcon from '@lucide/svelte/icons/refresh-cw';
import {
	activateInstance,
	deactivateInstance,
	excludeQuarantined,
	getRailsOverview,
	listBacklog,
	listBazarrInstances,
	listInFlight,
	listNeedsAttention,
	listQuarantine,
	pauseInstanceRails,
	pauseRailsGlobal,
	releaseQuarantined,
	resumeInstanceRails,
	resumeRailsGlobal,
	retryQuarantined
} from '$lib/api/endpoints';
import type { BazarrInstanceRead, IntentRead, RailStatusDto } from '$lib/api/types';
import RailsGauges from '$lib/components/rails-gauges.svelte';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import * as Table from '$lib/components/ui/table';
import * as Tabs from '$lib/components/ui/tabs';
import { pairLabel, subtitleFlags } from '$lib/policy-display';
import { createQueueState, type QueueTab } from '$lib/state/queue.svelte';
import { createRailsState } from '$lib/state/rails.svelte';
import { sse } from '$lib/state/sse.svelte';

const queue = createQueueState({
	backlog: (query) => listBacklog(query),
	inFlight: (query) => listInFlight(query),
	needsAttention: (query) => listNeedsAttention(query),
	quarantine: (query) => listQuarantine(query),
	retry: (id) => retryQuarantined(id),
	release: (id) => releaseQuarantined(id),
	exclude: (id) => excludeQuarantined(id)
});

const rails = createRailsState({
	overview: () => getRailsOverview(),
	pauseGlobal: (reason) => pauseRailsGlobal(reason),
	resumeGlobal: () => resumeRailsGlobal(),
	pauseInstance: (id, reason) => pauseInstanceRails(id, reason),
	resumeInstance: (id) => resumeInstanceRails(id),
	activate: (id) => activateInstance(id),
	deactivate: (id) => deactivateInstance(id)
});

let instances = $state<BazarrInstanceRead[]>([]);
// Latest telemetry job progress (fuzzy §6.5 correlation — UI liveness only).
let liveProgress = $state<{ label: string; value: number; maximum: number } | null>(null);

const TABS: { value: QueueTab; label: string }[] = [
	{ value: 'backlog', label: 'Backlog' },
	{ value: 'inFlight', label: 'In flight' },
	{ value: 'needsAttention', label: 'Needs attention' },
	{ value: 'quarantine', label: 'Quarantine' }
];

$effect(() => {
	void queue.load();
	void rails.load();
	void listBazarrInstances().then((rows) => {
		instances = rows;
	});
	const unsubscribers = [
		sse.subscribe('intents.dispatched', () => {
			void queue.load();
			void rails.load();
		}),
		sse.subscribe('intents.verified', () => {
			void queue.load();
			void rails.load();
		}),
		sse.subscribe('rails.breaker', () => void rails.load()),
		sse.subscribe('rails.pause', () => void rails.load()),
		sse.subscribe('rails.activation', () => void rails.load()),
		sse.subscribe('telemetry.jobs', (data) => {
			const job = data as { label?: string; value?: number; maximum?: number };
			if (job.maximum && job.maximum > 0) {
				liveProgress = {
					label: job.label ?? 'translating',
					value: job.value ?? 0,
					maximum: job.maximum
				};
			}
		})
	];
	sse.connect();
	return () => {
		for (const unsubscribe of unsubscribers) {
			unsubscribe();
		}
	};
});

const instanceName = $derived(new Map(instances.map((instance) => [instance.id, instance.name])));

function itemTitle(item: IntentRead): string {
	if (item.mediaType === 'episode' && item.season !== null && item.episodeNumber !== null) {
		const season = String(item.season).padStart(2, '0');
		const episode = String(item.episodeNumber).padStart(2, '0');
		return `${item.displayTitle} S${season}E${episode}`;
	}
	return item.displayTitle;
}

function toggleActivation(status: RailStatusDto): void {
	if (status.bazarrInstanceId === null) {
		return;
	}
	if (status.dispatchActive) {
		if (
			confirm(
				`Return ${status.instanceName} to Observe? In-flight work finishes; no new dispatches.`
			)
		) {
			void rails.deactivate(status.bazarrInstanceId);
		}
	} else if (
		confirm(
			`Activate dispatch for ${status.instanceName}? Rails in force: window K=${status.dispatchWindowK}, ` +
				`${status.windowOpen ? 'schedule open' : 'outside schedule'}. Translations will be sent through Bazarr.`
		)
	) {
		void rails.activate(status.bazarrInstanceId);
	}
}
</script>

<div class="space-y-5">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<h1 class="text-2xl font-semibold">Queue</h1>
		<div class="flex items-center gap-2">
			<select
				class="h-9 rounded-md border border-input bg-background px-2 text-sm"
				value={queue.instanceId}
				onchange={(event) => void queue.setInstance(event.currentTarget.value)}
				aria-label="Bazarr instance"
			>
				<option value="">All instances</option>
				{#each instances as instance (instance.id)}
					<option value={instance.id}>{instance.name}</option>
				{/each}
			</select>
			<Button variant="outline" size="sm" disabled={queue.loading} onclick={() => void queue.load()}>
				<RefreshCwIcon class="size-4" />
				Refresh
			</Button>
		</div>
	</div>

	{#if rails.error}
		<p class="text-sm text-destructive">{rails.error}</p>
	{/if}

	<!-- Rails: global + per-instance gauges with pause/resume + activation -->
	<div class="grid gap-3 lg:grid-cols-2">
		{#if rails.globalRails}
			<Card.Root>
				<Card.Header class="flex-row items-center justify-between space-y-0 pb-3">
					<Card.Title class="text-base">Global rails</Card.Title>
					{#if rails.globalRails.paused}
						<Button
							size="sm"
							variant="outline"
							disabled={rails.busy}
							onclick={() => void rails.resumeGlobal()}
						>
							<PlayIcon class="size-4" /> Resume all
						</Button>
					{:else}
						<Button
							size="sm"
							variant="outline"
							disabled={rails.busy}
							onclick={() => void rails.pauseGlobal('manual')}
						>
							<PauseIcon class="size-4" /> Pause all
						</Button>
					{/if}
				</Card.Header>
				<Card.Content>
					<RailsGauges status={rails.globalRails} />
				</Card.Content>
			</Card.Root>
		{/if}

		{#each rails.instances as status (status.bazarrInstanceId)}
			<Card.Root>
				<Card.Header class="flex-row items-center justify-between space-y-0 pb-3">
					<Card.Title class="text-base">{status.instanceName}</Card.Title>
					<div class="flex items-center gap-2">
						<Button
							size="sm"
							variant={status.dispatchActive ? 'outline' : 'default'}
							disabled={rails.busy}
							onclick={() => toggleActivation(status)}
						>
							{status.dispatchActive ? 'Deactivate' : 'Activate'}
						</Button>
						{#if status.bazarrInstanceId}
							{#if status.paused}
								<Button
									size="sm"
									variant="outline"
									disabled={rails.busy}
									onclick={() =>
										status.bazarrInstanceId && void rails.resumeInstance(status.bazarrInstanceId)}
								>
									<PlayIcon class="size-4" />
								</Button>
							{:else}
								<Button
									size="sm"
									variant="outline"
									disabled={rails.busy}
									onclick={() =>
										status.bazarrInstanceId && void rails.pauseInstance(status.bazarrInstanceId, 'manual')}
								>
									<PauseIcon class="size-4" />
								</Button>
							{/if}
						{/if}
					</div>
				</Card.Header>
				<Card.Content>
					<RailsGauges {status} />
				</Card.Content>
			</Card.Root>
		{/each}
	</div>

	{#if queue.error}
		<p class="text-sm text-destructive">{queue.error}</p>
	{/if}

	<Tabs.Root value={queue.tab} onValueChange={(value) => void queue.setTab(value as QueueTab)}>
		<Tabs.List>
			{#each TABS as entry (entry.value)}
				<Tabs.Trigger value={entry.value}>{entry.label}</Tabs.Trigger>
			{/each}
		</Tabs.List>

		{#each TABS as entry (entry.value)}
			<Tabs.Content value={entry.value} class="space-y-2">
				{#if entry.value === 'inFlight' && liveProgress}
					<div class="rounded-md border bg-muted/40 p-2 text-xs">
						<div class="mb-1 flex justify-between font-mono text-muted-foreground">
							<span>{liveProgress.label}</span>
							<span>{liveProgress.value}/{liveProgress.maximum}</span>
						</div>
						<div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
							<div
								class="h-full rounded-full bg-primary transition-all"
								style="width: {Math.min(100, Math.round((liveProgress.value / liveProgress.maximum) * 100))}%"
							></div>
						</div>
					</div>
				{/if}

				<Table.Root>
					<Table.Header>
						<Table.Row>
							<Table.Head>Title</Table.Head>
							<Table.Head>Pair</Table.Head>
							<Table.Head>State</Table.Head>
							{#if entry.value === 'needsAttention' || entry.value === 'quarantine'}
								<Table.Head class="text-right">Actions</Table.Head>
							{:else}
								<Table.Head class="text-right">Priority</Table.Head>
							{/if}
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each queue.items as item (item.id)}
							<Table.Row>
								<Table.Cell class="font-medium">
									{itemTitle(item)}{subtitleFlags(item.forced, item.hi)}
									{#if queue.instanceId === '' && instanceName.get(item.bazarrInstanceId)}
										<span class="ml-1 text-xs text-muted-foreground">
											· {instanceName.get(item.bazarrInstanceId)}
										</span>
									{/if}
									{#if item.bumpedAt}
										<Badge variant="secondary" class="ml-1">bumped</Badge>
									{/if}
								</Table.Cell>
								<Table.Cell class="font-mono text-sm">
									{pairLabel(item.sourceLanguage, item.targetLanguage)}
								</Table.Cell>
								<Table.Cell>
									{#if entry.value === 'inFlight'}
										<Badge variant="secondary" class="animate-pulse">translating</Badge>
									{:else}
										<span class="font-mono text-xs text-muted-foreground">{item.state}</span>
									{/if}
								</Table.Cell>
								<Table.Cell class="text-right">
									{#if entry.value === 'quarantine'}
										<div class="flex justify-end gap-1">
											<Button
												size="sm"
												variant="outline"
												disabled={queue.acting === item.id}
												onclick={() => void queue.retry(item.id)}>Retry</Button
											>
											<Button
												size="sm"
												variant="outline"
												disabled={queue.acting === item.id}
												onclick={() => void queue.release(item.id)}>Release</Button
											>
											<Button
												size="sm"
												variant="outline"
												disabled={queue.acting === item.id}
												onclick={() => void queue.exclude(item.id)}>Exclude</Button
											>
										</div>
									{:else if entry.value === 'needsAttention'}
										<Button
											size="sm"
											variant="outline"
											disabled={queue.acting === item.id}
											onclick={() => void queue.retry(item.id)}>Retry</Button
										>
									{:else}
										<span class="font-mono text-xs text-muted-foreground">{item.priority}</span>
									{/if}
								</Table.Cell>
							</Table.Row>
						{:else}
							<Table.Row>
								<Table.Cell colspan={4} class="text-center text-muted-foreground">
									{queue.loading ? 'Loading…' : 'Nothing here'}
								</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			</Tabs.Content>
		{/each}
	</Tabs.Root>
</div>
