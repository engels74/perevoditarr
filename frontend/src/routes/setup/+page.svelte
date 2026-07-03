<script lang="ts">
import { goto } from '$app/navigation';
import Logo from '$lib/components/logo.svelte';
import AdminStep from '$lib/components/setup/admin-step.svelte';
import BazarrStep from '$lib/components/setup/bazarr-step.svelte';
import FinishStep from '$lib/components/setup/finish-step.svelte';
import LingarrStep from '$lib/components/setup/lingarr-step.svelte';
import NotificationsStep from '$lib/components/setup/notifications-step.svelte';
import PolicyStep from '$lib/components/setup/policy-step.svelte';
import * as Card from '$lib/components/ui/card';
import { session } from '$lib/state/session.svelte';

const STEPS = ['Admin', 'Bazarr', 'Lingarr', 'Policy', 'Notifications', 'Finish'] as const;

// Resume mid-wizard: the server only tracks required progress, so map its
// phase to the earliest matching UI step. Optional steps never move the server
// phase, so the operator can still walk through them.
function phaseToStep(phase: (typeof session)['setupPhase']): number {
	switch (phase) {
		case 'bazarr':
			return 1;
		case 'lingarr':
			return 2;
		case 'policy':
			return 3;
		case 'notifications':
			return 4;
		case 'finish':
		case 'done':
			return 5;
		default:
			return 0;
	}
}

let currentStep = $state(phaseToStep(session.setupPhase));

// Once the admin exists, the Admin step is done — never navigate back into it
// (a resubmit would 409). Bazarr becomes the effective first step.
const minStep = $derived(session.setupChecklist?.hasAdmin ? 1 : 0);

function goToStep(index: number): void {
	currentStep = index;
}

function next(): void {
	currentStep = Math.min(currentStep + 1, STEPS.length - 1);
}

function back(): void {
	currentStep = Math.max(currentStep - 1, minStep);
}
</script>

<div class="flex min-h-screen flex-col items-center justify-center gap-8 p-6">
	<div class="brand-enter">
		<Logo size={52} wordmark={false} />
	</div>
	<Card.Root class="w-full max-w-xl">
		<Card.Header>
			<Card.Title>Welcome to Perevoditarr</Card.Title>
			<Card.Description>First-run setup — {STEPS[currentStep]}</Card.Description>
			<ol class="mt-3 flex flex-wrap items-center gap-2 text-xs">
				{#each STEPS as step, index (step)}
					<li class="flex items-center gap-2">
						<span
							class="flex size-6 items-center justify-center rounded-full border text-[11px] font-medium {index ===
							currentStep
								? 'border-primary bg-primary text-primary-foreground'
								: index < currentStep
									? 'border-primary text-primary'
									: 'border-muted-foreground/40 text-muted-foreground'}"
						>
							{index + 1}
						</span>
						<span
							class={index === currentStep
								? 'font-medium text-foreground'
								: 'text-muted-foreground'}
						>
							{step}
						</span>
						{#if index < STEPS.length - 1}
							<span class="text-muted-foreground/40">›</span>
						{/if}
					</li>
				{/each}
			</ol>
		</Card.Header>
		<Card.Content>
			{#if currentStep === 0}
				<AdminStep onComplete={() => goToStep(1)} />
			{:else if currentStep === 1}
				<BazarrStep onBack={back} onNext={next} />
			{:else if currentStep === 2}
				<LingarrStep onBack={back} onNext={next} onSkip={next} />
			{:else if currentStep === 3}
				<PolicyStep onBack={back} onNext={next} onSkip={next} />
			{:else if currentStep === 4}
				<NotificationsStep onBack={back} onNext={next} onSkip={next} />
			{:else}
				<FinishStep onBack={back} onFinish={() => void goto('/')} />
			{/if}
		</Card.Content>
	</Card.Root>
</div>
