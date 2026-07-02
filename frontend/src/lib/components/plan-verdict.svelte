<script lang="ts">
import type { HeldVerdictDto, IncludedVerdictDto } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';

interface Props {
	verdict: IncludedVerdictDto | HeldVerdictDto;
}

let { verdict }: Props = $props();
</script>

{#if verdict.type === 'included'}
	<span class="inline-flex items-center gap-2">
		<Badge>would dispatch</Badge>
		<span class="font-mono text-xs text-muted-foreground">#{verdict.position}</span>
	</span>
{:else}
	<span class="inline-flex flex-wrap items-center gap-2">
		<Badge variant="outline">held</Badge>
		<span class="font-mono text-xs text-muted-foreground">{verdict.detail}</span>
	</span>
{/if}
