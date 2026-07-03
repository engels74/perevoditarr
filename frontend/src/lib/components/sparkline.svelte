<script lang="ts">
// Minimal dependency-free sparkline (P4-T1): plots a numeric series as an SVG
// polyline for the throughput trend cards on the stats dashboard.
let {
	points,
	label,
	color = 'var(--color-primary, currentColor)'
}: { points: number[]; label: string; color?: string } = $props();

const WIDTH = 240;
const HEIGHT = 40;
const max = $derived(Math.max(1, ...points));
const total = $derived(points.reduce((sum, value) => sum + value, 0));

const polyline = $derived.by(() => {
	if (points.length === 0) {
		return '';
	}
	if (points.length === 1) {
		const y = HEIGHT - (points[0] / max) * HEIGHT;
		return `0,${y} ${WIDTH},${y}`;
	}
	return points
		.map((value, index) => {
			const x = (index / (points.length - 1)) * WIDTH;
			const y = HEIGHT - (value / max) * HEIGHT;
			return `${x.toFixed(1)},${y.toFixed(1)}`;
		})
		.join(' ');
});
</script>

<div class="space-y-1">
	<div class="flex items-center justify-between text-xs">
		<span class="text-muted-foreground">{label}</span>
		<span class="font-mono">{total.toLocaleString()}</span>
	</div>
	{#if points.length === 0}
		<div class="flex h-10 items-center text-xs text-muted-foreground">No data yet.</div>
	{:else}
		<svg
			viewBox="0 0 {WIDTH} {HEIGHT}"
			class="h-10 w-full"
			preserveAspectRatio="none"
			role="img"
			aria-label={`${label} trend`}
		>
			<polyline
				points={polyline}
				fill="none"
				stroke={color}
				stroke-width="1.5"
				vector-effect="non-scaling-stroke"
			/>
		</svg>
	{/if}
</div>
