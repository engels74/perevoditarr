<script lang="ts">
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import { formatDateTime, formatLatency, healthBadgeVariant } from '$lib/format';
import { createDashboardState } from '$lib/state/dashboard.svelte';
import { instances } from '$lib/state/instances.svelte';
import { sse } from '$lib/state/sse.svelte';

const dashboard = createDashboardState();

$effect(() => {
	void instances.load();
	void dashboard.loadAll();
});

// Liveness plane only (PRD §7.3): SSE events trigger refetches of the
// affected slice; the REST responses stay the source of truth.
$effect(() => {
	sse.connect();
	const unsubscribes = [
		sse.subscribe('instances.health', () => void instances.load()),
		sse.subscribe('mirror.sync', () => {
			void dashboard.loadFreshness();
			void dashboard.loadCoverage();
		}),
		sse.subscribe('doctor.completed', () => void dashboard.loadDoctor())
	];
	return () => {
		for (const unsubscribe of unsubscribes) {
			unsubscribe();
		}
	};
});

const doctorSummary = $derived.by(() => {
	const summary = dashboard.doctor?.summary ?? null;
	return summary === null
		? null
		: {
				info: summary.info ?? 0,
				warn: summary.warn ?? 0,
				critical: summary.critical ?? 0
			};
});

const healthCards = $derived([
	...instances.bazarr.map((instance) => ({ instance, kind: 'Bazarr' as const })),
	...instances.lingarr.map((instance) => ({ instance, kind: 'Lingarr' as const }))
]);

function coveragePercent(existing: number, wanted: number): number {
	const total = existing + wanted;
	return total === 0 ? 100 : Math.round((existing / total) * 100);
}
</script>

<div class="space-y-6">
	<h1 class="text-2xl font-semibold">Dashboard</h1>

	{#if dashboard.error}
		<p class="text-sm text-destructive">{dashboard.error}</p>
	{/if}

	<section class="space-y-3">
		<h2 class="text-sm font-medium text-muted-foreground">Instance health</h2>
		{#if instances.error}
			<p class="text-sm text-destructive">{instances.error}</p>
		{:else if healthCards.length === 0}
			<Card.Root>
				<Card.Content class="py-6 text-sm text-muted-foreground">
					No instances configured yet. Add one under
					<a href="/settings/instances" class="underline">Settings → Instances</a>.
				</Card.Content>
			</Card.Root>
		{:else}
			<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
				{#each healthCards as entry (entry.kind + entry.instance.id)}
					<Card.Root>
						<Card.Header>
							<Card.Title class="flex items-center justify-between gap-2 text-base">
								<span class="truncate">{entry.instance.name}</span>
								<Badge variant={healthBadgeVariant(entry.instance.health?.status)}>
									{entry.instance.health?.status ?? 'unknown'}
								</Badge>
							</Card.Title>
							<Card.Description>{entry.kind}</Card.Description>
						</Card.Header>
						<Card.Content class="space-y-1 text-sm text-muted-foreground">
							<p>Version: {entry.instance.version ?? '—'}</p>
							<p>Latency: {formatLatency(entry.instance.health?.latencyMs)}</p>
							{#if entry.kind === 'Bazarr'}
								<p>Queue depth: {entry.instance.health?.queueDepth ?? '—'}</p>
							{/if}
						</Card.Content>
					</Card.Root>
				{/each}
			</div>
		{/if}
	</section>

	<div class="grid gap-4 lg:grid-cols-2">
		<Card.Root>
			<Card.Header>
				<Card.Title class="text-base">Subtitle coverage</Card.Title>
				<Card.Description>Existing vs wanted per language</Card.Description>
			</Card.Header>
			<Card.Content>
				{#if dashboard.coverage.length === 0}
					<p class="text-sm text-muted-foreground">No coverage data yet — run a sync first.</p>
				{:else}
					<div class="space-y-3">
						{#each dashboard.coverage as stat (stat.language)}
							{@const existing = stat.episodesWithSubtitle + stat.moviesWithSubtitle}
							{@const wanted = stat.episodesWanted + stat.moviesWanted}
							{@const percent = coveragePercent(existing, wanted)}
							<div class="space-y-1">
								<div class="flex items-center justify-between text-sm">
									<span class="font-medium uppercase">{stat.language}</span>
									<span class="text-muted-foreground">
										{existing} have · {wanted} wanted · {percent}%
									</span>
								</div>
								<div class="h-2 rounded-full bg-muted">
									<div class="h-2 rounded-full bg-primary" style="width: {percent}%"></div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</Card.Content>
		</Card.Root>

		<Card.Root>
			<Card.Header>
				<Card.Title class="text-base">Doctor</Card.Title>
				<Card.Description>Latest configuration health check</Card.Description>
			</Card.Header>
			<Card.Content class="space-y-3">
				{#if dashboard.doctor === null}
					<p class="text-sm text-muted-foreground">No doctor run yet.</p>
				{:else}
					<div class="flex flex-wrap items-center gap-2">
						<Badge variant="destructive">critical {doctorSummary?.critical ?? 0}</Badge>
						<Badge variant="secondary">warn {doctorSummary?.warn ?? 0}</Badge>
						<Badge variant="outline">info {doctorSummary?.info ?? 0}</Badge>
					</div>
					<p class="text-sm text-muted-foreground">
						Finished {formatDateTime(dashboard.doctor.finishedAt)}
					</p>
				{/if}
				<Button href="/doctor" variant="outline" size="sm">Open doctor</Button>
			</Card.Content>
		</Card.Root>
	</div>

	<Card.Root>
		<Card.Header>
			<Card.Title class="text-base">Mirror freshness</Card.Title>
			<Card.Description>Last sync per Bazarr instance</Card.Description>
		</Card.Header>
		<Card.Content>
			{#if dashboard.freshness.length === 0}
				<p class="text-sm text-muted-foreground">No mirror data yet.</p>
			{:else}
				<div class="space-y-4">
					{#each dashboard.freshness as entry (entry.bazarrInstanceId)}
						{@const pending = dashboard.syncPending.has(entry.bazarrInstanceId)}
						<div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
							<div class="space-y-1 text-sm">
								<div class="flex items-center gap-2">
									<span class="font-medium">
										{instances.bazarrName(entry.bazarrInstanceId) ?? entry.bazarrInstanceId}
									</span>
									{#if entry.stale}
										<Badge variant="destructive">stale</Badge>
									{:else}
										<Badge variant="secondary">fresh</Badge>
									{/if}
								</div>
								<p class="text-muted-foreground">
									Full sync: {formatDateTime(entry.lastFullSyncAt)} · Wanted sync:
									{formatDateTime(entry.lastWantedSyncAt)}
								</p>
							</div>
							<div class="flex gap-2">
								<Button
									size="sm"
									disabled={pending}
									onclick={() => void dashboard.triggerSync(entry.bazarrInstanceId, true)}
								>
									Sync now
								</Button>
								<Button
									size="sm"
									variant="outline"
									disabled={pending}
									onclick={() => void dashboard.triggerWantedSync(entry.bazarrInstanceId)}
								>
									Sync wanted
								</Button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</Card.Content>
	</Card.Root>
</div>
