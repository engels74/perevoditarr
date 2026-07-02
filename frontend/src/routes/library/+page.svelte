<script lang="ts">
import { goto } from '$app/navigation';
import { getCoverage, listMovies, listSeries } from '$lib/api/endpoints';
import type { MovieRead, SeriesRead } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import { Input } from '$lib/components/ui/input';
import * as Table from '$lib/components/ui/table';
import * as Tabs from '$lib/components/ui/tabs';
import { subtitleLabel, wantedLabel } from '$lib/format';
import { createPagedList } from '$lib/state/library.svelte';

const series = createPagedList<SeriesRead>((query) => listSeries(query));
const movies = createPagedList<MovieRead>((query) => listMovies(query));

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
	void goto(`/library/series/${row.id}?title=${encodeURIComponent(row.title)}`);
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
						</Table.Row>
					{:else}
						<Table.Row>
							<Table.Cell colspan={5} class="text-center text-muted-foreground">
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
										<Badge variant="outline">{wantedLabel(wanted)}</Badge>
									{:else}
										<span class="text-muted-foreground">—</span>
									{/each}
								</div>
							</Table.Cell>
						</Table.Row>
					{:else}
						<Table.Row>
							<Table.Cell colspan={5} class="text-center text-muted-foreground">
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
