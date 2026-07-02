// Intent history state (P2-T6, FR-V2 read scope): filterable, paginated
// audit surface with per-intent drill-in (events + decision trace).

import type { IntentsQuery } from '$lib/api/endpoints';
import type { IntentDetail, IntentRead, Page } from '$lib/api/types';

export interface HistoryApi {
	list(query: IntentsQuery): Promise<Page<IntentRead>>;
	detail(id: string): Promise<IntentDetail>;
}

export const HISTORY_PAGE_SIZE = 50;

export interface HistoryFilters {
	states: string;
	instanceId: string;
	mediaType: '' | 'episode' | 'movie';
	targetLanguage: string;
	createdAfter: string;
	createdBefore: string;
}

const EMPTY_FILTERS: HistoryFilters = {
	states: '',
	instanceId: '',
	mediaType: '',
	targetLanguage: '',
	createdAfter: '',
	createdBefore: ''
};

export function createHistoryState(api: HistoryApi, pageSize = HISTORY_PAGE_SIZE) {
	let items = $state<IntentRead[]>([]);
	let total = $state(0);
	let offset = $state(0);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let filters = $state<HistoryFilters>({ ...EMPTY_FILTERS });
	let selected = $state<IntentDetail | null>(null);
	let detailLoading = $state(false);

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			const page = await api.list({
				states: filters.states || undefined,
				instanceId: filters.instanceId || undefined,
				mediaType: filters.mediaType || undefined,
				targetLanguage: filters.targetLanguage || undefined,
				createdAfter: filters.createdAfter || undefined,
				createdBefore: filters.createdBefore || undefined,
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

	async function setFilters(next: Partial<HistoryFilters>): Promise<void> {
		filters = { ...filters, ...next };
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

	async function open(id: string): Promise<void> {
		detailLoading = true;
		error = null;
		try {
			selected = await api.detail(id);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			detailLoading = false;
		}
	}

	function close(): void {
		selected = null;
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
		get filters() {
			return filters;
		},
		get selected() {
			return selected;
		},
		get detailLoading() {
			return detailLoading;
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
		prev,
		open,
		close
	};
}

export type HistoryState = ReturnType<typeof createHistoryState>;
