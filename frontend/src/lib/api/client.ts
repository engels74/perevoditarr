// Typed client for Perevoditarr's own /api/v1 — the UI consumes only this API
// (PRD §2.3). Generated types replace these hand-written ones in P1-T7.

export interface HelloMessage {
	appName: string;
	message: string;
}

export async function getHello(fetchFn: typeof fetch = fetch): Promise<HelloMessage> {
	const response = await fetchFn('/api/v1/hello');
	if (!response.ok) {
		throw new Error(`GET /api/v1/hello failed: ${response.status}`);
	}
	return (await response.json()) as HelloMessage;
}
