import { describe, expect, test } from 'bun:test';
import type { StatsOverviewResponse } from '$lib/api/types';
import { createStatsState, type StatsFetchers } from './stats.svelte';

function overview(overrides: Partial<StatsOverviewResponse> = {}): StatsOverviewResponse {
	return {
		generatedAt: '2026-07-02T12:00:00Z',
		since: '2026-06-02',
		until: '2026-07-02',
		bazarrInstanceId: null,
		totals: {
			dispatched: 10,
			converged: 7,
			superseded: 1,
			failed: 2,
			convergedCharacters: 5600,
			meanDurationSeconds: 120,
			failedTransient: 1,
			failedEnvironmental: 0,
			failedProvider: 1,
			failedPoison: 0
		},
		throughput: [
			{ day: '2026-07-01', dispatched: 4, converged: 3, superseded: 0, failed: 1 },
			{ day: '2026-07-02', dispatched: 6, converged: 4, superseded: 1, failed: 1 }
		],
		failureClasses: [
			{ failureClass: 'transient', count: 1, rate: 0.5 },
			{ failureClass: 'provider', count: 1, rate: 0.5 }
		],
		coverage: [
			{
				targetLanguage: 'da',
				total: 7,
				points: [{ day: '2026-07-02', converged: 4, cumulative: 7 }]
			}
		],
		budget: [],
		...overrides
	};
}

function fetchers(overrides: Partial<StatsFetchers> = {}): StatsFetchers {
	return {
		overview: () => Promise.resolve(overview()),
		...overrides
	};
}

describe('stats state', () => {
	test('loads and exposes totals, throughput, failure classes and coverage', async () => {
		const stats = createStatsState(fetchers());
		await stats.load();
		expect(stats.totals?.converged).toBe(7);
		expect(stats.throughput).toHaveLength(2);
		expect(stats.failureClasses.map((f) => f.failureClass)).toEqual(['transient', 'provider']);
		expect(stats.coverage[0]?.total).toBe(7);
	});

	test('setDays refetches with the new window', async () => {
		const seen: number[] = [];
		const stats = createStatsState(
			fetchers({
				overview: (days) => {
					seen.push(days);
					return Promise.resolve(overview());
				}
			})
		);
		await stats.load(); // days=30
		await stats.setDays(7);
		expect(stats.days).toBe(7);
		expect(seen).toEqual([30, 7]);
	});

	test('setInstance refetches scoped to the instance', async () => {
		const seen: (string | null)[] = [];
		const stats = createStatsState(
			fetchers({
				overview: (_days, instanceId) => {
					seen.push(instanceId);
					return Promise.resolve(overview());
				}
			})
		);
		await stats.setInstance('inst-1');
		expect(stats.instanceId).toBe('inst-1');
		expect(seen).toEqual(['inst-1']);
	});

	test('a failure lands in error state', async () => {
		const stats = createStatsState(fetchers({ overview: () => Promise.reject(new Error('boom')) }));
		await stats.load();
		expect(stats.error).toBe('boom');
		expect(stats.totals).toBeNull();
	});
});
