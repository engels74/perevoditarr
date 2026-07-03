import { fileURLToPath } from 'node:url';
import { sveltekit } from '@sveltejs/kit/vite';
import UnoCSS from 'unocss/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	// Read env from the repo root (the shared `.env`) and from this folder
	// (`frontend/.env`), with the local file overriding the shared one. Only the
	// dev-server config below reads these; `envPrefix` (default `VITE_`) still
	// governs what reaches the browser bundle, so the unprefixed orchestration
	// vars stay server-side.
	const rootDir = fileURLToPath(new URL('..', import.meta.url));
	const localDir = fileURLToPath(new URL('.', import.meta.url));
	const env = { ...loadEnv(mode, rootDir, ''), ...loadEnv(mode, localDir, '') };

	const backendHost = env.BACKEND_HOST || 'localhost';
	const backendPort = env.BACKEND_PORT || '8000';
	const backendUrl = env.VITE_BACKEND_URL || `http://${backendHost}:${backendPort}`;
	const parsedPort = Number(env.FRONTEND_PORT || env.PORT || '5173');
	const frontendPort = Number.isNaN(parsedPort) ? 5173 : parsedPort;

	return {
		// UnoCSS must run before sveltekit
		plugins: [UnoCSS(), sveltekit()],
		server: {
			port: frontendPort,
			proxy: {
				'/api': backendUrl,
				'/sse': backendUrl
			}
		}
	};
});
