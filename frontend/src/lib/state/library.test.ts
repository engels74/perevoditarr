import { describe, expect, test } from 'bun:test';
import type { LibraryQuery } from '$lib/api/endpoints';
import type { Page } from '$lib/api/types';
import { createPagedList } from './library.svelte';

interface Row {
	id: string;
	title: string;
}

function makeFetcher(total: number, seen: LibraryQuery[]) {
	return (query: LibraryQuery): Promise<Page<Row>> => {
		seen.push(query);
		const offset = query.offset ?? 0;
		const limit = query.limit ?? 50;
		const count = Math.max(0, Math.min(limit, total - offset));
		return Promise.resolve({
			items: Array.from({ length: count }, (_, i) => ({
				id: `row-${offset + i}`,
				title: `Title ${offset + i}`
			})),
			total,
			limit,
			offset
		});
	};
}

describe('paged library list', () => {
	test('load requests the first page with filters omitted when empty', async () => {
		const seen: LibraryQuery[] = [];
		const list = createPagedList(makeFetcher(120, seen));
		await list.load();
		expect(seen[0]).toEqual({
			search: undefined,
			missingLanguage: undefined,
			limit: 50,
			offset: 0
		});
		expect(list.items).toHaveLength(50);
		expect(list.total).toBe(120);
		expect(list.pageNumber).toBe(1);
		expect(list.pageCount).toBe(3);
		expect(list.hasPrev).toBe(false);
		expect(list.hasNext).toBe(true);
	});

	test('next/prev walk pages and clamp at the ends', async () => {
		const seen: LibraryQuery[] = [];
		const list = createPagedList(makeFetcher(120, seen));
		await list.load();
		await list.next();
		expect(list.offset).toBe(50);
		await list.next();
		expect(list.offset).toBe(100);
		expect(list.items).toHaveLength(20);
		expect(list.hasNext).toBe(false);
		await list.next();
		expect(list.offset).toBe(100);
		await list.prev();
		await list.prev();
		expect(list.offset).toBe(0);
		await list.prev();
		expect(list.offset).toBe(0);
	});

	test('setFilters resets to the first page and passes the filters through', async () => {
		const seen: LibraryQuery[] = [];
		const list = createPagedList(makeFetcher(120, seen));
		await list.load();
		await list.next();
		await list.setFilters('vinland', 'da');
		const last = seen.at(-1);
		expect(last).toEqual({ search: 'vinland', missingLanguage: 'da', limit: 50, offset: 0 });
		expect(list.offset).toBe(0);
	});

	test('a fetch failure is captured as error state', async () => {
		const list = createPagedList<Row>(() => Promise.reject(new Error('boom')));
		await list.load();
		expect(list.error).toBe('boom');
		expect(list.items).toHaveLength(0);
		expect(list.loading).toBe(false);
	});
});
