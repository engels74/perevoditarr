<script lang="ts">
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import { createHelloState } from '$lib/state/hello.svelte';

const hello = createHelloState();

$effect(() => {
	void hello.load();
});
</script>

<Card.Root class="max-w-md">
	<Card.Header>
		<Card.Title>Hello from the API</Card.Title>
		<Card.Description>GET /api/v1/hello, same-origin via the dev proxy</Card.Description>
	</Card.Header>
	<Card.Content class="space-y-3">
		{#if hello.loading}
			<p class="text-muted-foreground">Loading…</p>
		{:else if hello.error}
			<p class="text-destructive" data-testid="hello-error">{hello.error}</p>
		{:else if hello.message}
			<p data-testid="hello-message">{hello.message.message}</p>
			<Badge variant="secondary">{hello.message.appName}</Badge>
		{/if}
		<div>
			<Button variant="outline" size="sm" onclick={() => void hello.load()}>Reload</Button>
		</div>
	</Card.Content>
</Card.Root>
