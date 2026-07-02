<script lang="ts">
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import { formatDateTime, severityBadgeVariant } from '$lib/format';
import { createDoctorState } from '$lib/state/doctor.svelte';
import { instances } from '$lib/state/instances.svelte';

const doctor = createDoctorState();

$effect(() => {
	void doctor.loadLatest();
	// Instance names give findings context (which Bazarr/Lingarr they refer to).
	if (!instances.loaded) {
		void instances.load();
	}
});

function instanceLabel(bazarrId: string | null, lingarrId: string | null): string | null {
	if (bazarrId !== null) {
		return instances.bazarrName(bazarrId) ?? bazarrId;
	}
	if (lingarrId !== null) {
		return instances.lingarrName(lingarrId) ?? lingarrId;
	}
	return null;
}
</script>

<div class="space-y-4">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<h1 class="text-2xl font-semibold">Doctor</h1>
		<Button disabled={doctor.running} onclick={() => void doctor.run()}>
			{doctor.running ? 'Running…' : 'Run doctor'}
		</Button>
	</div>

	{#if doctor.error}
		<p class="text-sm text-destructive">{doctor.error}</p>
	{/if}

	{#if doctor.latest === null}
		{#if !doctor.loading}
			<Card.Root>
				<Card.Content class="py-8 text-center text-sm text-muted-foreground">
					No doctor run yet. Run it to check your Bazarr/Lingarr configuration for common
					problems.
				</Card.Content>
			</Card.Root>
		{/if}
	{:else}
		<div class="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
			<Badge variant="destructive">critical {doctor.latest.summary?.critical ?? 0}</Badge>
			<Badge variant="secondary">warn {doctor.latest.summary?.warn ?? 0}</Badge>
			<Badge variant="outline">info {doctor.latest.summary?.info ?? 0}</Badge>
			<span>· Finished {formatDateTime(doctor.latest.finishedAt)}</span>
		</div>

		{#if doctor.latest.findings.length === 0}
			<Card.Root>
				<Card.Content class="py-8 text-center text-sm text-muted-foreground">
					No findings — everything looks healthy.
				</Card.Content>
			</Card.Root>
		{/if}

		{#each doctor.grouped as group (group.severity)}
			<section class="space-y-2">
				<h2 class="text-sm font-medium uppercase text-muted-foreground">{group.severity}</h2>
				{#each group.findings as finding (finding.id)}
					{@const label = instanceLabel(finding.bazarrInstanceId, finding.lingarrInstanceId)}
					<Card.Root>
						<Card.Content class="space-y-2 py-4">
							<div class="flex flex-wrap items-center gap-2">
								<Badge variant={severityBadgeVariant(finding.severity)}>{finding.severity}</Badge>
								<Badge variant="outline" class="font-mono text-xs">{finding.checkId}</Badge>
								{#if label}
									<Badge variant="ghost">{label}</Badge>
								{/if}
							</div>
							<p class="text-sm font-medium">{finding.message}</p>
							<details class="text-sm text-muted-foreground">
								<summary class="cursor-pointer select-none">Explanation &amp; fix</summary>
								<div class="mt-2 space-y-2">
									<p>{finding.explanation}</p>
									<p class="text-foreground">{finding.fixGuidance}</p>
								</div>
							</details>
						</Card.Content>
					</Card.Root>
				{/each}
			</section>
		{/each}
	{/if}
</div>
