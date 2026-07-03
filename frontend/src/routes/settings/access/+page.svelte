<script lang="ts">
import Trash2Icon from '@lucide/svelte/icons/trash-2';
import {
	createUser,
	deleteUser,
	getLdapSettings,
	listUsers,
	putLdapSettings,
	setUserRole
} from '$lib/api/endpoints';
import type { LdapSettingsWrite, UserRole } from '$lib/api/types';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import * as Card from '$lib/components/ui/card';
import { Input } from '$lib/components/ui/input';
import { Label } from '$lib/components/ui/label';
import { session } from '$lib/state/session.svelte';
import { createUsersState } from '$lib/state/users.svelte';

const users = createUsersState({
	list: () => listUsers(),
	create: (body) => createUser(body),
	setRole: (id, body) => setUserRole(id, body),
	remove: (id) => deleteUser(id)
});

// New-user form
let uName = $state('');
let uPassword = $state('');
let uEmail = $state('');
let uRole = $state<UserRole>('viewer');

// LDAP form
let ldap = $state<LdapSettingsWrite>({
	enabled: false,
	serverUri: '',
	bindDn: '',
	bindPassword: null,
	userSearchBase: '',
	userFilter: '(uid={username})',
	emailAttribute: 'mail',
	startTls: false,
	autoCreateUsers: true
});
let ldapPasswordSet = $state(false);
let ldapBusy = $state(false);
let ldapMessage = $state<string | null>(null);

$effect(() => {
	void users.load();
	void getLdapSettings().then((stored) => {
		if (stored) {
			ldap = { ...ldap, ...stored, bindPassword: null };
			ldapPasswordSet = stored.bindPasswordSet;
		}
	});
});

async function addUser(event: SubmitEvent): Promise<void> {
	event.preventDefault();
	const ok = await users.create({
		username: uName,
		password: uPassword,
		email: uEmail || null,
		role: uRole
	});
	if (ok) {
		uName = '';
		uPassword = '';
		uEmail = '';
		uRole = 'viewer';
	}
}

async function saveLdap(event: SubmitEvent): Promise<void> {
	event.preventDefault();
	ldapBusy = true;
	ldapMessage = null;
	try {
		const saved = await putLdapSettings(ldap);
		ldapPasswordSet = saved.bindPasswordSet;
		ldap = { ...ldap, bindPassword: null };
		ldapMessage = 'Saved.';
	} catch (cause) {
		ldapMessage = cause instanceof Error ? cause.message : String(cause);
	} finally {
		ldapBusy = false;
	}
}
</script>

