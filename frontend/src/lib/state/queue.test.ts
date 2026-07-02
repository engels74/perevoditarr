import { describe, expect, test } from 'bun:test';
import type { IntentRead, Page } from '$lib/api/types';
import { createQueueState, type QueueFetchers } from './queue.svelte';

function intent(id: string, state: string): IntentRead {
	return {
		id,
		bazarrInstanceId: 'instance-1',
		mediaType: 'episode',
		externalMediaId: 1,
		sonarrSeriesId: 11,
		season: 1,
		episodeNumber: 1,
		displayTitle: 'Alpha Show',
		sourceLanguage: 'en',
		targetLanguage: 'da',
		forced: false,
		hi: false,
		state,
		leaseExpiresAt: null,
		priority: 10,
		bumpedAt: null,
		traceRendered: '',
		createdAt: '2026-07-02T00:00:00Z',
		updatedAt: '2026-07-02T00:00:00Z'
	};
}

function page(items: IntentRead[]): Page<IntentRead> {
	return { items, total: items.length, limit: 50, offset: 0 };
}

function fetchers(overrides: Partial<QueueFetchers> = {}): QueueFetchers {
	return {
		backlog: () => Promise.resolve(page([intent('b1', 'eligible')])),
		inFlight: () => Promise.resolve(page([intent('f1', 'dispatched')])),
		needsAttention: () => Promise.resolve(page([intent('n1', 'failed')])),
		quarantine: () => Promise.resolve(page([intent('q1', 'quarantined')])),
		retry: (id) => Promise.resolve(intent(id, 'eligible')),
		release: (id) => Promise.resolve(intent(id, 'superseded')),
		exclude: (id) => Promise.resolve(intent(id, 'superseded')),
		...overrides
	};
}

describe('queue state', () => {
	test('loads the active tab and switches tabs', async () => {
		const queue = createQueueState(fetchers());
		await queue.load();
		expect(queue.items.map((entry) => entry.id)).toEqual(['b1']);
		await queue.setTab('quarantine');
		expect(queue.tab).toBe('quarantine');
		expect(queue.items.map((entry) => entry.id)).toEqual(['q1']);
	});

	test('setInstance forwards the filter to the active loader', async () => {
		const seen: (string | undefined)[] = [];
		const queue = createQueueState(
			fetchers({
				backlog: (query) => {
					seen.push(query.instanceId);
					return Promise.resolve(page([]));
				}
			})
		);
		await queue.load();
		await queue.setInstance('instance-2');
		expect(seen).toEqual([undefined, 'instance-2']);
	});

	test('retry runs the action then reloads the tab', async () => {
		const retried: string[] = [];
		let reloads = 0;
		const queue = createQueueState(
			fetchers({
				quarantine: () => {
					reloads += 1;
					return Promise.resolve(page([intent('q1', 'quarantined')]));
				},
				retry: (id) => {
					retried.push(id);
					return Promise.resolve(intent(id, 'eligible'));
				}
			})
		);
		await queue.setTab('quarantine'); // reloads=1
		await queue.retry('q1'); // reloads=2
		expect(retried).toEqual(['q1']);
		expect(reloads).toBe(2);
	});

	test('a fetch failure lands in error state', async () => {
		const queue = createQueueState(fetchers({ backlog: () => Promise.reject(new Error('boom')) }));
		await queue.load();
		expect(queue.error).toBe('boom');
		expect(queue.loading).toBe(false);
	});
});
