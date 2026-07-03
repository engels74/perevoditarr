<script lang="ts">
import { activatePreset, listPresets } from '$lib/api/endpoints';
import type { PresetRead } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import { session } from '$lib/state/session.svelte';

let { onBack, onNext, onSkip }: { onBack: () => void; onNext: () => void; onSkip: () => void } =
	$props();

let presets = $state<PresetRead[]>([]);
let localError = $state<string | null>(null);
let busyId = $state<string | null>(null);

function message(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

async function loadPresets(): Promise<void> {
	try {
		presets = await listPresets();
	} catch (cause) {
		localError = message(cause);
	}
}

$effect(() => {
	void loadPresets();
});

async function activate(id: string): Promise<void> {
	busyId = id;
	localError = null;
	try {
		await activatePreset(id);
		await loadPresets();
		await session.refreshSetup();
	} catch (cause) {
		localError = message(cause);
	} finally {
		busyId = null;
	}
}
</script>

<div class="space-y-4">
	<p class="text-sm text-muted-foreground">
		Choose the default translation policy. This controls how aggressively Perevoditarr acts — the
		<span class="font-medium">Observe</span> preset only watches without dispatching. You can change this
		later from Settings.
	</p>

	{#if localError}
		<p class="text-sm text-destructive">{localError}</p>
	{/if}

	<div class="grid gap-3 sm:grid-cols-2">
		{#each presets as preset (preset.id)}
			<Card.Root class={preset.active ? 'border-primary' : ''}>
				<Card.Header class="pb-2">
					<Card.Title class="flex items-center justify-between text-base">
						{preset.name}
						{#if preset.active}
							<Badge>active</Badge>
						{:else if preset.builtIn}
							<Badge variant="outline">built-in</Badge>
						{/if}
					</Card.Title>
					{#if preset.description}
						<Card.Description>{preset.description}</Card.Description>
					{/if}
				</Card.Header>
				<Card.Footer>
					{#if preset.active}
						<span class="text-sm text-muted-foreground">Current default</span>
					{:else}
						<Button
							size="sm"
							variant="outline"
							disabled={busyId === preset.id}
							onclick={() => void activate(preset.id)}
						>
							{busyId === preset.id ? 'Activating…' : 'Use this preset'}
						</Button>
					{/if}
				</Card.Footer>
			</Card.Root>
		{:else}
			<p class="text-sm text-muted-foreground">No presets available.</p>
		{/each}
	</div>

	<div class="flex items-center justify-between">
		<Button variant="ghost" onclick={onBack}>Back</Button>
		<div class="flex gap-2">
			<Button variant="outline" onclick={onSkip}>Skip</Button>
			<Button onclick={onNext}>Next</Button>
		</div>
	</div>
</div>
