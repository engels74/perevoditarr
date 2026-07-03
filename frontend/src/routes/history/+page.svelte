<script lang="ts">
import { getIntent, listBazarrInstances, listIntents } from '$lib/api/endpoints';
import type { BazarrInstanceRead } from '$lib/api/types';
import ItemTimeline from '$lib/components/item-timeline.svelte';
import TraceRail from '$lib/components/trace-rail.svelte';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Dialog from '$lib/components/ui/dialog';
import { Input } from '$lib/components/ui/input';
import * as Table from '$lib/components/ui/table';
import { pairLabel, subtitleFlags } from '$lib/policy-display';
import { createHistoryState } from '$lib/state/history.svelte';

const INTENT_STATES = [
	'discovered',
	'eligible',
	'dispatched',
	'converged',
	'superseded',
	'failed',
	'retry_eligible',
	'quarantined'
];

const STATE_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
	converged: 'default',
	dispatched: 'default',
	eligible: 'secondary',
	discovered: 'secondary',
	retry_eligible: 'secondary',
	superseded: 'outline',
	failed: 'destructive',
	quarantined: 'destructive'
};

const history = createHistoryState({
	list: (query) => listIntents(query),
	detail: (id) => getIntent(id)
});

let instances = $state<BazarrInstanceRead[]>([]);

$effect(() => {
	void history.load();
	void listBazarrInstances().then((rows) => {
		instances = rows;
	});
});

function formatWhen(iso: string): string {
	return new Date(iso).toLocaleString();
}

function rangeLabel(): string {
	if (history.total === 0) {
		return 'No results';
	}
	const from = history.offset + 1;
	const to = Math.min(history.offset + history.pageSize, history.total);
	return `${from}–${to} of ${history.total}`;
}
</script>

