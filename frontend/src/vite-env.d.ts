/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Dev server only: skip the login gate. Ignored by `vite build`. */
  readonly VITE_AUTH_BYPASS?: string;
}
