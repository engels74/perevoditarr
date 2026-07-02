import { redirect } from '@sveltejs/kit';

// /settings currently has a single section; land on it directly.
export function load(): never {
	redirect(307, '/settings/instances');
}
