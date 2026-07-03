<script lang="ts">
// Statistics dashboard (P4-T1, FR-U8): throughput, durations, failure rates by
// class, converged vs. superseded, per-language coverage trends, and budget
// reconciliation (Lingarr actuals vs. the conservative heuristic).
import { getStatsOverview, listBazarrInstances } from '$lib/api/endpoints';
import type { BazarrInstanceRead } from '$lib/api/types';
import BarChart from '$lib/components/bar-chart.svelte';
import Sparkline from '$lib/components/sparkline.svelte';
import { Badge } from '$lib/components/ui/badge';
import * as Card from '$lib/components/ui/card';
import * as Table from '$lib/components/ui/table';
import { formatDateTime } from '$lib/format';
import { createStatsState } from '$lib/state/stats.svelte';

const RANGES = [
	{ days: 7, label: '7d' },
	{ days: 30, label: '30d' },
	{ days: 90, label: '90d' }
];

const stats = createStatsState({
	overview: (days, instanceId) => getStatsOverview(days, instanceId)
});

let instances = $state<BazarrInstanceRead[]>([]);

$effect(() => {
	void stats.load();
	void listBazarrInstances().then((rows) => {
		instances = rows;
	});
});

const failureBars = $derived(
	stats.failureClasses.map((entry) => ({
		label: entry.failureClass,
		value: entry.count,
		subtitle: `${Math.round(entry.rate * 100)}%`
	}))
);

const coverageBars = $derived(
	stats.coverage.map((series) => ({
		label: series.targetLanguage,
		value: series.total
	}))
);

const convergedSeries = $derived(stats.throughput.map((point) => point.converged));
const dispatchedSeries = $derived(stats.throughput.map((point) => point.dispatched));
const failedSeries = $derived(stats.throughput.map((point) => point.failed));

function meanDuration(seconds: number | null): string {
	if (seconds === null) {
		return '—';
	}
	if (seconds < 60) {
		return `${Math.round(seconds)}s`;
	}
	return `${Math.round(seconds / 60)}m`;
}
</script>

