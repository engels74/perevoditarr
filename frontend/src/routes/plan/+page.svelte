<script lang="ts">
import EyeIcon from '@lucide/svelte/icons/eye';
import RefreshCwIcon from '@lucide/svelte/icons/refresh-cw';
import { getPlanPreview, listBazarrInstances } from '$lib/api/endpoints';
import type { BazarrInstanceRead, PlanItemDto } from '$lib/api/types';
import PlanVerdict from '$lib/components/plan-verdict.svelte';
import * as Alert from '$lib/components/ui/alert';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import * as Table from '$lib/components/ui/table';
import * as Tooltip from '$lib/components/ui/tooltip';
import { pairLabel, subtitleFlags } from '$lib/policy-display';
import { createPlanState } from '$lib/state/plan.svelte';
import { sse } from '$lib/state/sse.svelte';

const plan = createPlanState((query) => getPlanPreview(query));

let instances = $state<BazarrInstanceRead[]>([]);

$effect(() => {
	void plan.load();
	void listBazarrInstances().then((rows) => {
		instances = rows;
	});
	// Discovery output changes the backlog; refresh the preview when it lands.
	const unsubscribe = sse.subscribe('intents.discovered', () => void plan.load());
	sse.connect();
	return unsubscribe;
});

function itemTitle(item: PlanItemDto): string {
	if (item.mediaType === 'episode' && item.season !== null && item.episodeNumber !== null) {
		const season = String(item.season).padStart(2, '0');
		const episode = String(item.episodeNumber).padStart(2, '0');
		return `${item.displayTitle} S${season}E${episode}`;
	}
	return item.displayTitle;
}

function scoreSummary(item: PlanItemDto): string {
	if (!item.scoreComponents) {
		return `priority ${item.priority}`;
	}
	const parts = Object.entries(item.scoreComponents)
		.filter(([, value]) => value !== 0)
		.map(([key, value]) => `${key} ${value > 0 ? '+' : ''}${value}`);
	return parts.join(', ') || `priority ${item.priority}`;
}

function estimateLabel(item: PlanItemDto): string {
	return `~${item.estimate.characters.toLocaleString()} chars · ${item.estimate.lines.toLocaleString()} lines`;
}

const instanceName = $derived(new Map(instances.map((instance) => [instance.id, instance.name])));
</script>

