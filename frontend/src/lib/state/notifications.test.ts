import { describe, expect, test } from 'bun:test';
import type { NotificationRouteRead } from '$lib/api/types';
import { createNotificationsState, type NotificationsFetchers } from './notifications.svelte';

function route(id: string, enabled = true): NotificationRouteRead {
	return {
		id,
		name: `route-${id}`,
		enabled,
		events: ['breaker_tripped'],
		urlMasked: 'discord://***',
		createdAt: '2026-07-02T00:00:00Z'
	};
}

function fetchers(overrides: Partial<NotificationsFetchers> = {}): NotificationsFetchers {
	return {
		list: () => Promise.resolve([route('1')]),
		create: () => Promise.resolve(route('2')),
		update: (id) => Promise.resolve(route(id, false)),
		remove: () => Promise.resolve(),
		test: (id) => Promise.resolve({ routeId: id, sent: true, detail: 'delivered' }),
		...overrides
	};
}

describe('notifications state', () => {
	test('loads routes', async () => {
		const state = createNotificationsState(fetchers());
		await state.load();
		expect(state.routes.map((entry) => entry.id)).toEqual(['1']);
	});

	test('create reloads and returns success', async () => {
		let reloads = 0;
		const state = createNotificationsState(
			fetchers({
				list: () => {
					reloads += 1;
					return Promise.resolve([route('1')]);
				}
			})
		);
		const ok = await state.create({
			name: 'ops',
			url: 'discord://x',
			enabled: true,
			events: ['breaker_tripped']
		});
		expect(ok).toBe(true);
		expect(reloads).toBe(1);
	});

	test('test-fire records the result', async () => {
		const state = createNotificationsState(fetchers());
		await state.test('1');
		expect(state.lastTest?.sent).toBe(true);
	});

	test('a failed mutation returns false and sets error', async () => {
		const state = createNotificationsState(
			fetchers({ create: () => Promise.reject(new Error('bad url')) })
		);
		const ok = await state.create({ name: 'ops', url: 'nope', enabled: true, events: [] });
		expect(ok).toBe(false);
		expect(state.error).toBe('bad url');
	});
});
