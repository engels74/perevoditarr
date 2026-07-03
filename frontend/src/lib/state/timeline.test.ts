import { describe, expect, test } from 'bun:test';
import type { PassthroughActionRead, TimelineResponse } from '$lib/api/types';
import {
	createTimelineState,
	type PassthroughAction,
	type TimelineFetchers
} from './timeline.svelte';

function timeline(overrides: Partial<TimelineResponse> = {}): TimelineResponse {
	return {
		intent: {
			id: 'intent-1',
			bazarrInstanceId: 'inst-1',
			mediaType: 'episode',
			externalMediaId: 101,
			sonarrSeriesId: 5,
			season: 1,
			episodeNumber: 2,
			displayTitle: 'The Show',
			sourceLanguage: 'en',
			targetLanguage: 'da',
			forced: false,
			hi: false,
			state: 'converged',
			leaseExpiresAt: null,
			priority: 0,
			bumpedAt: null,
			traceRendered: '',
			createdAt: '2026-07-02T12:00:00Z',
			updatedAt: '2026-07-02T12:00:00Z'
		},
		bazarrHistoryAvailable: true,
		lingarrAvailable: true,
		entries: [
			{
				type: 'intent_event',
				at: '2026-07-02T12:00:00Z',
				actor: 'dispatcher',
				fromState: 'eligible',
				toState: 'dispatched',
				reason: 'dispatched'
			},
			{
				type: 'lingarr_request',
				at: '2026-07-02T12:01:00Z',
				requestId: 42,
				status: 'Pending',
				sourceLanguage: 'en',
				targetLanguage: 'da',
				errorMessage: null,
				completedAt: null,
				active: true
			}
		],
		...overrides
	};
}

function action(overrides: Partial<PassthroughActionRead> = {}): PassthroughActionRead {
	return {
		id: 'pa-1',
		intentId: 'intent-1',
		lingarrRequestId: 42,
		action: 'cancel',
		actor: 'user:admin',
		status: 'ok',
		detail: null,
		createdAt: '2026-07-02T12:02:00Z',
		...overrides
	};
}

function fetchers(overrides: Partial<TimelineFetchers> = {}): TimelineFetchers {
	return {
		timeline: () => Promise.resolve(timeline()),
		passthrough: () => Promise.resolve(action()),
		...overrides
	};
}

describe('timeline state', () => {
	test('loads and exposes stitched entries', async () => {
		const state = createTimelineState(fetchers());
		await state.load('intent-1');
		expect(state.entries).toHaveLength(2);
		expect(state.timeline?.lingarrAvailable).toBe(true);
	});

	test('a pass-through action reloads the timeline', async () => {
		const calls: [number, PassthroughAction][] = [];
		let loads = 0;
		const state = createTimelineState(
			fetchers({
				timeline: () => {
					loads += 1;
					return Promise.resolve(timeline());
				},
				passthrough: (_id, requestId, act) => {
					calls.push([requestId, act]);
					return Promise.resolve(action());
				}
			})
		);
		await state.load('intent-1'); // loads=1
		await state.act(42, 'cancel'); // loads=2
		expect(calls).toEqual([[42, 'cancel']]);
		expect(loads).toBe(2);
		expect(state.lastResult?.status).toBe('ok');
	});

	test('a failed pass-through surfaces the detail as error', async () => {
		const state = createTimelineState(
			fetchers({
				passthrough: () => Promise.resolve(action({ status: 'failed', detail: 'Lingarr said no' }))
			})
		);
		await state.load('intent-1');
		await state.act(42, 'retry');
		expect(state.error).toBe('Lingarr said no');
	});
});
