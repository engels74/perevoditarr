<script lang="ts">
import type { RailStatusDto } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';

// Live cap/budget/window/breaker gauges for one scope (global or instance),
// with explanations (P3-T7, FR-Q3). Read-only; controls live on the page.
let { status }: { status: RailStatusDto } = $props();

function pct(used: number, limit: number | null): number {
	if (limit === null || limit <= 0) {
		return 0;
	}
	return Math.min(100, Math.round((used / limit) * 100));
}

const breakerVariant = $derived(
	status.breaker == null || status.breaker.state === 'closed' ? 'secondary' : 'destructive'
);
</script>

<div class="space-y-3">
	<div class="flex flex-wrap items-center gap-2">
		{#if status.scope === 'instance'}
			<Badge variant={status.dispatchActive ? 'default' : 'secondary'}>
				{status.dispatchActive ? 'Active' : 'Observe'}
			</Badge>
		{/if}
		{#if status.paused}
			<Badge variant="destructive">Paused{status.pausedReason ? ` · ${status.pausedReason}` : ''}</Badge>
		{/if}
		<Badge variant="outline" class="font-mono">window K={status.dispatchWindowK}</Badge>
		<Badge variant={status.windowOpen ? 'outline' : 'destructive'}>
			{status.windowOpen ? 'schedule open' : 'outside schedule'}
		</Badge>
		{#if status.breaker != null}
			<Badge variant={breakerVariant} class="font-mono">
				breaker {status.breaker.state}
				{#if status.breaker.consecutiveFailures > 0}
					· {status.breaker.consecutiveFailures} fails
				{/if}
			</Badge>
		{/if}
	</div>

	<div class="grid gap-2 sm:grid-cols-3">
		{#each status.caps as cap (cap.period)}
			<div class="space-y-1">
				<div class="flex items-center justify-between text-xs">
					<span class="capitalize text-muted-foreground">{cap.period} cap</span>
					<span class="font-mono {cap.blocked ? 'text-destructive' : ''}">
						{cap.used}{cap.limit === null ? '' : `/${cap.limit}`}
					</span>
				</div>
				<div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
					<div
						class="h-full rounded-full {cap.blocked ? 'bg-destructive' : 'bg-primary'}"
						style="width: {cap.limit === null ? 0 : pct(cap.used, cap.limit)}%"
					></div>
				</div>
			</div>
		{/each}
	</div>

	{#if status.budget != null}
		<div class="space-y-1">
			<div class="flex items-center justify-between text-xs">
				<span class="text-muted-foreground">daily character budget</span>
				<span class="font-mono {status.budget.blocked ? 'text-destructive' : ''}">
					{status.budget.usedCharacters.toLocaleString()}{status.budget.limitCharacters === null
						? ''
						: `/${status.budget.limitCharacters.toLocaleString()}`}
				</span>
			</div>
			<div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
				<div
					class="h-full rounded-full {status.budget.blocked ? 'bg-destructive' : 'bg-primary'}"
					style="width: {pct(status.budget.usedCharacters, status.budget.limitCharacters)}%"
				></div>
			</div>
		</div>
	{/if}
</div>
