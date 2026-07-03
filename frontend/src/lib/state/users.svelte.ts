// User management state (P5-T2, FR-A6): admin CRUD over users and roles.
// Fetchers injected for testability.

import type { UserCreateRequest, UserRead, UserRoleUpdate } from '$lib/api/types';

export interface UsersFetchers {
	list: () => Promise<UserRead[]>;
	create: (body: UserCreateRequest) => Promise<UserRead>;
	setRole: (id: string, body: UserRoleUpdate) => Promise<UserRead>;
	remove: (id: string) => Promise<void>;
}

function message(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

export function createUsersState(fetchers: UsersFetchers) {
	let users = $state<UserRead[]>([]);
	let loading = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			users = await fetchers.list();
		} catch (cause) {
			error = message(cause);
		} finally {
			loading = false;
		}
	}

	async function run(mutate: () => Promise<void>): Promise<boolean> {
		busy = true;
		error = null;
		try {
			await mutate();
			await load();
			return true;
		} catch (cause) {
			error = message(cause);
			return false;
		} finally {
			busy = false;
		}
	}

	async function create(body: UserCreateRequest): Promise<boolean> {
		return run(async () => {
			await fetchers.create(body);
		});
	}

	async function setRole(id: string, role: UserRoleUpdate['role']): Promise<boolean> {
		return run(async () => {
			await fetchers.setRole(id, { role });
		});
	}

	async function remove(id: string): Promise<boolean> {
		return run(async () => {
			await fetchers.remove(id);
		});
	}

	return {
		get users(): UserRead[] {
			return users;
		},
		get loading() {
			return loading;
		},
		get busy() {
			return busy;
		},
		get error() {
			return error;
		},
		load,
		create,
		setRole,
		remove
	};
}

export type UsersState = ReturnType<typeof createUsersState>;
