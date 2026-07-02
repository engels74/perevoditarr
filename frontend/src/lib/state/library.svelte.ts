// Paged library list state (P1-T9, NFR-4): server-side pagination only — the
// UI never loads the full library client-side. One instance per tab.

import type { LibraryQuery } from '$lib/api/endpoints';
import type { Page } from '$lib/api/types';

export type PageFetcher<T> = (query: LibraryQuery) => Promise<Page<T>>;

export const LIBRARY_PAGE_SIZE = 50;

export function createPagedList<T>(fetchPage: PageFetcher<T>, pageSize = LIBRARY_PAGE_SIZE) {
	let items = $state<T[]>([]);
	let total = $state(0);
	let offset = $state(0);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let search = $state('');
	let missingLanguage = $state('');

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			const page = await fetchPage({
				search: search || undefined,
				missingLanguage: missingLanguage || undefined,
				limit: pageSize,
				offset
			});
			items = page.items;
			total = page.total;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	async function setFilters(nextSearch: string, nextMissingLanguage: string): Promise<void> {
		search = nextSearch;
		missingLanguage = nextMissingLanguage;
		offset = 0;
		await load();
	}

	async function next(): Promise<void> {
		if (offset + pageSize < total) {
			offset += pageSize;
			await load();
		}
	}

	async function prev(): Promise<void> {
		if (offset > 0) {
			offset = Math.max(0, offset - pageSize);
			await load();
		}
	}

	return {
		get items() {
			return items;
		},
		get total() {
			return total;
		},
		get offset() {
			return offset;
		},
		get pageSize() {
			return pageSize;
		},
		get loading() {
			return loading;
		},
		get error() {
			return error;
		},
		get search() {
			return search;
		},
		get missingLanguage() {
			return missingLanguage;
		},
		get pageNumber() {
			return Math.floor(offset / pageSize) + 1;
		},
		get pageCount() {
			return Math.max(1, Math.ceil(total / pageSize));
		},
		get hasPrev() {
			return offset > 0;
		},
		get hasNext() {
			return offset + pageSize < total;
		},
		load,
		setFilters,
		next,
		prev
	};
}

export type PagedList<T> = ReturnType<typeof createPagedList<T>>;
