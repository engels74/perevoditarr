<script lang="ts">
import { goto } from '$app/navigation';
import { type ExplainQuery, getCoverage, listMovies, listSeries } from '$lib/api/endpoints';
import type { MovieRead, SeriesRead } from '$lib/api/types';
import ExplainDialog from '$lib/components/explain-dialog.svelte';
import ItemPolicyActions from '$lib/components/item-policy-actions.svelte';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import { Input } from '$lib/components/ui/input';
import * as Table from '$lib/components/ui/table';
import * as Tabs from '$lib/components/ui/tabs';
import { subtitleLabel, wantedLabel } from '$lib/format';
import { createPagedList } from '$lib/state/library.svelte';

const series = createPagedList<SeriesRead>((query) => listSeries(query));
const movies = createPagedList<MovieRead>((query) => listMovies(query));

// One explainer dialog for the whole page; wanted chips select into it.
let explainQuery = $state<ExplainQuery | null>(null);
let explainTitle = $state('');

function openExplain(movie: MovieRead, wanted: { language: string; forced: boolean; hi: boolean }) {
	explainTitle = `${movie.title} — wants ${wantedLabel(wanted)}`;
	explainQuery = {
		instanceId: movie.bazarrInstanceId,
		mediaType: 'movie',
		externalMediaId: movie.radarrId,
		language: wanted.language,
		forced: wanted.forced,
		hi: wanted.hi
	};
}

let tab = $state('series');
let search = $state('');
let missingLanguage = $state('');
let languages = $state<string[]>([]);
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

$effect(() => {
	void series.load();
	void movies.load();
	void getCoverage().then((coverage) => {
		languages = coverage.map((stat) => stat.language);
	});
	return () => {
		if (debounceTimer !== null) {
			clearTimeout(debounceTimer);
		}
	};
});

function applyFilters(): void {
	void series.setFilters(search, missingLanguage);
	void movies.setFilters(search, missingLanguage);
}

function onSearchInput(): void {
	if (debounceTimer !== null) {
		clearTimeout(debounceTimer);
	}
	debounceTimer = setTimeout(applyFilters, 300);
}

function openSeries(row: SeriesRead): void {
	// Item context rides the URL so the drill-down can explain wants and
	// inspect policy without an extra series fetch (pure SPA).
	const params = new URLSearchParams({
		title: row.title,
		instanceId: row.bazarrInstanceId,
		sonarrSeriesId: String(row.sonarrSeriesId)
	});
	void goto(`/library/series/${row.id}?${params}`);
}

function rangeLabel(list: { offset: number; pageSize: number; total: number }): string {
	if (list.total === 0) {
		return 'No results';
	}
	const from = list.offset + 1;
	const to = Math.min(list.offset + list.pageSize, list.total);
	return `${from}–${to} of ${list.total}`;
}
</script>

