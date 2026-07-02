<script lang="ts">
import SendIcon from '@lucide/svelte/icons/send';
import Trash2Icon from '@lucide/svelte/icons/trash-2';
import {
	createNotificationRoute,
	deleteNotificationRoute,
	listNotificationRoutes,
	sendNotificationDigest,
	testNotificationRoute,
	updateNotificationRoute
} from '$lib/api/endpoints';
import type { NotificationRouteCreate } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import { Input } from '$lib/components/ui/input';
import { Label } from '$lib/components/ui/label';
import { createNotificationsState } from '$lib/state/notifications.svelte';

type EventKey = NotificationRouteCreate['events'] extends (infer T)[] | undefined ? T : never;

const EVENTS: { key: EventKey; label: string }[] = [
	{ key: 'breaker_tripped', label: 'Breaker tripped' },
	{ key: 'breaker_closed', label: 'Breaker recovered' },
	{ key: 'cap_reached', label: 'Cap reached' },
	{ key: 'quarantine_added', label: 'Quarantine additions' },
	{ key: 'doctor_critical', label: 'Doctor criticals' },
	{ key: 'daily_digest', label: 'Daily digest' }
];

const notifications = createNotificationsState({
	list: () => listNotificationRoutes(),
	create: (body) => createNotificationRoute(body),
	update: (id, body) => updateNotificationRoute(id, body),
	remove: (id) => deleteNotificationRoute(id),
	test: (id) => testNotificationRoute(id)
});

let name = $state('');
let url = $state('');
let selected = $state<Set<EventKey>>(new Set());
let digestBusy = $state(false);
let digestResult = $state<string | null>(null);

$effect(() => {
	void notifications.load();
});

function toggleEvent(key: EventKey): void {
	const next = new Set(selected);
	if (next.has(key)) {
		next.delete(key);
	} else {
		next.add(key);
	}
	selected = next;
}

async function submit(event: SubmitEvent): Promise<void> {
	event.preventDefault();
	const ok = await notifications.create({
		name,
		url,
		enabled: true,
		events: [...selected]
	});
	if (ok) {
		name = '';
		url = '';
		selected = new Set();
	}
}

async function sendDigest(): Promise<void> {
	digestBusy = true;
	digestResult = null;
	try {
		const result = await sendNotificationDigest();
		digestResult = `Digest sent to ${result.routesNotified} route(s).`;
	} catch (cause) {
		digestResult = cause instanceof Error ? cause.message : String(cause);
	} finally {
		digestBusy = false;
	}
}
</script>

<div class="space-y-5">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<h1 class="text-2xl font-semibold">Notifications</h1>
		<Button variant="outline" size="sm" disabled={digestBusy} onclick={() => void sendDigest()}>
			<SendIcon class="size-4" /> Send digest now
		</Button>
	</div>

	{#if digestResult}
		<p class="text-sm text-muted-foreground">{digestResult}</p>
	{/if}
	{#if notifications.error}
		<p class="text-sm text-destructive">{notifications.error}</p>
	{/if}
	{#if notifications.lastTest}
		<p class="text-sm {notifications.lastTest.sent ? 'text-muted-foreground' : 'text-destructive'}">
			Test: {notifications.lastTest.detail}
		</p>
	{/if}

	<Card.Root>
		<Card.Header class="pb-3">
			<Card.Title class="text-base">Add a route</Card.Title>
			<Card.Description>
				Apprise URL (Discord, Telegram, Slack, email, …). The URL is encrypted at rest and never shown
				again after saving.
			</Card.Description>
		</Card.Header>
		<Card.Content>
			<form class="space-y-3" onsubmit={submit}>
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
				<fieldset class="space-y-2">
					<legend class="text-sm font-medium">Events</legend>
					<div class="grid gap-2 sm:grid-cols-3">
						{#each EVENTS as event (event.key)}
							<label class="flex items-center gap-2 text-sm">
								<input
									type="checkbox"
									class="size-4 rounded border-input"
									checked={selected.has(event.key)}
									onchange={() => toggleEvent(event.key)}
								/>
								{event.label}
							</label>
						{/each}
					</div>
				</fieldset>
				<Button type="submit" disabled={notifications.busy || !name || !url}>Add route</Button>
			</form>
		</Card.Content>
	</Card.Root>

	<section class="space-y-2">
		<h2 class="text-lg font-medium">Routes</h2>
		{#each notifications.routes as route (route.id)}
			<Card.Root>
				<Card.Content class="flex flex-wrap items-center justify-between gap-3 py-4">
					<div class="space-y-1">
						<div class="flex items-center gap-2">
							<span class="font-medium">{route.name}</span>
							<span class="font-mono text-xs text-muted-foreground">{route.urlMasked}</span>
							{#if !route.enabled}
								<Badge variant="secondary">disabled</Badge>
							{/if}
						</div>
						<div class="flex flex-wrap gap-1">
							{#each route.events as event (event)}
								<Badge variant="outline" class="font-mono text-xs">{event}</Badge>
							{:else}
								<span class="text-xs text-muted-foreground">no events subscribed</span>
							{/each}
						</div>
					</div>
					<div class="flex items-center gap-1">
						<Button
							size="sm"
							variant="outline"
							disabled={notifications.busy}
							onclick={() =>
								void notifications.update(route.id, { enabled: !route.enabled })}
						>
							{route.enabled ? 'Disable' : 'Enable'}
						</Button>
						<Button
							size="sm"
							variant="outline"
							disabled={notifications.busy}
							onclick={() => void notifications.test(route.id)}
						>
							Test
						</Button>
						<Button
							size="sm"
							variant="ghost"
							disabled={notifications.busy}
							onclick={() => void notifications.remove(route.id)}
							aria-label="Delete route"
						>
							<Trash2Icon class="size-4" />
						</Button>
					</div>
				</Card.Content>
			</Card.Root>
		{:else}
			<p class="text-sm text-muted-foreground">
				{notifications.loading ? 'Loading…' : 'No notification routes yet.'}
			</p>
		{/each}
	</section>
</div>
