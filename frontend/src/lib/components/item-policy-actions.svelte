<script lang="ts">
// Per-item policy actions (FR-U4): effective-policy inspector, profile
// assignment, and "never translate" exclusion — series or movie scope.

import EllipsisIcon from '@lucide/svelte/icons/ellipsis';
import {
	createAssignment,
	createExclusion,
	type EffectivePolicyQuery,
	listProfiles
} from '$lib/api/endpoints';
import type { ProfileEditorResponse } from '$lib/api/types';
import EffectivePolicyDialog from '$lib/components/effective-policy-dialog.svelte';
import { Button } from '$lib/components/ui/button';
import * as Dialog from '$lib/components/ui/dialog';
import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
import { Label } from '$lib/components/ui/label';

interface Props {
	instanceId: string;
	mediaType: 'series' | 'movie';
	/** sonarr_series_id for series, radarr_id for movies. */
	externalId: number;
	title: string;
	monitored: boolean;
	onChanged?: () => void;
}

let { instanceId, mediaType, externalId, title, monitored, onChanged }: Props = $props();

let inspectorOpen = $state(false);
let assignOpen = $state(false);
let profiles = $state<ProfileEditorResponse[]>([]);
let selectedProfileId = $state('');
let busy = $state(false);
let error = $state<string | null>(null);

const effectiveQuery = $derived<EffectivePolicyQuery>({
	instanceId,
	mediaType,
	sonarrSeriesId: mediaType === 'series' ? externalId : undefined,
	radarrId: mediaType === 'movie' ? externalId : undefined,
	monitored
});

async function openAssign(): Promise<void> {
	error = null;
	assignOpen = true;
	profiles = await listProfiles();
	selectedProfileId = profiles[0]?.profile.id ?? '';
}

async function submitAssign(): Promise<void> {
	busy = true;
	error = null;
	try {
		await createAssignment({
			profileId: selectedProfileId,
			bazarrInstanceId: instanceId,
			scopeType: mediaType,
			scopeKey: String(externalId)
		});
		assignOpen = false;
		onChanged?.();
	} catch (cause) {
		error = cause instanceof Error ? cause.message : String(cause);
	} finally {
		busy = false;
	}
}

async function exclude(): Promise<void> {
	error = null;
	try {
		await createExclusion({
			bazarrInstanceId: instanceId,
			kind: mediaType,
			ruleKey: String(externalId),
			note: title
		});
		onChanged?.();
	} catch (cause) {
		error = cause instanceof Error ? cause.message : String(cause);
	}
}
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger>
		{#snippet child({ props })}
			<Button {...props} variant="ghost" size="icon" aria-label="Policy actions for {title}">
				<EllipsisIcon class="size-4" />
			</Button>
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content align="end">
		<DropdownMenu.Item onclick={() => (inspectorOpen = true)}>
			Effective policy
		</DropdownMenu.Item>
		<DropdownMenu.Item onclick={() => void openAssign()}>Assign profile…</DropdownMenu.Item>
		<DropdownMenu.Separator />
		<DropdownMenu.Item class="text-destructive" onclick={() => void exclude()}>
			Never translate
		</DropdownMenu.Item>
	</DropdownMenu.Content>
</DropdownMenu.Root>

{#if error}
	<p class="text-xs text-destructive">{error}</p>
{/if}

<EffectivePolicyDialog
	open={inspectorOpen}
	{title}
	query={effectiveQuery}
	onClose={() => (inspectorOpen = false)}
/>

<Dialog.Root
	open={assignOpen}
	onOpenChange={(next) => {
		if (!next) {
			assignOpen = false;
		}
	}}
>
	<Dialog.Content class="max-w-md">
		<Dialog.Header>
			<Dialog.Title>Assign profile</Dialog.Title>
			<Dialog.Description>{title}</Dialog.Description>
		</Dialog.Header>
		{#if profiles.length === 0}
			<p class="text-sm text-muted-foreground">
				No translation profiles yet — create one under Settings → Policy.
			</p>
		{:else}
			<div class="grid gap-2">
				<Label for="assign-profile">Profile</Label>
				<select
					id="assign-profile"
					class="h-9 rounded-md border border-input bg-background px-2 text-sm"
					bind:value={selectedProfileId}
				>
					{#each profiles as entry (entry.profile.id)}
						<option value={entry.profile.id}>{entry.profile.name}</option>
					{/each}
				</select>
			</div>
		{/if}
		{#if error}
			<p class="text-sm text-destructive">{error}</p>
		{/if}
		<Dialog.Footer>
			<Button variant="outline" onclick={() => (assignOpen = false)}>Cancel</Button>
			<Button
				disabled={busy || selectedProfileId === ''}
				onclick={() => void submitAssign()}
			>
				Assign
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
