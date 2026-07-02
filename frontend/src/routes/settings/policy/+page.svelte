<script lang="ts">
import CheckIcon from '@lucide/svelte/icons/check';
import CopyIcon from '@lucide/svelte/icons/copy';
import DownloadIcon from '@lucide/svelte/icons/download';
import Trash2Icon from '@lucide/svelte/icons/trash-2';
import UploadIcon from '@lucide/svelte/icons/upload';
import {
	activatePreset,
	createAssignment,
	createExclusion,
	createProfile,
	deleteAssignment,
	deleteExclusion,
	deleteOverride,
	deletePreset,
	deleteProfile,
	exportPolicies,
	forkPreset,
	getProfile,
	importPolicies,
	listAssignments,
	listExclusions,
	listOverrides,
	listPresets,
	listProfiles,
	updateProfile,
	upsertOverride
} from '$lib/api/endpoints';
import type {
	PolicyFindingRead,
	PolicyImportRequest,
	PolicyValuesDto,
	TranslationProfileCreate,
	TranslationProfileRead
} from '$lib/api/types';
import CascadeField from '$lib/components/cascade-field.svelte';
import SettingsNav from '$lib/components/settings-nav.svelte';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import * as Dialog from '$lib/components/ui/dialog';
import { Input } from '$lib/components/ui/input';
import { Label } from '$lib/components/ui/label';
import {
	inheritedResolution,
	POLICY_FIELDS,
	severityBadgeVariant,
	sortFindings
} from '$lib/policy-display';
import { createPolicyState } from '$lib/state/policy.svelte';

const policy = createPolicyState({
	listPresets,
	activatePreset,
	forkPreset,
	deletePreset,
	listProfiles,
	getProfile,
	createProfile,
	updateProfile,
	deleteProfile,
	listAssignments: () => listAssignments(),
	createAssignment,
	deleteAssignment,
	listExclusions: () => listExclusions(),
	createExclusion,
	deleteExclusion,
	listOverrides: () => listOverrides(),
	upsertOverride,
	deleteOverride,
	exportPolicies,
	importPolicies: (payload) => importPolicies(payload as PolicyImportRequest)
});

$effect(() => {
	void policy.load();
});

// --- profile editor dialog state ---------------------------------------------
let editorOpen = $state(false);
let editingId = $state<string | null>(null);
let editorName = $state('');
let editorDescription = $state('');
let editorValues = $state<PolicyValuesDto>({});
let editorFindings = $state<PolicyFindingRead[]>([]);
let saving = $state(false);

async function openEditor(entry: TranslationProfileRead | null): Promise<void> {
	editingId = entry?.id ?? null;
	editorName = entry?.name ?? '';
	editorDescription = entry?.description ?? '';
	editorValues = { ...(entry?.values ?? {}) };
	editorFindings = [];
	editorOpen = true;
	if (entry) {
		// Findings aren't part of the flat profile list — fetch the wrapped
		// editor response on demand so inline validation still shows.
		const detail = await policy.profileEditor(entry.id);
		if (detail && editingId === entry.id) {
			editorFindings = sortFindings(detail.findings);
		}
	}
}

async function saveEditor(): Promise<void> {
	saving = true;
	const payload: TranslationProfileCreate = {
		name: editorName,
		description: editorDescription || null,
		values: editorValues
	};
	const saved = await policy.saveProfile(editingId, payload);
	saving = false;
	if (saved) {
		// Keep the dialog open on validation findings so the user sees them
		// inline; close on a clean save.
		editingId = saved.profile.id;
		editorFindings = sortFindings(saved.findings);
		if (saved.findings.length === 0) {
			editorOpen = false;
		}
	}
}

// --- fork dialog ---------------------------------------------------------------
let forkSource = $state<{ id: string; name: string } | null>(null);
let forkName = $state('');

async function submitFork(): Promise<void> {
	if (forkSource) {
		await policy.fork(forkSource.id, forkName);
		forkSource = null;
	}
}

// --- import/export ---------------------------------------------------------------
let importInput = $state<HTMLInputElement | null>(null);

async function downloadExport(): Promise<void> {
	const payload = await policy.exportAll();
	if (payload === null) {
		return;
	}
	const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
	const url = URL.createObjectURL(blob);
	const anchor = document.createElement('a');
	anchor.href = url;
	anchor.download = 'perevoditarr-policies.json';
	anchor.click();
	URL.revokeObjectURL(url);
}

async function onImportFile(event: Event): Promise<void> {
	const input = event.currentTarget as HTMLInputElement;
	const file = input.files?.[0];
	if (!file) {
		return;
	}
	try {
		const parsed: unknown = JSON.parse(await file.text());
		await policy.importAll(parsed);
	} catch {
		// Non-JSON file: surface through the shared error channel.
		await policy.importAll({});
	} finally {
		input.value = '';
	}
}
</script>

