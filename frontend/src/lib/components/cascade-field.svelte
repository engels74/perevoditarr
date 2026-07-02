<script lang="ts">
// One row of the cascade editor: either this layer sets the value (control
// active) or it inherits (value preview + provenance chip). The switch is the
// per-layer override toggle (PRD §8.1: overrides explicit, visible, revocable).

import type { PolicyValuesDto } from '$lib/api/types';
import ProvenanceChip from '$lib/components/provenance-chip.svelte';
import { Input } from '$lib/components/ui/input';
import { Switch } from '$lib/components/ui/switch';
import {
	isSetAtLayer,
	type PolicyFieldSpec,
	type ProvenanceLike,
	withFieldCleared
} from '$lib/policy-display';

interface Props {
	spec: PolicyFieldSpec;
	values: PolicyValuesDto;
	inherited: { value: unknown; provenance: ProvenanceLike };
	onValuesChange: (next: PolicyValuesDto) => void;
}

let { spec, values, inherited, onValuesChange }: Props = $props();

const overridden = $derived(isSetAtLayer(values, spec.key));

function display(value: unknown): string {
	if (Array.isArray(value)) {
		return value.length > 0 ? value.join(', ') : 'none';
	}
	if (typeof value === 'boolean') {
		return value ? 'yes' : 'no';
	}
	return String(value);
}

function enableOverride(): void {
	// Start the override from the inherited value so toggling is lossless.
	onValuesChange({ ...values, [spec.key]: inherited.value });
}

function clearOverride(): void {
	onValuesChange(withFieldCleared(values, spec.key));
}

function setLanguages(raw: string): void {
	const codes = raw
		.split(',')
		.map((part) => part.trim().toLowerCase())
		.filter((part) => part.length > 0);
	onValuesChange({ ...values, [spec.key]: codes });
}

function setHours(raw: string): void {
	const parsed = Number.parseInt(raw, 10);
	if (!Number.isNaN(parsed) && parsed >= 0) {
		onValuesChange({ ...values, [spec.key]: parsed });
	}
}

function setBoolean(checked: boolean): void {
	onValuesChange({ ...values, [spec.key]: checked });
}
</script>

<div class="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0">
	<div class="min-w-48 flex-1">
		<p class="text-sm font-medium">{spec.label}</p>
		<p class="text-xs text-muted-foreground">{spec.help}</p>
	</div>

	<div class="flex items-center gap-3">
		{#if overridden}
			{#if spec.kind === 'languages'}
				<Input
					class="w-44 font-mono"
					value={Array.isArray(values[spec.key]) ? (values[spec.key] as string[]).join(', ') : ''}
					placeholder="en, da"
					aria-label={spec.label}
					onchange={(event) => setLanguages(event.currentTarget.value)}
				/>
			{:else if spec.kind === 'hours'}
				<Input
					class="w-24 font-mono"
					type="number"
					min="0"
					value={String(values[spec.key] ?? 0)}
					aria-label={spec.label}
					onchange={(event) => setHours(event.currentTarget.value)}
				/>
			{:else}
				<Switch
					checked={values[spec.key] === true}
					onCheckedChange={setBoolean}
					aria-label={spec.label}
				/>
			{/if}
		{:else}
			<span class="font-mono text-sm text-muted-foreground">{display(inherited.value)}</span>
			<ProvenanceChip provenance={inherited.provenance} />
		{/if}

		<label class="flex items-center gap-1.5 text-xs text-muted-foreground">
			<Switch
				checked={overridden}
				onCheckedChange={(checked) => (checked ? enableOverride() : clearOverride())}
				aria-label={`Override ${spec.label} at this layer`}
			/>
			override
		</label>
	</div>
</div>
