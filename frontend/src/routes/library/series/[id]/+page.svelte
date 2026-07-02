<script lang="ts">
import { page } from '$app/state';
import { listSeriesEpisodes } from '$lib/api/endpoints';
import type { EpisodeRead } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Table from '$lib/components/ui/table';
import { subtitleLabel, wantedLabel } from '$lib/format';
import { createPagedList } from '$lib/state/library.svelte';

const seriesId = $derived(page.params.id ?? '');
const title = $derived(page.url.searchParams.get('title') ?? 'Series');

const episodes = createPagedList<EpisodeRead>((query) =>
	listSeriesEpisodes(seriesId, { limit: query.limit, offset: query.offset })
);

$effect(() => {
	if (seriesId !== '') {
		void episodes.load();
	}
});

function episodeCode(row: EpisodeRead): string {
	const season = String(row.season).padStart(2, '0');
	const episode = String(row.episode).padStart(2, '0');
	return `S${season}E${episode}`;
}
</script>

<div class="space-y-4">
	<div class="flex items-center gap-3">
		<Button href="/library" variant="ghost" size="sm">← Library</Button>
		<h1 class="text-2xl font-semibold">{title}</h1>
	</div>

	{#if episodes.error}
		<p class="text-sm text-destructive">{episodes.error}</p>
	{/if}

	<Table.Root>
		<Table.Header>
			<Table.Row>
				<Table.Head>Episode</Table.Head>
				<Table.Head>Title</Table.Head>
				<Table.Head>Monitored</Table.Head>
				<Table.Head>Subtitles</Table.Head>
				<Table.Head>Wanted</Table.Head>
			</Table.Row>
		</Table.Header>
		<Table.Body>
			{#each episodes.items as row (row.id)}
				<Table.Row>
					<Table.Cell class="font-mono text-xs">{episodeCode(row)}</Table.Cell>
					<Table.Cell class="font-medium">{row.title}</Table.Cell>
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
						{episodes.loading ? 'Loading…' : 'No episodes found'}
					</Table.Cell>
				</Table.Row>
			{/each}
		</Table.Body>
	</Table.Root>

	<div class="flex items-center justify-between text-sm text-muted-foreground">
		<span>
			{episodes.total === 0
				? 'No results'
				: `${episodes.offset + 1}–${Math.min(episodes.offset + episodes.pageSize, episodes.total)} of ${episodes.total}`}
		</span>
		<div class="flex gap-2">
			<Button
				variant="outline"
				size="sm"
				disabled={!episodes.hasPrev || episodes.loading}
				onclick={() => void episodes.prev()}
			>
				Previous
			</Button>
			<Button
				variant="outline"
				size="sm"
				disabled={!episodes.hasNext || episodes.loading}
				onclick={() => void episodes.next()}
			>
				Next
			</Button>
		</div>
	</div>
</div>
