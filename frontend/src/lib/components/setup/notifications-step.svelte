<script lang="ts">
import {
	createNotificationRoute,
	listNotificationRoutes,
	testNotificationRoute
} from '$lib/api/endpoints';
import type { NotificationRouteRead } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import { Input } from '$lib/components/ui/input';
import { Label } from '$lib/components/ui/label';
import { session } from '$lib/state/session.svelte';

let { onBack, onNext, onSkip }: { onBack: () => void; onNext: () => void; onSkip: () => void } =
	$props();

let name = $state('');
let url = $state('');
let routes = $state<NotificationRouteRead[]>([]);
let localError = $state<string | null>(null);
let testResult = $state<string | null>(null);
let saveBusy = $state(false);
let testBusyId = $state<string | null>(null);

function message(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

async function loadRoutes(): Promise<void> {
	try {
		routes = await listNotificationRoutes();
	} catch (cause) {
		localError = message(cause);
	}
}

$effect(() => {
	void loadRoutes();
});

async function add(): Promise<void> {
	saveBusy = true;
	localError = null;
	try {
		await createNotificationRoute({ name, url, enabled: true });
		name = '';
		url = '';
		await loadRoutes();
		await session.refreshSetup();
	} catch (cause) {
		localError = message(cause);
	} finally {
		saveBusy = false;
	}
}

async function test(id: string): Promise<void> {
	testBusyId = id;
	testResult = null;
	try {
		const result = await testNotificationRoute(id);
		testResult = result.detail;
	} catch (cause) {
		testResult = message(cause);
	} finally {
		testBusyId = null;
	}
}
</script>

<div class="space-y-4">
	<p class="text-sm text-muted-foreground">
		Optionally add a notification route (Apprise URL) to get alerts about breakers, caps, and
		digests. You can skip this and configure it later from Settings.
	</p>

	<form
		class="space-y-3"
		onsubmit={(event) => {
			event.preventDefault();
			void add();
		}}
	>
		<div class="grid gap-3 sm:grid-cols-2">
			<div class="space-y-1">
				<Label for="route-name">Name</Label>
				<Input id="route-name" bind:value={name} placeholder="Ops alerts" required />
			</div>
			<div class="space-y-1">
				<Label for="route-url">Apprise URL</Label>
				<Input id="route-url" bind:value={url} placeholder="discord://token@id" required />
			</div>
		</div>
		{#if localError}
			<p class="text-sm text-destructive">{localError}</p>
		{/if}
		{#if testResult}
			<p class="text-sm text-muted-foreground">Test: {testResult}</p>
		{/if}
		<Button type="submit" disabled={saveBusy || !name || !url}>
			{saveBusy ? 'Adding…' : 'Add route'}
		</Button>
	</form>

	<div class="space-y-2">
		<h3 class="text-sm font-medium">Routes</h3>
		{#each routes as route (route.id)}
			<div class="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
				<span class="flex items-center gap-2">
					<span class="font-medium">{route.name}</span>
					<span class="font-mono text-xs text-muted-foreground">{route.urlMasked}</span>
					{#if !route.enabled}
						<Badge variant="secondary">disabled</Badge>
					{/if}
				</span>
				<Button
					size="sm"
					variant="outline"
					disabled={testBusyId === route.id}
					onclick={() => void test(route.id)}
				>
					{testBusyId === route.id ? 'Testing…' : 'Test'}
				</Button>
			</div>
		{:else}
			<p class="text-sm text-muted-foreground">No notification routes yet.</p>
		{/each}
	</div>

	<div class="flex items-center justify-between">
		<Button variant="ghost" onclick={onBack}>Back</Button>
		<div class="flex gap-2">
			<Button variant="outline" onclick={onSkip}>Skip</Button>
			<Button onclick={onNext}>Next</Button>
		</div>
	</div>
</div>
