/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" in the static demo build (`npm run build:demo`), which plays a recorded town. */
  readonly VITE_DEMO?: string;
  /** "1" in the tab build (`npm run build:tab`): the engine and the model run in the page itself. */
  readonly VITE_TAB?: string;
}
