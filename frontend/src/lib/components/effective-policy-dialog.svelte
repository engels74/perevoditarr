<script lang="ts">
// Per-item effective-policy inspector (FR-P2): every value with provenance.

import { type EffectivePolicyQuery, getEffectivePolicy } from '$lib/api/endpoints';
import type { EffectivePolicyRead } from '$lib/api/types';
import ProvenanceChip from '$lib/components/provenance-chip.svelte';
import * as Dialog from '$lib/components/ui/dialog';
import { POLICY_FIELDS, resolvedFor } from '$lib/policy-display';

interface Props {
	open: boolean;
	title: string;
	query: EffectivePolicyQuery;
	onClose: () => void;
}

let { open, title, query, onClose }: Props = $props();

let effective = $state<EffectivePolicyRead | null>(null);
let error = $state<string | null>(null);

$effect(() => {
	if (!open) {
		return;
	}
	effective = null;
	error = null;
	getEffectivePolicy(query)
		.then((result) => {
			effective = result;
		})
		.catch((cause: unknown) => {
			error = cause instanceof Error ? cause.message : String(cause);
		});
});

function display(value: unknown): string {
	if (Array.isArray(value)) {
		return value.length > 0 ? value.join(', ') : 'none';
	}
	if (typeof value === 'boolean') {
		return value ? 'yes' : 'no';
	}
	if (value !== null && typeof value === 'object') {
		return Object.entries(value)
			.map(([key, entry]) => `${key}=${String(entry)}`)
			.join(' ');
	}
	return String(value);
}
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
			<Dialog.Title>Effective policy</Dialog.Title>
			<Dialog.Description>{title}</Dialog.Description>
		</Dialog.Header>

		{#if error}
			<p class="text-sm text-destructive">{error}</p>
		{:else if effective === null}
			<p class="text-sm text-muted-foreground">Loading…</p>
		{:else}
			<div>
				{#each POLICY_FIELDS as spec (spec.key)}
					{@const resolved = resolvedFor(effective, spec.key)}
					{#if resolved}
						<div
							class="flex items-center justify-between gap-3 border-b py-2 text-sm last:border-b-0"
						>
							<span>{spec.label}</span>
							<span class="flex items-center gap-2">
								<span class="font-mono text-xs">{display(resolved.value)}</span>
								<ProvenanceChip provenance={resolved.provenance} />
							</span>
						</div>
					{/if}
				{/each}
				<div class="flex items-center justify-between gap-3 py-2 text-sm">
					<span>Priority weights</span>
					<span class="flex items-center gap-2">
						<span class="font-mono text-xs">{display(effective.priorityWeights.value)}</span>
						<ProvenanceChip provenance={effective.priorityWeights.provenance} />
					</span>
				</div>
			</div>
		{/if}
	</Dialog.Content>
</Dialog.Root>