<div class="space-y-6">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<h1 class="text-2xl font-semibold">Statistics</h1>
		<div class="flex flex-wrap items-center gap-2">
			<select
				class="h-9 rounded-md border border-input bg-background px-2 text-sm"
				value={stats.instanceId ?? ''}
				onchange={(event) =>
					void stats.setInstance(event.currentTarget.value === '' ? null : event.currentTarget.value)}
				aria-label="Bazarr instance"
			>
				<option value="">All instances</option>
				{#each instances as instance (instance.id)}
					<option value={instance.id}>{instance.name}</option>
				{/each}
			</select>
			<div class="flex gap-1">
				{#each RANGES as range (range.days)}
					<button
						type="button"
						class="rounded-md px-3 py-1.5 text-sm transition-colors hover:bg-accent"
						class:bg-accent={stats.days === range.days}
						aria-pressed={stats.days === range.days}
						onclick={() => void stats.setDays(range.days)}
					>
						{range.label}
					</button>
				{/each}
			</div>
		</div>
	</div>

	{#if stats.error}
		<p class="text-sm text-destructive">{stats.error}</p>
	{/if}

	{#if stats.totals}
		{@const totals = stats.totals}
		<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
			<Card.Root>
				<Card.Header class="pb-2"><Card.Description>Dispatched</Card.Description></Card.Header>
				<Card.Content class="text-2xl font-semibold">{totals.dispatched.toLocaleString()}</Card.Content>
			</Card.Root>
			<Card.Root>
				<Card.Header class="pb-2"><Card.Description>Converged</Card.Description></Card.Header>
				<Card.Content class="text-2xl font-semibold text-emerald-600 dark:text-emerald-400">
					{totals.converged.toLocaleString()}
				</Card.Content>
			</Card.Root>
			<Card.Root>
				<Card.Header class="pb-2"><Card.Description>Superseded</Card.Description></Card.Header>
				<Card.Content class="text-2xl font-semibold">{totals.superseded.toLocaleString()}</Card.Content>
			</Card.Root>
			<Card.Root>
				<Card.Header class="pb-2"><Card.Description>Failed</Card.Description></Card.Header>
				<Card.Content class="text-2xl font-semibold text-destructive">
					{totals.failed.toLocaleString()}
				</Card.Content>
			</Card.Root>
			<Card.Root>
				<Card.Header class="pb-2"><Card.Description>Mean latency</Card.Description></Card.Header>
				<Card.Content class="text-2xl font-semibold">{meanDuration(totals.meanDurationSeconds)}</Card.Content>
			</Card.Root>
		</div>

		<div class="grid gap-4 lg:grid-cols-2">
			<Card.Root>
				<Card.Header>
					<Card.Title>Throughput</Card.Title>
					<Card.Description>Daily outcomes over the selected window.</Card.Description>
				</Card.Header>
				<Card.Content class="space-y-3">
					<Sparkline label="Converged" points={convergedSeries} />
					<Sparkline label="Dispatched" points={dispatchedSeries} />
					<Sparkline label="Failed" points={failedSeries} />
				</Card.Content>
			</Card.Root>

			<Card.Root>
				<Card.Header>
					<Card.Title>Failures by class</Card.Title>
					<Card.Description>The §7.4 failure taxonomy (transient / environmental / provider / poison).</Card.Description>
				</Card.Header>
				<Card.Content>
					<BarChart bars={failureBars} />
				</Card.Content>
			</Card.Root>

			<Card.Root>
				<Card.Header>
					<Card.Title>Coverage by language</Card.Title>
					<Card.Description>Cumulative converged translations per target language.</Card.Description>
				</Card.Header>
				<Card.Content>
					<BarChart bars={coverageBars} />
				</Card.Content>
			</Card.Root>

			<Card.Root>
				<Card.Header>
					<Card.Title>Budget reconciliation</Card.Title>
					<Card.Description>Lingarr actuals vs. the conservative estimate (FR-U8).</Card.Description>
				</Card.Header>
				<Card.Content>
					{#if stats.budget.length === 0}
						<p class="text-sm text-muted-foreground">No Lingarr statistics reconciled yet.</p>
					{:else}
						<Table.Root>
							<Table.Header>
								<Table.Row>
									<Table.Head>Lingarr</Table.Head>
									<Table.Head class="text-right">Files</Table.Head>
									<Table.Head class="text-right">Chars/file (actual)</Table.Head>
									<Table.Head class="text-right">Heuristic (ep/movie)</Table.Head>
									<Table.Head>Updated</Table.Head>
								</Table.Row>
							</Table.Header>
							<Table.Body>
								{#each stats.budget as row (row.lingarrInstanceId)}
									<Table.Row>
										<Table.Cell class="font-medium">
											{row.instanceName}
											{#if !row.hasActuals}<Badge variant="outline">no sample</Badge>{/if}
										</Table.Cell>
										<Table.Cell class="text-right font-mono">{row.totalFiles.toLocaleString()}</Table.Cell>
										<Table.Cell class="text-right font-mono">
											{row.hasActuals ? Math.round(row.charactersPerFile).toLocaleString() : '—'}
										</Table.Cell>
										<Table.Cell class="text-right font-mono">
											{row.heuristicCharactersEpisode.toLocaleString()} / {row.heuristicCharactersMovie.toLocaleString()}
										</Table.Cell>
										<Table.Cell class="text-xs text-muted-foreground">{formatDateTime(row.capturedAt)}</Table.Cell>
									</Table.Row>
								{/each}
							</Table.Body>
						</Table.Root>
					{/if}
				</Card.Content>
			</Card.Root>
		</div>
	{:else if stats.loading}
		<p class="text-sm text-muted-foreground">Loading statistics…</p>
	{:else}
		<p class="text-sm text-muted-foreground">No statistics recorded yet.</p>
	{/if}
</div>
