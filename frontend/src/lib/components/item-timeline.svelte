<script lang="ts">
// Per-item timeline (P4-T2, FR-V4): the durable planes stitched into one
// chronological stream, plus Lingarr pass-through actions (FR-X3) rendered on
// each matched Lingarr request. Pass-through buttons are clearly labeled as
// acting on Lingarr and are always audit-logged server-side.
import { getIntentTimeline, lingarrPassthroughAction } from '$lib/api/endpoints';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import { formatDateTime } from '$lib/format';
import { createTimelineState, type PassthroughAction } from '$lib/state/timeline.svelte';

let { intentId }: { intentId: string } = $props();

const timeline = createTimelineState({
	timeline: (id) => getIntentTimeline(id),
	passthrough: (id, requestId, action) => lingarrPassthroughAction(id, requestId, action)
});

$effect(() => {
	void timeline.load(intentId);
});

const PASSTHROUGH_ACTIONS: PassthroughAction[] = ['cancel', 'retry', 'resume', 'remove'];

function entryLabel(type: string): string {
	switch (type) {
		case 'intent_event':
			return 'Perevoditarr';
		case 'bazarr_history':
			return 'Bazarr';
		case 'lingarr_request':
			return 'Lingarr';
		case 'passthrough_action':
			return 'Action';
		default:
			return type;
	}
}
</script>

<div class="space-y-4">
	<div class="flex flex-wrap items-center gap-2">
		<h3 class="text-sm font-semibold">Timeline</h3>
		{#if timeline.timeline}
			{#if !timeline.timeline.bazarrHistoryAvailable}
				<Badge variant="outline">Bazarr history unavailable</Badge>
			{/if}
			{#if !timeline.timeline.lingarrAvailable}
				<Badge variant="outline">Lingarr unavailable</Badge>
			{/if}
		{/if}
	</div>

	{#if timeline.loading}
		<p class="text-sm text-muted-foreground">Loading timeline…</p>
	{:else if timeline.error}
		<p class="text-sm text-destructive">{timeline.error}</p>
	{:else if timeline.entries.length === 0}
		<p class="text-sm text-muted-foreground">No timeline events recorded yet.</p>
	{:else}
		<ol class="space-y-3 border-l pl-4">
			{#each timeline.entries as entry, index (index)}
				<li class="space-y-1">
					<div class="flex items-center gap-2 text-xs text-muted-foreground">
						<Badge variant="secondary">{entryLabel(entry.type)}</Badge>
						<span class="font-mono">{formatDateTime(entry.at)}</span>
					</div>
					{#if entry.type === 'intent_event'}
						<p class="text-sm">
							<span class="font-mono">{entry.fromState ?? 'new'} → {entry.toState}</span>
							<span class="text-muted-foreground"> · {entry.reason} ({entry.actor})</span>
						</p>
					{:else if entry.type === 'bazarr_history'}
						<p class="text-sm">
							Translated{entry.language ? ` (${entry.language})` : ''}
							{#if entry.description}<span class="text-muted-foreground"> · {entry.description}</span>{/if}
						</p>
					{:else if entry.type === 'passthrough_action'}
						<p class="text-sm">
							Lingarr <span class="font-mono">{entry.action}</span> on request #{entry.lingarrRequestId}
							by {entry.actor}
							<Badge variant={entry.status === 'ok' ? 'default' : 'destructive'}>{entry.status}</Badge>
							{#if entry.detail}<span class="text-muted-foreground"> · {entry.detail}</span>{/if}
						</p>
					{:else if entry.type === 'lingarr_request'}
						<div class="space-y-2">
							<p class="text-sm">
								Lingarr request #{entry.requestId}
								<Badge variant={entry.active ? 'default' : 'secondary'}>{entry.status ?? 'unknown'}</Badge>
								{#if entry.errorMessage}<span class="text-destructive"> · {entry.errorMessage}</span>{/if}
							</p>
							<div class="flex flex-wrap gap-2">
								{#each PASSTHROUGH_ACTIONS as action (action)}
									<Button
										variant="outline"
										size="sm"
										disabled={timeline.busy}
										onclick={() => void timeline.act(entry.requestId, action)}
										title={`Act on Lingarr: ${action} request #${entry.requestId}`}
									>
										{action}
									</Button>
								{/each}
							</div>
						</div>
					{/if}
				</li>
			{/each}
		</ol>
	{/if}
</div>