<div class="space-y-4">
	<h1 class="text-2xl font-semibold">Library</h1>

	<div class="flex flex-wrap items-center gap-2">
		<Input
			class="max-w-xs"
			placeholder="Search titles…"
			bind:value={search}
			oninput={onSearchInput}
		/>
		<select
			class="h-9 rounded-md border border-input bg-background px-2 text-sm"
			bind:value={missingLanguage}
			onchange={applyFilters}
			aria-label="Missing target language"
		>
			<option value="">Missing language: any</option>
			{#each languages as language (language)}
				<option value={language}>{language}</option>
			{/each}
		</select>
	</div>

	<Tabs.Root bind:value={tab}>
		<Tabs.List>
			<Tabs.Trigger value="series">Series</Tabs.Trigger>
			<Tabs.Trigger value="movies">Movies</Tabs.Trigger>
		</Tabs.List>

		<Tabs.Content value="series" class="space-y-3 pt-3">
			{#if series.error}
				<p class="text-sm text-destructive">{series.error}</p>
			{/if}
			<Table.Root>
				<Table.Header>
					<Table.Row>
						<Table.Head>Title</Table.Head>
						<Table.Head>Year</Table.Head>
						<Table.Head>Monitored</Table.Head>
						<Table.Head class="text-right">Episodes</Table.Head>
						<Table.Head class="text-right">Wanted</Table.Head>
						<Table.Head class="w-12"><span class="sr-only">Actions</span></Table.Head>
					</Table.Row>
				</Table.Header>
				<Table.Body>
					{#each series.items as row (row.id)}
						<Table.Row class="cursor-pointer" onclick={() => openSeries(row)}>
							<Table.Cell class="font-medium">{row.title}</Table.Cell>
							<Table.Cell>{row.year ?? '—'}</Table.Cell>
							<Table.Cell>
								<Badge variant={row.monitored ? 'secondary' : 'outline'}>
									{row.monitored ? 'yes' : 'no'}
								</Badge>
							</Table.Cell>
							<Table.Cell class="text-right">{row.episodeCount}</Table.Cell>
							<Table.Cell class="text-right">{row.wantedCount}</Table.Cell>
							<Table.Cell onclick={(event) => event.stopPropagation()}>
								<ItemPolicyActions
									instanceId={row.bazarrInstanceId}
									mediaType="series"
									externalId={row.sonarrSeriesId}
									title={row.title}
									monitored={row.monitored}
								/>
							</Table.Cell>
						</Table.Row>
					{:else}
						<Table.Row>
							<Table.Cell colspan={6} class="text-center text-muted-foreground">
								{series.loading ? 'Loading…' : 'No series found'}
							</Table.Cell>
						</Table.Row>
					{/each}
				</Table.Body>
			</Table.Root>
			<div class="flex items-center justify-between text-sm text-muted-foreground">
				<span>{rangeLabel(series)}</span>
				<div class="flex gap-2">
					<Button
						variant="outline"
						size="sm"
						disabled={!series.hasPrev || series.loading}
						onclick={() => void series.prev()}
					>
						Previous
					</Button>
					<Button
						variant="outline"
						size="sm"
						disabled={!series.hasNext || series.loading}
						onclick={() => void series.next()}
					>
						Next
					</Button>
				</div>
			</div>
		</Tabs.Content>

		<Tabs.Content value="movies" class="space-y-3 pt-3">
			{#if movies.error}
				<p class="text-sm text-destructive">{movies.error}</p>
			{/if}
			<Table.Root>
				<Table.Header>
					<Table.Row>
						<Table.Head>Title</Table.Head>
						<Table.Head>Year</Table.Head>
						<Table.Head>Monitored</Table.Head>
						<Table.Head>Subtitles</Table.Head>
						<Table.Head>Wanted</Table.Head>
						<Table.Head class="w-12"><span class="sr-only">Actions</span></Table.Head>
					</Table.Row>
				</Table.Header>
				<Table.Body>
					{#each movies.items as row (row.id)}
						<Table.Row>
							<Table.Cell class="font-medium">{row.title}</Table.Cell>
							<Table.Cell>{row.year ?? '—'}</Table.Cell>
							<Table.Cell>
								<Badge variant={row.monitored ? 'secondary' : 'outline'}>
									{row.monitored ? 'yes' : 'no'}
								</Badge>
							</Table.Cell>
							<Table.Cell>
								<div class="flex flex-wrap gap-1">
									{#each row.subtitles as subtitle (subtitleLabel(subtitle))}
										<Badge variant="secondary">{subtitleLabel(subtitle)}</Badge>
									{:else}
										<span class="text-muted-foreground">—</span>
									{/each}
								</div>
							</Table.Cell>
							<Table.Cell>
								<div class="flex flex-wrap gap-1">
									{#each row.wanted as wanted (wantedLabel(wanted))}
										<button
											type="button"
											class="cursor-pointer"
											title="Why is this not planned?"
											onclick={() => openExplain(row, wanted)}
										>
											<Badge variant="outline">{wantedLabel(wanted)}</Badge>
										</button>
									{:else}
										<span class="text-muted-foreground">—</span>
									{/each}
								</div>
							</Table.Cell>
							<Table.Cell>
								<ItemPolicyActions
									instanceId={row.bazarrInstanceId}
									mediaType="movie"
									externalId={row.radarrId}
									title={row.title}
									monitored={row.monitored}
								/>
							</Table.Cell>
						</Table.Row>
					{:else}
						<Table.Row>
							<Table.Cell colspan={6} class="text-center text-muted-foreground">
								{movies.loading ? 'Loading…' : 'No movies found'}
							</Table.Cell>
						</Table.Row>
					{/each}
				</Table.Body>
			</Table.Root>
			<div class="flex items-center justify-between text-sm text-muted-foreground">
				<span>{rangeLabel(movies)}</span>
				<div class="flex gap-2">
					<Button
						variant="outline"
						size="sm"
						disabled={!movies.hasPrev || movies.loading}
						onclick={() => void movies.prev()}
					>
						Previous
					</Button>
					<Button
						variant="outline"
						size="sm"
						disabled={!movies.hasNext || movies.loading}
						onclick={() => void movies.next()}
					>
						Next
					</Button>
				</div>
			</div>
		</Tabs.Content>
	</Tabs.Root>
</div>

{#if explainQuery}
	<ExplainDialog
		open={explainQuery !== null}
		title={explainTitle}
		query={explainQuery}
		onClose={() => (explainQuery = null)}
	/>
{/if}
