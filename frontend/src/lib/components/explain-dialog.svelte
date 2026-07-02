<script lang="ts">
// "Why is this (not) planned?" — the discovery rule chain for one wanted
// subtitle, rendered as the decision rail (resolver-driven, FR-U4).

import { type ExplainQuery, explainCandidate } from '$lib/api/endpoints';
import type { ExplainRead } from '$lib/api/types';
import TraceRail from '$lib/components/trace-rail.svelte';
import { Badge } from '$lib/components/ui/badge';
import * as Dialog from '$lib/components/ui/dialog';
import { pairLabel } from '$lib/policy-display';

interface Props {
	open: boolean;
	title: string;
	query: ExplainQuery;
	onClose: () => void;
}

let { open, title, query, onClose }: Props = $props();

let explanation = $state<ExplainRead | null>(null);
let error = $state<string | null>(null);

$effect(() => {
	if (!open) {
		return;
	}
	explanation = null;
	error = null;
	explainCandidate(query)
		.then((result) => {
			explanation = result;
		})
		.catch((cause: unknown) => {
			error = cause instanceof Error ? cause.message : String(cause);
		});
});
</script>

<Dialog.Root
	{open}
	onOpenChange={(next) => {
		if (!next) {
			onClose();
		}
	}}
>
	<Dialog.Content class="max-h-[85vh] max-w-lg overflow-y-auto">
		<Dialog.Header>
			<Dialog.Title>
				Why is this {explanation?.outcome === 'planned' ? 'planned' : 'not planned'}?
			</Dialog.Title>
			<Dialog.Description>{title}</Dialog.Description>
		</Dialog.Header>

		{#if error}
			<p class="text-sm text-destructive">{error}</p>
		{:else if explanation === null}
			<p class="text-sm text-muted-foreground">Loading…</p>
		{:else if explanation.outcome === 'not_wanted'}
			<p class="text-sm text-muted-foreground">
				Bazarr does not list this subtitle as missing, so Perevoditarr never evaluates it. If
				it should be wanted, check the item's language profile in Bazarr.
			</p>
		{:else}
			<div class="space-y-3">
				<p class="flex items-center gap-2 text-sm">
					{#if explanation.outcome === 'planned'}
						<Badge>planned</Badge>
						<span class="font-mono text-xs">
							{pairLabel(explanation.sourceLanguage, query.language)}
						</span>
					{:else}
						<Badge variant="outline">not planned</Badge>
						<span class="text-muted-foreground">{explanation.detail}</span>
					{/if}
				</p>
				<TraceRail steps={explanation.traceSteps} />
			</div>
		{/if}
	</Dialog.Content>
</Dialog.Root>