<div class="space-y-4">
	<h1 class="text-2xl font-semibold">Settings</h1>
	<SettingsNav />

	{#if policy.error}
		<p class="text-sm text-destructive">{policy.error}</p>
	{/if}

	<section class="space-y-2">
		<div class="flex items-center justify-between">
			<h2 class="text-lg font-medium">Presets</h2>
			<div class="flex gap-2">
				<Button variant="outline" size="sm" onclick={() => void downloadExport()}>
					<DownloadIcon class="size-4" />
					Export
				</Button>
				<Button variant="outline" size="sm" onclick={() => importInput?.click()}>
					<UploadIcon class="size-4" />
					Import
				</Button>
				<input
					bind:this={importInput}
					type="file"
					accept="application/json"
					class="hidden"
					onchange={(event) => void onImportFile(event)}
				/>
			</div>
		</div>

		{#if policy.importResult}
			<p class="text-sm text-muted-foreground">
				Imported {policy.importResult.createdPresets.length} presets and
				{policy.importResult.createdProfiles.length} profiles.
				{#if policy.importResult.skipped.length > 0}
					Skipped (name already exists): {policy.importResult.skipped.join(', ')}.
				{/if}
			</p>
		{/if}

		<div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
			{#each policy.presets as preset (preset.id)}
				<Card.Root class={preset.active ? 'border-primary' : ''}>
					<Card.Header class="pb-2">
						<Card.Title class="flex items-center justify-between text-base">
							{preset.name}
							{#if preset.active}
								<Badge>active</Badge>
							{:else if preset.builtIn}
								<Badge variant="outline">built-in</Badge>
							{/if}
						</Card.Title>
						{#if preset.description}
							<Card.Description>{preset.description}</Card.Description>
						{/if}
					</Card.Header>
					<Card.Content class="space-y-1 text-sm text-muted-foreground">
						<p class="font-mono text-xs">
							{preset.values.dryRun === false ? 'live' : 'dry-run'}
							{#if preset.rails.dispatchWindowK}
								· K={preset.rails.dispatchWindowK}
							{/if}
							{#if preset.rails.dailyCap}
								· {preset.rails.dailyCap}/day
							{/if}
						</p>
					</Card.Content>
					<Card.Footer class="flex gap-2">
						{#if !preset.active}
							<Button size="sm" variant="outline" onclick={() => void policy.activate(preset.id)}>
								<CheckIcon class="size-4" />
								Activate
							</Button>
						{/if}
						<Button
							size="sm"
							variant="ghost"
							onclick={() => {
								forkSource = { id: preset.id, name: preset.name };
								forkName = `${preset.name} (fork)`;
							}}
						>
							<CopyIcon class="size-4" />
							Fork
						</Button>
						{#if !preset.builtIn && !preset.active}
							<Button
								size="sm"
								variant="ghost"
								class="text-destructive"
								onclick={() => void policy.removePreset(preset.id)}
							>
								<Trash2Icon class="size-4" />
							</Button>
						{/if}
					</Card.Footer>
				</Card.Root>
			{/each}
		</div>
	</section>

	<section class="space-y-2">
		<div class="flex items-center justify-between">
			<h2 class="text-lg font-medium">Translation profiles</h2>
			<Button size="sm" onclick={() => void openEditor(null)}>New profile</Button>
		</div>
		<div class="grid gap-3 md:grid-cols-2">
			{#each policy.profiles as entry (entry.id)}
				<Card.Root>
					<Card.Header class="pb-2">
						<Card.Title class="text-base">
							{entry.name}
						</Card.Title>
						{#if entry.description}
							<Card.Description>{entry.description}</Card.Description>
						{/if}
					</Card.Header>
					<Card.Content class="text-sm text-muted-foreground">
						<p class="font-mono text-xs">
							targets: {(entry.values.targetLanguages ?? []).join(', ') || 'inherited'}
							· {entry.assignmentCount} assignment{entry.assignmentCount === 1 ? '' : 's'}
						</p>
					</Card.Content>
					<Card.Footer class="flex gap-2">
						<Button size="sm" variant="outline" onclick={() => void openEditor(entry)}>Edit</Button>
						<Button
							size="sm"
							variant="ghost"
							class="text-destructive"
							onclick={() => void policy.removeProfile(entry.id)}
						>
							<Trash2Icon class="size-4" />
						</Button>
					</Card.Footer>
				</Card.Root>
			{:else}
				<p class="text-sm text-muted-foreground">
					No profiles yet. Profiles bundle the what and how of translation for the media they
					are assigned to.
				</p>
			{/each}
		</div>
	</section>

	<section class="space-y-2">
		<h2 class="text-lg font-medium">Assignments & exclusions</h2>
		<div class="grid gap-3 md:grid-cols-2">
			<Card.Root>
				<Card.Header class="pb-2">
					<Card.Title class="text-base">Profile assignments</Card.Title>
					<Card.Description>Assigned from the library browser</Card.Description>
				</Card.Header>
				<Card.Content class="space-y-1">
					{#each policy.assignments as assignment (assignment.id)}
						<div class="flex items-center justify-between text-sm">
							<span class="font-mono text-xs">
								{assignment.scopeType}:{assignment.scopeKey} → {assignment.profileName}
							</span>
							<Button
								size="sm"
								variant="ghost"
								class="text-destructive"
								aria-label="Remove assignment"
								onclick={() => void policy.unassign(assignment.id)}
							>
								<Trash2Icon class="size-4" />
							</Button>
						</div>
					{:else}
						<p class="text-sm text-muted-foreground">No assignments yet.</p>
					{/each}
				</Card.Content>
			</Card.Root>
			<Card.Root>
				<Card.Header class="pb-2">
					<Card.Title class="text-base">Exclusions</Card.Title>
					<Card.Description>"Never translate" rules</Card.Description>
				</Card.Header>
				<Card.Content class="space-y-1">
					{#each policy.exclusions as exclusion (exclusion.id)}
						<div class="flex items-center justify-between text-sm">
							<span class="font-mono text-xs">
								{exclusion.kind}:{exclusion.ruleKey}
								{#if exclusion.note}
									<span class="text-muted-foreground">— {exclusion.note}</span>
								{/if}
							</span>
							<Button
								size="sm"
								variant="ghost"
								class="text-destructive"
								aria-label="Remove exclusion"
								onclick={() => void policy.removeExclusion(exclusion.id)}
							>
								<Trash2Icon class="size-4" />
							</Button>
						</div>
					{:else}
						<p class="text-sm text-muted-foreground">No exclusions yet.</p>
					{/each}
				</Card.Content>
			</Card.Root>
		</div>
	</section>
</div>

<Dialog.Root bind:open={editorOpen}>
	<Dialog.Content class="max-h-[85vh] max-w-2xl overflow-y-auto">
		<Dialog.Header>
			<Dialog.Title>{editingId === null ? 'New profile' : 'Edit profile'}</Dialog.Title>
			<Dialog.Description>
				Unset values inherit through the cascade — global defaults, then the active preset.
			</Dialog.Description>
		</Dialog.Header>

		<div class="space-y-3">
			<div class="grid gap-2">
				<Label for="profile-name">Name</Label>
				<Input id="profile-name" bind:value={editorName} placeholder="Anime" />
			</div>
			<div class="grid gap-2">
				<Label for="profile-description">Description</Label>
				<Input
					id="profile-description"
					bind:value={editorDescription}
					placeholder="Japanese-timed sources first"
				/>
			</div>

			<div>
				{#each POLICY_FIELDS as spec (spec.key)}
					<CascadeField
						{spec}
						values={editorValues}
						inherited={inheritedResolution(
							spec.key as Parameters<typeof inheritedResolution>[0],
							policy.activePreset
						)}
						onValuesChange={(next) => {
							editorValues = next;
						}}
					/>
				{/each}
			</div>

			{#if editorFindings.length > 0}
				<div class="space-y-1 rounded-md border p-3">
					<p class="text-sm font-medium">Validation</p>
					{#each editorFindings as finding (finding.code + (finding.instanceName ?? ''))}
						<div class="flex items-start gap-2 text-sm">
							<Badge variant={severityBadgeVariant(finding.severity)}>{finding.severity}</Badge>
							<div>
								<p>{finding.message}</p>
								<p class="text-xs text-muted-foreground">{finding.fixGuidance}</p>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<Dialog.Footer>
			<Button variant="outline" onclick={() => (editorOpen = false)}>Cancel</Button>
			<Button disabled={saving || editorName.trim() === ''} onclick={() => void saveEditor()}>
				{saving ? 'Saving…' : 'Save profile'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

<Dialog.Root
	open={forkSource !== null}
	onOpenChange={(open) => {
		if (!open) {
			forkSource = null;
		}
	}}
>
	<Dialog.Content class="max-w-md">
		<Dialog.Header>
			<Dialog.Title>Fork {forkSource?.name}</Dialog.Title>
			<Dialog.Description>Creates an editable copy of this preset.</Dialog.Description>
		</Dialog.Header>
		<div class="grid gap-2">
			<Label for="fork-name">New preset name</Label>
			<Input id="fork-name" bind:value={forkName} />
		</div>
		<Dialog.Footer>
			<Button variant="outline" onclick={() => (forkSource = null)}>Cancel</Button>
			<Button disabled={forkName.trim() === ''} onclick={() => void submitFork()}>Fork</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
