<script lang="ts">
import { goto } from '$app/navigation';
import Logo from '$lib/components/logo.svelte';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import { Input } from '$lib/components/ui/input';
import { session } from '$lib/state/session.svelte';

let username = $state('');
let email = $state('');
let password = $state('');
let confirmPassword = $state('');
let localError = $state<string | null>(null);

async function submit(event: SubmitEvent) {
	event.preventDefault();
	localError = null;
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
		email: email.trim() === '' ? null : email.trim()
	});
	if (created) {
		void goto('/');
	}
}
</script>

<div class="flex min-h-screen flex-col items-center justify-center gap-8 p-6">
	<div class="brand-enter">
		<Logo size={52} wordmark={false} />
	</div>
	<Card.Root class="w-full max-w-md">
		<Card.Header>
			<Card.Title>Welcome to Perevoditarr</Card.Title>
			<Card.Description>
				First-run setup — create the administrator account. Until this is done, the API only
				accepts this request.
			</Card.Description>
		</Card.Header>
		<Card.Content>
			<form class="space-y-4" onsubmit={submit}>
				<div class="space-y-2">
					<label class="text-sm font-medium" for="username">Username</label>
					<Input
						id="username"
						name="username"
						autocomplete="username"
						bind:value={username}
						required
					/>
				</div>
				<div class="space-y-2">
					<label class="text-sm font-medium" for="email">Email (optional)</label>
					<Input id="email" name="email" type="email" autocomplete="email" bind:value={email} />
				</div>
				<div class="space-y-2">
					<label class="text-sm font-medium" for="password">Password</label>
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
					<label class="text-sm font-medium" for="confirm-password">Confirm password</label>
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
		</Card.Content>
	</Card.Root>
</div>
