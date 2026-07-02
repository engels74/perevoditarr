<script lang="ts">
import { LAYER_COLOR_VAR, type ProvenanceLike, provenanceChip } from '$lib/policy-display';

interface Props {
	provenance: ProvenanceLike;
}

let { provenance }: Props = $props();

const chip = $derived(provenanceChip(provenance));
</script>

<span
	class="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-xs text-muted-foreground"
	title={chip.explanation}
>
	<span
		class="size-1.5 rounded-full"
		style="background-color: {LAYER_COLOR_VAR[chip.layer]}"
		aria-hidden="true"
	></span>
	{chip.label}
</span>
