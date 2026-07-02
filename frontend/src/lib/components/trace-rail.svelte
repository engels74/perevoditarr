<script lang="ts">
// The decision rail: machine reasoning rendered as a mono-typeset chain.
// Each step is one rule evaluation; order IS the rule chain (FR-V1), so the
// sequential treatment encodes real structure, not decoration.

interface Props {
	steps: string[];
	/** Compact single-line rendering (tables); default is the vertical rail. */
	inline?: boolean;
}

let { steps, inline = false }: Props = $props();
</script>

{#if inline}
	<span class="font-mono text-xs text-muted-foreground">{steps.join(' → ')}</span>
{:else}
	<ol class="space-y-0 border-l border-border pl-0">
		{#each steps as step, index (index)}
			<li class="relative flex items-baseline gap-2 py-1 pl-4 font-mono text-xs">
				<span
					class="absolute -left-px top-0 h-full w-px {index === steps.length - 1
						? 'bg-primary'
						: ''}"
					aria-hidden="true"
				></span>
				<span class="select-none text-muted-foreground/60">{index === 0 ? '·' : '→'}</span>
				<span class={index === steps.length - 1 ? 'text-foreground' : 'text-muted-foreground'}>
					{step}
				</span>
			</li>
		{:else}
			<li class="py-1 pl-4 font-mono text-xs text-muted-foreground">No trace recorded</li>
		{/each}
	</ol>
{/if}
