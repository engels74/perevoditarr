<script lang="ts">
import { goto } from '$app/navigation';
import { apiFetch } from '$lib/api/client';
import type { LoginProviders } from '$lib/api/types';
import Logo from '$lib/components/logo.svelte';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import { Input } from '$lib/components/ui/input';
import { session } from '$lib/state/session.svelte';

let username = $state('');
let password = $state('');
let providers = $state<LoginProviders | null>(null);

void apiFetch<LoginProviders>('/api/v1/auth/providers')
	.then((result) => {
		providers = result;
	})
	.catch(() => {
		// login page still works with built-in auth if this fails
	});

async function submit(event: SubmitEvent) {
	event.preventDefault();
	if (await session.login(username, password)) {
		void goto('/');
	}
}
</script>

<div class="flex min-h-screen flex-col items-center justify-center gap-8 p-6">
	<div class="brand-enter">
		<Logo size={52} wordmark={false} />
	</div>
	<Card.Root class="w-full max-w-sm">
		<Card.Header>
			<Card.Title>Sign in</Card.Title>
			<Card.Description>Perevoditarr — subtitle translation orchestrator</Card.Description>
		</Card.Header>
		<Card.Content class="space-y-4">
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
					<label class="text-sm font-medium" for="password">Password</label>
					<Input
						id="password"
						name="password"
						type="password"
						autocomplete="current-password"
						bind:value={password}
						required
					/>
				</div>
				{#if session.error}
					<p class="text-sm text-destructive" data-testid="login-error">{session.error}</p>
				{/if}
				<Button type="submit" class="w-full" disabled={session.loading}>
					{session.loading ? 'Signing in…' : 'Sign in'}
				</Button>
			</form>
			{#if providers?.oidc}
				<div class="relative">
					<div class="absolute inset-0 flex items-center">
						<span class="w-full border-t"></span>
					</div>
					<div class="relative flex justify-center text-xs uppercase">
						<span class="bg-card px-2 text-muted-foreground">or</span>
					</div>
				</div>
				<Button variant="outline" class="w-full" href="/api/v1/auth/oidc/login">
					Continue with {providers.oidc.displayName}
				</Button>
			{/if}
		</Card.Content>
	</Card.Root>
</div>
