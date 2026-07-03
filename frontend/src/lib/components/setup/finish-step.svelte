<script lang="ts">
import CheckIcon from '@lucide/svelte/icons/check';
import { Button } from '$lib/components/ui/button';
import { session } from '$lib/state/session.svelte';

let { onBack, onFinish }: { onBack: () => void; onFinish: () => void } = $props();

const checklist = $derived(session.setupChecklist);
const canFinish = $derived((checklist?.hasAdmin ?? false) && (checklist?.bazarrCount ?? 0) >= 1);

async function finish(): Promise<void> {
	const ok = await session.finishSetup();
	if (ok) {
		onFinish();
	}
}

const rows = $derived([
	{ label: 'Administrator account', done: checklist?.hasAdmin ?? false, required: true },
	{
		label: `Bazarr instances (${checklist?.bazarrCount ?? 0})`,
		done: (checklist?.bazarrCount ?? 0) >= 1,
		required: true
	},
	{
		label: `Lingarr instances (${checklist?.lingarrCount ?? 0})`,
		done: (checklist?.lingarrCount ?? 0) >= 1,
		required: false
	},
	{
		label: `Notification routes (${checklist?.notificationCount ?? 0})`,
		done: (checklist?.notificationCount ?? 0) >= 1,
		required: false
	}
]);
</script>

<div class="space-y-4">
	<p class="text-sm text-muted-foreground">
		Review your setup and finish. Optional steps can always be configured later from Settings.
	</p>

	<ul class="space-y-2">
		{#each rows as row (row.label)}
			<li class="flex items-center gap-2 text-sm">
				<span
					class="flex size-5 items-center justify-center rounded-full border {row.done
						? 'border-primary text-primary'
						: 'border-muted-foreground/40 text-muted-foreground'}"
				>
					{#if row.done}
						<CheckIcon class="size-3" />
					{/if}
				</span>
				<span>{row.label}</span>
				{#if row.required && !row.done}
					<span class="text-xs text-destructive">required</span>
				{:else if !row.required}
					<span class="text-xs text-muted-foreground">optional</span>
				{/if}
			</li>
		{/each}
	</ul>

	{#if session.error}
		<p class="text-sm text-destructive">{session.error}</p>
	{/if}

	<div class="flex items-center justify-between">
		<Button variant="ghost" onclick={onBack}>Back</Button>
		<Button disabled={!canFinish || session.loading} onclick={() => void finish()}>
			{session.loading ? 'Finishing…' : 'Finish setup'}
		</Button>
	</div>
</div>
