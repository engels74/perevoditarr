// Policy settings state (P2-T6): presets, profiles (with inline findings),
// assignments, exclusions, overrides. One instance per page; all fetchers
// injectable for tests.

import type {
	ExclusionCreate,
	ExclusionRead,
	OverrideRead,
	OverrideUpsert,
	PolicyImportResult,
	PresetRead,
	ProfileAssignmentCreate,
	ProfileAssignmentRead,
	ProfileEditorResponse,
	TranslationProfileCreate,
	TranslationProfileUpdate
} from '$lib/api/types';

export interface PolicyApi {
	listPresets(): Promise<PresetRead[]>;
	activatePreset(id: string): Promise<PresetRead>;
	forkPreset(id: string, name: string): Promise<PresetRead>;
	deletePreset(id: string): Promise<void>;
	listProfiles(): Promise<ProfileEditorResponse[]>;
	createProfile(input: TranslationProfileCreate): Promise<ProfileEditorResponse>;
	updateProfile(id: string, patch: TranslationProfileUpdate): Promise<ProfileEditorResponse>;
	deleteProfile(id: string): Promise<void>;
	listAssignments(): Promise<ProfileAssignmentRead[]>;
	createAssignment(input: ProfileAssignmentCreate): Promise<ProfileAssignmentRead>;
	deleteAssignment(id: string): Promise<void>;
	listExclusions(): Promise<ExclusionRead[]>;
	createExclusion(input: ExclusionCreate): Promise<ExclusionRead>;
	deleteExclusion(id: string): Promise<void>;
	listOverrides(): Promise<OverrideRead[]>;
	upsertOverride(input: OverrideUpsert): Promise<OverrideRead>;
	deleteOverride(id: string): Promise<void>;
	exportPolicies(): Promise<unknown>;
	importPolicies(input: unknown): Promise<PolicyImportResult>;
}

export function createPolicyState(api: PolicyApi) {
	let presets = $state<PresetRead[]>([]);
	let profiles = $state<ProfileEditorResponse[]>([]);
	let assignments = $state<ProfileAssignmentRead[]>([]);
	let exclusions = $state<ExclusionRead[]>([]);
	let overrides = $state<OverrideRead[]>([]);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let importResult = $state<PolicyImportResult | null>(null);

	const activePreset = $derived(presets.find((preset) => preset.active) ?? null);

	function capture(cause: unknown): void {
		error = cause instanceof Error ? cause.message : String(cause);
	}

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			[presets, profiles, assignments, exclusions, overrides] = await Promise.all([
				api.listPresets(),
				api.listProfiles(),
				api.listAssignments(),
				api.listExclusions(),
				api.listOverrides()
			]);
		} catch (cause) {
			capture(cause);
		} finally {
			loading = false;
		}
	}

	async function activate(id: string): Promise<void> {
		error = null;
		try {
			await api.activatePreset(id);
			presets = await api.listPresets();
		} catch (cause) {
			capture(cause);
		}
	}

	async function fork(id: string, name: string): Promise<void> {
		error = null;
		try {
			await api.forkPreset(id, name);
			presets = await api.listPresets();
		} catch (cause) {
			capture(cause);
		}
	}

	async function removePreset(id: string): Promise<void> {
		error = null;
		try {
			await api.deletePreset(id);
			presets = await api.listPresets();
		} catch (cause) {
			capture(cause);
		}
	}

	async function saveProfile(
		id: string | null,
		input: TranslationProfileCreate
	): Promise<ProfileEditorResponse | null> {
		error = null;
		try {
			const saved =
				id === null
					? await api.createProfile(input)
					: await api.updateProfile(id, {
							name: input.name,
							description: input.description,
							values: input.values ?? undefined
						});
			profiles = await api.listProfiles();
			return saved;
		} catch (cause) {
			capture(cause);
			return null;
		}
	}

	async function removeProfile(id: string): Promise<void> {
		error = null;
		try {
			await api.deleteProfile(id);
			[profiles, assignments] = await Promise.all([api.listProfiles(), api.listAssignments()]);
		} catch (cause) {
			capture(cause);
		}
	}

	async function assign(input: ProfileAssignmentCreate): Promise<void> {
		error = null;
		try {
			await api.createAssignment(input);
			assignments = await api.listAssignments();
		} catch (cause) {
			capture(cause);
		}
	}

	async function unassign(id: string): Promise<void> {
		error = null;
		try {
			await api.deleteAssignment(id);
			assignments = await api.listAssignments();
		} catch (cause) {
			capture(cause);
		}
	}

	async function exclude(input: ExclusionCreate): Promise<void> {
		error = null;
		try {
			await api.createExclusion(input);
			exclusions = await api.listExclusions();
		} catch (cause) {
			capture(cause);
		}
	}

	async function removeExclusion(id: string): Promise<void> {
		error = null;
		try {
			await api.deleteExclusion(id);
			exclusions = await api.listExclusions();
		} catch (cause) {
			capture(cause);
		}
	}

	async function setOverride(input: OverrideUpsert): Promise<void> {
		error = null;
		try {
			await api.upsertOverride(input);
			overrides = await api.listOverrides();
		} catch (cause) {
			capture(cause);
		}
	}

	async function removeOverride(id: string): Promise<void> {
		error = null;
		try {
			await api.deleteOverride(id);
			overrides = await api.listOverrides();
		} catch (cause) {
			capture(cause);
		}
	}

	async function exportAll(): Promise<unknown | null> {
		error = null;
		try {
			return await api.exportPolicies();
		} catch (cause) {
			capture(cause);
			return null;
		}
	}

	async function importAll(payload: unknown): Promise<void> {
		error = null;
		importResult = null;
		try {
			importResult = await api.importPolicies(payload);
			await load();
		} catch (cause) {
			capture(cause);
		}
	}

	return {
		get presets() {
			return presets;
		},
		get profiles() {
			return profiles;
		},
		get assignments() {
			return assignments;
		},
		get exclusions() {
			return exclusions;
		},
		get overrides() {
			return overrides;
		},
		get activePreset() {
			return activePreset;
		},
		get loading() {
			return loading;
		},
		get error() {
			return error;
		},
		get importResult() {
			return importResult;
		},
		load,
		activate,
		fork,
		removePreset,
		saveProfile,
		removeProfile,
		assign,
		unassign,
		exclude,
		removeExclusion,
		setOverride,
		removeOverride,
		exportAll,
		importAll
	};
}

export type PolicyState = ReturnType<typeof createPolicyState>;
