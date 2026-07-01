import { getHello, type HelloMessage } from '$lib/api/client';

// Shared reactive state lives in .svelte.ts modules exposed through getter
// accessors (rules doc); the fetcher is injectable for tests.
export function createHelloState(fetchHello: () => Promise<HelloMessage> = getHello) {
	let message = $state<HelloMessage | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(false);

	return {
		get message() {
			return message;
		},
		get error() {
			return error;
		},
		get loading() {
			return loading;
		},
		async load(): Promise<void> {
			loading = true;
			error = null;
			try {
				message = await fetchHello();
			} catch (cause) {
				message = null;
				error = cause instanceof Error ? cause.message : String(cause);
			} finally {
				loading = false;
			}
		}
	};
}
