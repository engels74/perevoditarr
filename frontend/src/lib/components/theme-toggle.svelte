<script lang="ts">
import MoonIcon from '@lucide/svelte/icons/moon';
import SunIcon from '@lucide/svelte/icons/sun';
import { toggleMode } from 'mode-watcher';
import { Button } from '$lib/components/ui/button';
</script>

<Button onclick={toggleMode} variant="ghost" size="icon" aria-label="Toggle theme">
	<SunIcon class="size-5 dark:hidden" />
	<MoonIcon class="hidden size-5 dark:block" />
</Button>
