import { describe, expect, test } from 'bun:test';
import type { UserCreateRequest, UserRead } from '$lib/api/types';
import { createUsersState, type UsersFetchers } from './users.svelte';

function user(overrides: Partial<UserRead> = {}): UserRead {
	return {
		id: 'user-1',
		username: 'admin',
		email: null,
		role: 'admin',
		isAdmin: true,
		isActive: true,
		createdAt: '2026-07-03T00:00:00Z',
		...overrides
	};
}

function fetchers(overrides: Partial<UsersFetchers> = {}): UsersFetchers {
	return {
		list: () => Promise.resolve([user()]),
		create: () => Promise.resolve(user({ id: 'user-2', username: 'viewer', role: 'viewer' })),
		setRole: (_id, body) => Promise.resolve(user({ role: body.role })),
		remove: () => Promise.resolve(),
		...overrides
	};
}

describe('users state', () => {
	test('load populates users', async () => {
		const state = createUsersState(fetchers());
		await state.load();
		expect(state.users).toHaveLength(1);
		expect(state.users[0]?.role).toBe('admin');
	});

	test('create posts the body and reloads', async () => {
		const created: UserCreateRequest[] = [];
		const state = createUsersState(
			fetchers({
				create: (body) => {
					created.push(body);
					return Promise.resolve(user({ role: 'viewer' }));
				}
			})
		);
		const ok = await state.create({
			username: 'v',
			password: 'a-long-password-here',
			email: null,
			role: 'viewer'
		});
		expect(ok).toBe(true);
		expect(created[0]?.role).toBe('viewer');
	});

	test('setRole sends the new role', async () => {
		const roles: string[] = [];
		const state = createUsersState(
			fetchers({
				setRole: (_id, body) => {
					roles.push(body.role);
					return Promise.resolve(user({ role: body.role }));
				}
			})
		);
		const ok = await state.setRole('user-1', 'viewer');
		expect(ok).toBe(true);
		expect(roles).toEqual(['viewer']);
	});

	test('a failed load lands in error state', async () => {
		const state = createUsersState(fetchers({ list: () => Promise.reject(new Error('nope')) }));
		await state.load();
		expect(state.error).toBe('nope');
	});
});
