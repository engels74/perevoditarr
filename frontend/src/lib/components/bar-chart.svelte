<script lang="ts">
// Minimal dependency-free horizontal bar chart (P4-T1). Used for failure-class
// distribution and per-language coverage totals on the stats dashboard.
interface Bar {
	label: string;
	value: number;
	subtitle?: string;
}

let {
	bars,
	formatValue = (value: number) => value.toLocaleString()
}: { bars: Bar[]; formatValue?: (value: number) => string } = $props();

const max = $derived(Math.max(1, ...bars.map((bar) => bar.value)));

function widthPercent(value: number): number {
	return Math.round((value / max) * 100);
}
</script>

{#if bars.length === 0}
	<p class="text-sm text-muted-foreground">No data yet.</p>
{:else}
	<div class="space-y-2">
		{#each bars as bar (bar.label)}
			<div class="space-y-1">
				<div class="flex items-center justify-between text-xs">
					<span class="text-muted-foreground">
						{bar.label}
						{#if bar.subtitle}<span class="text-muted-foreground/70"> · {bar.subtitle}</span>{/if}
					</span>
					<span class="font-mono">{formatValue(bar.value)}</span>
				</div>
				<div class="h-2 w-full overflow-hidden rounded-full bg-muted">
					<div
						class="h-full rounded-full bg-primary"
						style="width: {widthPercent(bar.value)}%"
					></div>
				</div>
			</div>
		{/each}
	</div>
{/if}
