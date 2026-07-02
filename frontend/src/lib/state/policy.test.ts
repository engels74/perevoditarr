import { describe, expect, test } from 'bun:test';
import type {
	ExclusionRead,
	OverrideRead,
	PresetRead,
	ProfileAssignmentRead,
	TranslationProfileRead
} from '$lib/api/types';
import { createPolicyState, type PolicyApi } from './policy.svelte';

function preset(id: string, active: boolean): PresetRead {
	return {
		id,
		name: id,
		description: null,
		builtIn: true,
		active,
		values: { dryRun: true },
		rails: {},
		createdAt: '2026-07-01T00:00:00Z',
		updatedAt: '2026-07-01T00:00:00Z'
	};
}

function makeApi(calls: string[]): PolicyApi {
	let presets = [preset('observe', true), preset('balanced', false)];
	const none = <T>(value: T) => Promise.resolve(value);
	return {
		listPresets: () => {
			calls.push('listPresets');
			return none([...presets]);
		},
		activatePreset: (id) => {
			calls.push(`activate:${id}`);
			presets = presets.map((entry) => ({ ...entry, active: entry.id === id }));
			return none(presets.find((entry) => entry.id === id) as PresetRead);
		},
		forkPreset: (id, name) => {
			calls.push(`fork:${id}:${name}`);
			const copy = { ...preset(name, false), builtIn: false };
			presets = [...presets, copy];
			return none(copy);
		},
		deletePreset: (id) => {
			calls.push(`deletePreset:${id}`);
			presets = presets.filter((entry) => entry.id !== id);
			return none(undefined);
		},
		listProfiles: () => none<TranslationProfileRead[]>([]),
		getProfile: () => Promise.reject(new Error('unused')),
		createProfile: () => Promise.reject(new Error('unused')),
		updateProfile: () => Promise.reject(new Error('unused')),
		deleteProfile: () => none(undefined),
		listAssignments: () => none<ProfileAssignmentRead[]>([]),
		createAssignment: () => Promise.reject(new Error('unused')),
		deleteAssignment: () => none(undefined),
		listExclusions: () => none<ExclusionRead[]>([]),
		createExclusion: () => Promise.reject(new Error('unused')),
		deleteExclusion: () => none(undefined),
		listOverrides: () => none<OverrideRead[]>([]),
		upsertOverride: () => Promise.reject(new Error('unused')),
		deleteOverride: () => none(undefined),
		exportPolicies: () => none({ schemaVersion: 1, presets: [], profiles: [] }),
		importPolicies: () => none({ createdPresets: ['x'], createdProfiles: [], skipped: ['dupe'] })
	};
}

describe('policy state', () => {
	test('load populates all sections and derives the active preset', async () => {
		const policy = createPolicyState(makeApi([]));
		await policy.load();
		expect(policy.presets).toHaveLength(2);
		expect(policy.activePreset?.id).toBe('observe');
		expect(policy.loading).toBe(false);
		expect(policy.error).toBeNull();
	});

	test('activate refreshes the preset list and moves the active flag', async () => {
		const policy = createPolicyState(makeApi([]));
		await policy.load();
		await policy.activate('balanced');
		expect(policy.activePreset?.id).toBe('balanced');
	});

	test('fork adds an editable copy', async () => {
		const calls: string[] = [];
		const policy = createPolicyState(makeApi(calls));
		await policy.load();
		await policy.fork('balanced', 'Balanced (fork)');
		expect(calls).toContain('fork:balanced:Balanced (fork)');
		expect(policy.presets.map((entry) => entry.id)).toContain('Balanced (fork)');
	});

	test('import stores the result report and reloads', async () => {
		const policy = createPolicyState(makeApi([]));
		await policy.importAll({ schemaVersion: 1 });
		expect(policy.importResult?.createdPresets).toEqual(['x']);
		expect(policy.importResult?.skipped).toEqual(['dupe']);
	});

	test('failures land in the shared error channel', async () => {
		const api = makeApi([]);
		api.listPresets = () => Promise.reject(new Error('down'));
		const policy = createPolicyState(api);
		await policy.load();
		expect(policy.error).toBe('down');
	});
});
