import { describe, expect, test } from 'bun:test';
import type { PlanItemDto, PlanPreviewResponse } from '$lib/api/types';
import { createPlanState } from './plan.svelte';

function item(id: string, verdict: PlanItemDto['verdict']): PlanItemDto {
	return {
		intentId: id,
		bazarrInstanceId: 'instance-1',
		mediaType: 'episode',
		externalMediaId: 1,
		sonarrSeriesId: 11,
		displayTitle: 'Alpha Show',
		season: 1,
		episodeNumber: 1,
		sourceLanguage: 'en',
		targetLanguage: 'da',
		forced: false,
		hi: false,
		priority: 10,
		bumped: false,
		profileName: null,
		scoreComponents: null,
		estimate: { lines: 800, characters: 36000, basis: 'heuristic' },
		verdict
	};
}

function response(items: PlanItemDto[]): PlanPreviewResponse {
	return {
		generatedAt: '2026-07-02T00:00:00Z',
		dryRun: true,
		activePreset: 'Observe',
		rails: {},
		limit: 25,
		candidateWindow: 500,
		items,
		totals: {
			evaluated: items.length,
			included: items.filter((entry) => entry.verdict.type === 'included').length,
			held: items.filter((entry) => entry.verdict.type === 'held').length,
			estimatedLines: 0,
			estimatedCharacters: 0
		},
		groups: []
	};
}

describe('plan state', () => {
	test('splits items into included and held', async () => {
		const plan = createPlanState(() =>
			Promise.resolve(
				response([
					item('a', { type: 'included', position: 1 }),
					item('b', { type: 'held', rail: 'invariant', detail: '§6.5' }),
					item('c', { type: 'included', position: 2 })
				])
			)
		);
		await plan.load();
		expect(plan.included.map((entry) => entry.intentId)).toEqual(['a', 'c']);
		expect(plan.held.map((entry) => entry.intentId)).toEqual(['b']);
	});

	test('setInstance forwards the filter and reloads', async () => {
		const seen: (string | undefined)[] = [];
		const plan = createPlanState((query) => {
			seen.push(query.instanceId);
			return Promise.resolve(response([]));
		});
		await plan.load();
		await plan.setInstance('instance-2');
		await plan.setInstance('');
		expect(seen).toEqual([undefined, 'instance-2', undefined]);
	});

	test('a fetch failure lands in error state', async () => {
		const plan = createPlanState(() => Promise.reject(new Error('nope')));
		await plan.load();
		expect(plan.error).toBe('nope');
		expect(plan.plan).toBeNull();
		expect(plan.loading).toBe(false);
	});
});
