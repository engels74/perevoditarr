<script lang="ts">
import { Button } from '$lib/components/ui/button';
import { Input } from '$lib/components/ui/input';
import { Label } from '$lib/components/ui/label';
import { session } from '$lib/state/session.svelte';

let { onComplete }: { onComplete: () => void } = $props();

let bootstrapToken = $state('');
let username = $state('');
let email = $state('');
let password = $state('');
let confirmPassword = $state('');
let localError = $state<string | null>(null);

async function submit(event: SubmitEvent): Promise<void> {
	event.preventDefault();
	localError = null;
	if (bootstrapToken.trim() === '') {
		localError = 'Enter the bootstrap token from the server logs';
		return;
	}
	if (password !== confirmPassword) {
		localError = 'Passwords do not match';
		return;
	}
	if (password.length < 10) {
		localError = 'Password must be at least 10 characters';
		return;
	}
	const created = await session.completeSetup({
		username,
		password,
		bootstrapToken: bootstrapToken.trim(),
		email: email.trim() === '' ? null : email.trim()
	});
	if (created) {
		onComplete();
	}
}
</script>

<form class="space-y-4" onsubmit={submit}>
	<div class="space-y-2">
		<Label for="bootstrap-token">Bootstrap token</Label>
		<Input
			id="bootstrap-token"
			name="bootstrapToken"
			autocomplete="off"
			placeholder="xxxx-xxxx-xxxx"
			bind:value={bootstrapToken}
			required
		/>
		<p class="text-xs text-muted-foreground">
			Printed to the server logs at startup (e.g. <code>docker logs</code>). It expires 15 minutes
			after boot — restart the app to get a fresh one.
		</p>
	</div>
	<div class="space-y-2">
		<Label for="username">Username</Label>
		<Input id="username" name="username" autocomplete="username" bind:value={username} required />
	</div>
	<div class="space-y-2">
		<Label for="email">Email (optional)</Label>
		<Input id="email" name="email" type="email" autocomplete="email" bind:value={email} />
	</div>
	<div class="space-y-2">
		<Label for="password">Password</Label>
		<Input
			id="password"
			name="password"
			type="password"
			autocomplete="new-password"
			bind:value={password}
			required
		/>
		<p class="text-xs text-muted-foreground">At least 10 characters.</p>
	</div>
	<div class="space-y-2">
		<Label for="confirm-password">Confirm password</Label>
		<Input
			id="confirm-password"
			name="confirmPassword"
			type="password"
			autocomplete="new-password"
			bind:value={confirmPassword}
			required
		/>
	</div>
	{#if localError ?? session.error}
		<p class="text-sm text-destructive" data-testid="setup-error">
			{localError ?? session.error}
		</p>
	{/if}
	<Button type="submit" class="w-full" disabled={session.loading}>
		{session.loading ? 'Creating account…' : 'Create administrator'}
	</Button>
</form>
