import { describe, expect, test } from 'bun:test';

import { createHelloState } from './hello.svelte';

describe('hello state (.svelte.ts smoke test)', () => {
	test('loads a message through the injected fetcher', async () => {
		const state = createHelloState(() =>
			Promise.resolve({ appName: 'Perevoditarr', message: 'privet' })
		);
		expect(state.loading).toBe(false);
		expect(state.message).toBeNull();

		await state.load();

		expect(state.message).toEqual({ appName: 'Perevoditarr', message: 'privet' });
		expect(state.error).toBeNull();
		expect(state.loading).toBe(false);
	});

	test('captures a failure as error state', async () => {
		const state = createHelloState(() => Promise.reject(new Error('boom')));

		await state.load();

		expect(state.error).toBe('boom');
		expect(state.message).toBeNull();
		expect(state.loading).toBe(false);
	});
});
