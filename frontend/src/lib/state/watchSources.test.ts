import { describe, expect, test } from 'bun:test';
import type {
	WatchRefreshResult,
	WatchSourceCreate,
	WatchSourceRead,
	WatchSourceTestResult
} from '$lib/api/types';
import { createWatchSourcesState, type WatchSourcesFetchers } from './watchSources.svelte';

function source(overrides: Partial<WatchSourceRead> = {}): WatchSourceRead {
	return {
		id: 'src-1',
		name: 'Home Plex',
		sourceType: 'plex',
		url: 'http://plex:32400',
		hasCredential: true,
		enabled: true,
		config: { jellyfinUser: null, includeWatchlist: true },
		health: null,
		lastRefreshedAt: null,
		createdAt: '2026-07-03T00:00:00Z',
		...overrides
	};
}

const testResult: WatchSourceTestResult = {
	reachable: true,
	identity: 'HomePlex',
	version: '1.40',
	detail: null
};

const refreshResult: WatchRefreshResult = {
	sourcesPolled: 1,
	sourcesFailed: 0,
	titlesScored: 12
};

function fetchers(overrides: Partial<WatchSourcesFetchers> = {}): WatchSourcesFetchers {
	return {
		list: () => Promise.resolve([source()]),
		create: () => Promise.resolve(source()),
		update: () => Promise.resolve(source({ enabled: false })),
		remove: () => Promise.resolve(),
		test: () => Promise.resolve(testResult),
		checkHealth: () => Promise.resolve(source()),
		refresh: () => Promise.resolve(refreshResult),
		...overrides
	};
}

describe('watch sources state', () => {
	test('load populates sources', async () => {
		const state = createWatchSourcesState(fetchers());
		await state.load();
		expect(state.sources).toHaveLength(1);
		expect(state.sources[0]?.sourceType).toBe('plex');
	});

	test('create posts the body and reloads', async () => {
		const created: WatchSourceCreate[] = [];
		let reloads = 0;
		const state = createWatchSourcesState(
			fetchers({
				list: () => {
					reloads += 1;
					return Promise.resolve([source()]);
				},
				create: (body) => {
					created.push(body);
					return Promise.resolve(source());
				}
			})
		);
		const ok = await state.create({
			name: 'x',
			sourceType: 'tautulli',
			url: 'http://t',
			credential: 'k',
			enabled: true,
			config: { jellyfinUser: null, includeWatchlist: true }
		});
		expect(ok).toBe(true);
		expect(created).toHaveLength(1);
		expect(reloads).toBe(1);
	});

	test('test connection records the probe result', async () => {
		const state = createWatchSourcesState(fetchers());
		await state.test({
			sourceType: 'plex',
			url: 'http://plex',
			credential: 't',
			config: { jellyfinUser: null, includeWatchlist: true }
		});
		expect(state.lastTest?.reachable).toBe(true);
		expect(state.lastTest?.identity).toBe('HomePlex');
	});

	test('refresh records the outcome', async () => {
		const state = createWatchSourcesState(fetchers());
		await state.refresh();
		expect(state.lastRefresh?.titlesScored).toBe(12);
	});

	test('a failed load lands in error state', async () => {
		const state = createWatchSourcesState(
			fetchers({ list: () => Promise.reject(new Error('down')) })
		);
		await state.load();
		expect(state.error).toBe('down');
	});
});