<div class="space-y-4">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<h1 class="text-2xl font-semibold">Plan</h1>
		<div class="flex items-center gap-2">
			<select
				class="h-9 rounded-md border border-input bg-background px-2 text-sm"
				value={plan.instanceId}
				onchange={(event) => void plan.setInstance(event.currentTarget.value)}
				aria-label="Bazarr instance"
			>
				<option value="">All instances</option>
				{#each instances as instance (instance.id)}
					<option value={instance.id}>{instance.name}</option>
				{/each}
			</select>
			<Button variant="outline" size="sm" disabled={plan.loading} onclick={() => void plan.load()}>
				<RefreshCwIcon class="size-4" />
				Refresh
			</Button>
		</div>
	</div>

	{#if plan.plan?.dryRun}
		<Alert.Root>
			<EyeIcon class="size-4" />
			<Alert.Title>
				Observe mode — nothing will be dispatched
				{#if plan.plan.activePreset}
					<span class="font-normal text-muted-foreground">
						· active preset <span class="font-mono">{plan.plan.activePreset}</span>
					</span>
				{/if}
			</Alert.Title>
			<Alert.Description>
				This is the plan Perevoditarr would execute under the current policies and rails.
			</Alert.Description>
		</Alert.Root>
	{/if}

	{#if plan.error}
		<p class="text-sm text-destructive">{plan.error}</p>
	{/if}

	{#if plan.plan}
		<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
			<Card.Root>
				<Card.Header class="pb-2">
					<Card.Description>Evaluated</Card.Description>
					<Card.Title class="font-mono text-2xl">{plan.plan.totals.evaluated}</Card.Title>
				</Card.Header>
			</Card.Root>
			<Card.Root>
				<Card.Header class="pb-2">
					<Card.Description>Would dispatch</Card.Description>
					<Card.Title class="font-mono text-2xl">{plan.plan.totals.included}</Card.Title>
				</Card.Header>
			</Card.Root>
			<Card.Root>
				<Card.Header class="pb-2">
					<Card.Description>Held by rails</Card.Description>
					<Card.Title class="font-mono text-2xl">{plan.plan.totals.held}</Card.Title>
				</Card.Header>
			</Card.Root>
			<Card.Root>
				<Card.Header class="pb-2">
					<Card.Description>Estimated volume</Card.Description>
					<Card.Title class="font-mono text-2xl">
						{plan.plan.totals.estimatedCharacters.toLocaleString()}
						<span class="text-sm font-normal text-muted-foreground">chars</span>
					</Card.Title>
				</Card.Header>
			</Card.Root>
		</div>

		{#if plan.plan.groups.length > 1}
			<div class="flex flex-wrap gap-2">
				{#each plan.plan.groups as group (group.bazarrInstanceId)}
					<Badge variant="secondary" class="font-mono">
						{group.instanceName}: {group.included} run · {group.held} held
					</Badge>
				{/each}
			</div>
		{/if}

		<section class="space-y-2">
			<h2 class="text-lg font-medium">Next up</h2>
			<Table.Root>
				<Table.Header>
					<Table.Row>
						<Table.Head class="w-10">#</Table.Head>
						<Table.Head>Title</Table.Head>
						<Table.Head>Pair</Table.Head>
						<Table.Head>Profile</Table.Head>
						<Table.Head>Why now</Table.Head>
						<Table.Head class="text-right">Estimate</Table.Head>
					</Table.Row>
				</Table.Header>
				<Table.Body>
					{#each plan.included as item (item.intentId)}
						<Table.Row>
							<Table.Cell class="font-mono text-muted-foreground">
								{item.verdict.type === 'included' ? item.verdict.position : '—'}
							</Table.Cell>
							<Table.Cell class="font-medium">
								{itemTitle(item)}{subtitleFlags(item.forced, item.hi)}
								{#if plan.instanceId === '' && instanceName.get(item.bazarrInstanceId)}
									<span class="ml-1 text-xs text-muted-foreground">
										· {instanceName.get(item.bazarrInstanceId)}
									</span>
								{/if}
								{#if item.bumped}
									<Badge variant="secondary" class="ml-1">bumped</Badge>
								{/if}
							</Table.Cell>
							<Table.Cell class="font-mono text-sm">
								{pairLabel(item.sourceLanguage, item.targetLanguage)}
							</Table.Cell>
							<Table.Cell class="text-sm text-muted-foreground">
								{item.profileName ?? 'global defaults'}
							</Table.Cell>
							<Table.Cell class="font-mono text-xs text-muted-foreground">
								{scoreSummary(item)}
							</Table.Cell>
							<Table.Cell class="text-right">
								<Tooltip.Provider>
									<Tooltip.Root>
										<Tooltip.Trigger class="font-mono text-xs text-muted-foreground">
											{estimateLabel(item)}
										</Tooltip.Trigger>
										<Tooltip.Content>
											Basis: {item.estimate.basis === 'actuals'
												? 'rolling actuals from Lingarr statistics'
												: 'conservative runtime heuristic'}
										</Tooltip.Content>
									</Tooltip.Root>
								</Tooltip.Provider>
							</Table.Cell>
						</Table.Row>
					{:else}
						<Table.Row>
							<Table.Cell colspan={6} class="text-center text-muted-foreground">
								{plan.loading ? 'Loading…' : 'Nothing would dispatch right now'}
							</Table.Cell>
						</Table.Row>
					{/each}
				</Table.Body>
			</Table.Root>
		</section>

		{#if plan.held.length > 0}
			<section class="space-y-2">
				<h2 class="text-lg font-medium">Held back</h2>
				<Table.Root>
					<Table.Header>
						<Table.Row>
							<Table.Head>Title</Table.Head>
							<Table.Head>Pair</Table.Head>
							<Table.Head>Verdict</Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each plan.held as item (item.intentId)}
							<Table.Row>
								<Table.Cell class="font-medium">
									{itemTitle(item)}{subtitleFlags(item.forced, item.hi)}
								</Table.Cell>
								<Table.Cell class="font-mono text-sm">
									{pairLabel(item.sourceLanguage, item.targetLanguage)}
								</Table.Cell>
								<Table.Cell><PlanVerdict verdict={item.verdict} /></Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			</section>
		{/if}
	{/if}
</div>
