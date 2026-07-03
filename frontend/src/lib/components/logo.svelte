<script lang="ts">
import { cn } from '$lib/utils.js';

interface Props {
	/** Edge length of the mark in pixels. */
	size?: number;
	/** Render the "Perevoditarr" wordmark beside the mark. */
	wordmark?: boolean;
	class?: string;
}

let { size = 24, wordmark = true, class: className }: Props = $props();
</script>

<span class={cn('inline-flex items-center gap-2.5', className)}>
	<img
		src="/perevoditarr-logo.svg"
		alt={wordmark ? '' : 'Perevoditarr'}
		width={size}
		height={size}
		draggable="false"
		class="block shrink-0 select-none"
	/>
	{#if wordmark}
		<span class="text-lg font-semibold tracking-tight">Perevoditarr</span>
	{/if}
</span>
