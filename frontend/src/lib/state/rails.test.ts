import { describe, expect, test } from 'bun:test';
import type { RailStatusDto, RailsOverview } from '$lib/api/types';
import { createRailsState, type RailsFetchers } from './rails.svelte';

function status(overrides: Partial<RailStatusDto> = {}): RailStatusDto {
	return {
		scope: 'instance',
		bazarrInstanceId: 'instance-1',
		instanceName: 'main',
		dispatchActive: false,
		paused: false,
		pausedReason: null,
		dispatchWindowK: 2,
		windowOpen: true,
		windows: [],
		breaker: {
			state: 'closed',
			consecutiveFailures: 0,
			openedAt: null,
			lastProbeAt: null,
			probeDueAt: null
		},
		caps: [],
		budget: null,
		...overrides
	};
}

function overview(instances: RailStatusDto[]): RailsOverview {
	return {
		generatedAt: '2026-07-02T00:00:00Z',
		globalRails: status({
			scope: 'global',
			bazarrInstanceId: null,
			instanceName: null,
			breaker: null
		}),
		instances
	};
}

function fetchers(overrides: Partial<RailsFetchers> = {}): RailsFetchers {
	return {
		overview: () => Promise.resolve(overview([status()])),
		pauseGlobal: () => Promise.resolve(status({ paused: true })),
		resumeGlobal: () => Promise.resolve(status()),
		pauseInstance: () => Promise.resolve(status({ paused: true })),
		resumeInstance: () => Promise.resolve(status()),
		activate: () => Promise.resolve(status({ dispatchActive: true })),
		deactivate: () => Promise.resolve(status()),
		...overrides
	};
}

describe('rails state', () => {
	test('exposes global rails and instances', async () => {
		const rails = createRailsState(fetchers());
		await rails.load();
		expect(rails.globalRails?.scope).toBe('global');
		expect(rails.instances).toHaveLength(1);
		expect(rails.anyBreakerOpen).toBe(false);
	});

	test('detects an open breaker across instances', async () => {
		const rails = createRailsState(
			fetchers({
				overview: () =>
					Promise.resolve(
						overview([
							status({
								breaker: {
									state: 'open',
									consecutiveFailures: 5,
									openedAt: null,
									lastProbeAt: null,
									probeDueAt: null
								}
							})
						])
					)
			})
		);
		await rails.load();
		expect(rails.anyBreakerOpen).toBe(true);
	});

	test('activate calls the endpoint and reloads', async () => {
		const activated: string[] = [];
		let reloads = 0;
		const rails = createRailsState(
			fetchers({
				overview: () => {
					reloads += 1;
					return Promise.resolve(overview([status()]));
				},
				activate: (id) => {
					activated.push(id);
					return Promise.resolve(status({ dispatchActive: true }));
				}
			})
		);
		await rails.load(); // reloads=1
		await rails.activate('instance-1'); // reloads=2
		expect(activated).toEqual(['instance-1']);
		expect(reloads).toBe(2);
	});

	test('a failure lands in error state', async () => {
		const rails = createRailsState(fetchers({ overview: () => Promise.reject(new Error('down')) }));
		await rails.load();
		expect(rails.error).toBe('down');
	});
});