<div class="space-y-8">
	<section class="space-y-4">
		<div>
			<h1 class="text-2xl font-semibold">Users &amp; roles</h1>
			<p class="text-sm text-muted-foreground">
				Admins have full access; viewers are read-only observers.
			</p>
		</div>

		{#if users.error}
			<p class="text-sm text-destructive">{users.error}</p>
		{/if}

		<Card.Root>
			<Card.Header class="pb-3">
				<Card.Title class="text-base">Add a user</Card.Title>
			</Card.Header>
			<Card.Content>
				<form class="space-y-3" onsubmit={addUser}>
					<div class="grid gap-3 sm:grid-cols-2">
						<div class="space-y-1">
							<Label for="u-name">Username</Label>
							<Input id="u-name" bind:value={uName} required />
						</div>
						<div class="space-y-1">
							<Label for="u-password">Password</Label>
							<Input id="u-password" bind:value={uPassword} type="password" required />
						</div>
						<div class="space-y-1">
							<Label for="u-email">Email (optional)</Label>
							<Input id="u-email" bind:value={uEmail} type="email" />
						</div>
						<div class="space-y-1">
							<Label for="u-role">Role</Label>
							<select
								id="u-role"
								bind:value={uRole}
								class="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
							>
								<option value="viewer">Viewer (read-only)</option>
								<option value="admin">Admin (full access)</option>
							</select>
						</div>
					</div>
					<Button type="submit" disabled={users.busy || !uName || !uPassword}>Create user</Button>
				</form>
			</Card.Content>
		</Card.Root>

		<div class="space-y-2">
			{#each users.users as user (user.id)}
				<Card.Root>
					<Card.Content class="flex flex-wrap items-center justify-between gap-3 py-4">
						<div class="flex items-center gap-2">
							<span class="font-medium">{user.username}</span>
							<Badge variant={user.role === 'admin' ? 'default' : 'secondary'}>{user.role}</Badge>
							{#if !user.isActive}<Badge variant="destructive">inactive</Badge>{/if}
							{#if user.email}
								<span class="text-xs text-muted-foreground">{user.email}</span>
							{/if}
						</div>
						<div class="flex items-center gap-1">
							<Button
								size="sm"
								variant="outline"
								disabled={users.busy || user.id === session.user?.id}
								onclick={() =>
									void users.setRole(user.id, user.role === 'admin' ? 'viewer' : 'admin')}
							>
								Make {user.role === 'admin' ? 'viewer' : 'admin'}
							</Button>
							<Button
								size="sm"
								variant="ghost"
								disabled={users.busy || user.id === session.user?.id}
								onclick={() => void users.remove(user.id)}
								aria-label="Delete user"
							>
								<Trash2Icon class="size-4" />
							</Button>
						</div>
					</Card.Content>
				</Card.Root>
			{:else}
				<p class="text-sm text-muted-foreground">
					{users.loading ? 'Loading…' : 'No users.'}
				</p>
			{/each}
		</div>
	</section>

	<section class="space-y-4">
		<div>
			<h2 class="text-xl font-semibold">LDAP authentication</h2>
			<p class="text-sm text-muted-foreground">
				When enabled, a login that fails the built-in check falls back to an LDAP bind. New LDAP
				users are provisioned as viewers.
			</p>
		</div>

		{#if ldapMessage}
			<p class="text-sm text-muted-foreground">{ldapMessage}</p>
		{/if}

		<Card.Root>
			<Card.Content class="pt-6">
				<form class="space-y-3" onsubmit={saveLdap}>
					<label class="flex items-center gap-2 text-sm font-medium">
						<input type="checkbox" class="size-4 rounded border-input" bind:checked={ldap.enabled} />
						Enable LDAP
					</label>
					<div class="grid gap-3 sm:grid-cols-2">
						<div class="space-y-1">
							<Label for="l-uri">Server URI</Label>
							<Input id="l-uri" bind:value={ldap.serverUri} placeholder="ldap://ldap:389" required />
						</div>
						<div class="space-y-1">
							<Label for="l-base">User search base</Label>
							<Input id="l-base" bind:value={ldap.userSearchBase} placeholder="ou=users,dc=…" />
						</div>
						<div class="space-y-1">
							<Label for="l-binddn">Bind DN (service account)</Label>
							<Input id="l-binddn" bind:value={ldap.bindDn} placeholder="cn=svc,dc=…" />
						</div>
						<div class="space-y-1">
							<Label for="l-bindpw">Bind password</Label>
							<Input
								id="l-bindpw"
								type="password"
								placeholder={ldapPasswordSet ? '•••••• (unchanged)' : ''}
								oninput={(e) => (ldap.bindPassword = e.currentTarget.value || null)}
							/>
						</div>
						<div class="space-y-1">
							<Label for="l-filter">User filter</Label>
							<Input id="l-filter" bind:value={ldap.userFilter} />
						</div>
						<div class="space-y-1">
							<Label for="l-attr">Email attribute</Label>
							<Input id="l-attr" bind:value={ldap.emailAttribute} />
						</div>
					</div>
					<div class="flex flex-wrap gap-4">
						<label class="flex items-center gap-2 text-sm">
							<input type="checkbox" class="size-4 rounded border-input" bind:checked={ldap.startTls} />
							StartTLS
						</label>
						<label class="flex items-center gap-2 text-sm">
							<input
								type="checkbox"
								class="size-4 rounded border-input"
								bind:checked={ldap.autoCreateUsers}
							/>
							Auto-create users on first login
						</label>
					</div>
					<Button type="submit" disabled={ldapBusy || !ldap.serverUri}>Save LDAP settings</Button>
				</form>
			</Card.Content>
		</Card.Root>
	</section>
</div>