<div class="space-y-4">
	<h1 class="text-2xl font-semibold">History</h1>

	<div class="flex flex-wrap items-center gap-2">
		<select
			class="h-9 rounded-md border border-input bg-background px-2 text-sm"
			value={history.filters.states}
			onchange={(event) => void history.setFilters({ states: event.currentTarget.value })}
			aria-label="Intent state"
		>
			<option value="">State: any</option>
			{#each INTENT_STATES as state (state)}
				<option value={state}>{state}</option>
			{/each}
		</select>
		<select
			class="h-9 rounded-md border border-input bg-background px-2 text-sm"
			value={history.filters.instanceId}
			onchange={(event) => void history.setFilters({ instanceId: event.currentTarget.value })}
			aria-label="Bazarr instance"
		>
			<option value="">Instance: any</option>
			{#each instances as instance (instance.id)}
				<option value={instance.id}>{instance.name}</option>
			{/each}
		</select>
		<select
			class="h-9 rounded-md border border-input bg-background px-2 text-sm"
			value={history.filters.mediaType}
			onchange={(event) =>
				void history.setFilters({
					mediaType: event.currentTarget.value as '' | 'episode' | 'movie'
				})}
			aria-label="Media type"
		>
			<option value="">Media: any</option>
			<option value="episode">Episodes</option>
			<option value="movie">Movies</option>
		</select>
		<Input
			class="max-w-28 font-mono"
			placeholder="Target (da)"
			value={history.filters.targetLanguage}
			onchange={(event) =>
				void history.setFilters({ targetLanguage: event.currentTarget.value })}
			aria-label="Target language"
		/>
		<label class="flex items-center gap-1 text-sm text-muted-foreground">
			From
			<input
				type="date"
				class="h-9 rounded-md border border-input bg-background px-2 text-sm"
				value={history.filters.createdAfter}
				onchange={(event) =>
					void history.setFilters({ createdAfter: event.currentTarget.value })}
			/>
		</label>
		<label class="flex items-center gap-1 text-sm text-muted-foreground">
			To
			<input
				type="date"
				class="h-9 rounded-md border border-input bg-background px-2 text-sm"
				value={history.filters.createdBefore}
				onchange={(event) =>
					void history.setFilters({ createdBefore: event.currentTarget.value })}
			/>
		</label>
	</div>

	{#if history.error}
		<p class="text-sm text-destructive">{history.error}</p>
	{/if}

	<Table.Root>
		<Table.Header>
			<Table.Row>
				<Table.Head>Title</Table.Head>
				<Table.Head>Pair</Table.Head>
				<Table.Head>State</Table.Head>
				<Table.Head class="text-right">Priority</Table.Head>
				<Table.Head>Updated</Table.Head>
			</Table.Row>
		</Table.Header>
		<Table.Body>
			{#each history.items as intent (intent.id)}
				<Table.Row class="cursor-pointer" onclick={() => void history.open(intent.id)}>
					<Table.Cell class="font-medium">
						{intent.displayTitle}
						{#if intent.season !== null && intent.episodeNumber !== null}
							<span class="font-mono text-xs text-muted-foreground">
								S{String(intent.season).padStart(2, '0')}E{String(
									intent.episodeNumber
								).padStart(2, '0')}
							</span>
						{/if}
						{subtitleFlags(intent.forced, intent.hi)}
					</Table.Cell>
					<Table.Cell class="font-mono text-sm">
						{pairLabel(intent.sourceLanguage, intent.targetLanguage)}
					</Table.Cell>
					<Table.Cell>
						<Badge variant={STATE_VARIANT[intent.state] ?? 'outline'}>{intent.state}</Badge>
					</Table.Cell>
					<Table.Cell class="text-right font-mono">{intent.priority}</Table.Cell>
					<Table.Cell class="text-sm text-muted-foreground">
						{formatWhen(intent.updatedAt)}
					</Table.Cell>
				</Table.Row>
			{:else}
				<Table.Row>
					<Table.Cell colspan={5} class="text-center text-muted-foreground">
						{history.loading ? 'Loading…' : 'No intents match these filters'}
					</Table.Cell>
				</Table.Row>
			{/each}
		</Table.Body>
	</Table.Root>

	<div class="flex items-center justify-between text-sm text-muted-foreground">
		<span>{rangeLabel()}</span>
		<div class="flex gap-2">
			<Button
				variant="outline"
				size="sm"
				disabled={!history.hasPrev || history.loading}
				onclick={() => void history.prev()}
			>
				Previous
			</Button>
			<Button
				variant="outline"
				size="sm"
				disabled={!history.hasNext || history.loading}
				onclick={() => void history.next()}
			>
				Next
			</Button>
		</div>
	</div>
</div>

<Dialog.Root
	open={history.selected !== null}
	onOpenChange={(open) => {
		if (!open) {
			history.close();
		}
	}}
>
	<Dialog.Content class="max-h-[85vh] max-w-2xl overflow-y-auto">
		{#if history.selected}
			{@const detail = history.selected}
			<Dialog.Header>
				<Dialog.Title>
					{detail.intent.displayTitle}
					<span class="ml-1 font-mono text-sm text-muted-foreground">
						{pairLabel(detail.intent.sourceLanguage, detail.intent.targetLanguage)}
					</span>
				</Dialog.Title>
				<Dialog.Description>
					<Badge variant={STATE_VARIANT[detail.intent.state] ?? 'outline'}>
						{detail.intent.state}
					</Badge>
					<span class="ml-2 font-mono text-xs">priority {detail.intent.priority}</span>
				</Dialog.Description>
			</Dialog.Header>

			<section class="space-y-1">
				<h3 class="text-sm font-medium">Decision trace</h3>
				<TraceRail steps={detail.traceSteps} />
			</section>

			<section class="space-y-1">
				<h3 class="text-sm font-medium">Events</h3>
				<Table.Root>
					<Table.Header>
						<Table.Row>
							<Table.Head>When</Table.Head>
							<Table.Head>Actor</Table.Head>
							<Table.Head>Transition</Table.Head>
							<Table.Head>Reason</Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each detail.events as event (event.id)}
							<Table.Row>
								<Table.Cell class="whitespace-nowrap text-xs text-muted-foreground">
									{formatWhen(event.createdAt)}
								</Table.Cell>
								<Table.Cell class="font-mono text-xs">{event.actor}</Table.Cell>
								<Table.Cell class="font-mono text-xs">
									{event.fromState ?? '∅'} → {event.toState}
								</Table.Cell>
								<Table.Cell class="text-xs">{event.reason}</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			</section>

			<section class="space-y-1">
				<ItemTimeline intentId={detail.intent.id} />
			</section>
		{/if}
	</Dialog.Content>
</Dialog.Root>
