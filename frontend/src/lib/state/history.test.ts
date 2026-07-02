import { describe, expect, test } from 'bun:test';
import type { IntentsQuery } from '$lib/api/endpoints';
import type { IntentDetail, IntentRead, Page } from '$lib/api/types';
import { createHistoryState } from './history.svelte';

function intent(id: string): IntentRead {
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
		state: 'eligible',
		leaseExpiresAt: null,
		priority: 10,
		bumpedAt: null,
		traceRendered: 'profile *x* → …',
		createdAt: '2026-07-01T00:00:00Z',
		updatedAt: '2026-07-01T00:00:00Z'
	};
}

function api(total: number, seen: IntentsQuery[]) {
	return {
		list(query: IntentsQuery): Promise<Page<IntentRead>> {
			seen.push(query);
			const offset = query.offset ?? 0;
			const limit = query.limit ?? 50;
			const count = Math.max(0, Math.min(limit, total - offset));
			return Promise.resolve({
				items: Array.from({ length: count }, (_, index) => intent(`intent-${offset + index}`)),
				total,
				limit,
				offset
			});
		},
		detail(id: string): Promise<IntentDetail> {
			return Promise.resolve({
				intent: intent(id),
				traceSteps: ['profile *x*', 'missing `da`'],
				events: []
			});
		}
	};
}

describe('history state', () => {
	test('filters reset pagination and pass through as API params', async () => {
		const seen: IntentsQuery[] = [];
		const history = createHistoryState(api(120, seen));
		await history.load();
		await history.next();
		expect(history.offset).toBe(50);

		await history.setFilters({ states: 'superseded', mediaType: 'movie' });
		expect(history.offset).toBe(0);
		const last = seen.at(-1);
		expect(last?.states).toBe('superseded');
		expect(last?.mediaType).toBe('movie');
		// Empty filters are omitted entirely, not sent as empty strings.
		expect(last?.instanceId).toBeUndefined();
		expect(last?.targetLanguage).toBeUndefined();
	});

	test('pagination clamps at both ends', async () => {
		const history = createHistoryState(api(60, []));
		await history.load();
		expect(history.hasPrev).toBe(false);
		await history.next();
		expect(history.offset).toBe(50);
		expect(history.hasNext).toBe(false);
		await history.next();
		expect(history.offset).toBe(50);
	});

	test('open loads the detail drill-in and close clears it', async () => {
		const history = createHistoryState(api(1, []));
		await history.open('intent-9');
		expect(history.selected?.intent.id).toBe('intent-9');
		expect(history.selected?.traceSteps).toHaveLength(2);
		history.close();
		expect(history.selected).toBeNull();
	});
});
