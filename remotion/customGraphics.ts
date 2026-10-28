import type React from 'react';
import type {CustomGraphicProps} from './types';

/**
 * Components written for one reel (`custom` elements), by id. Empty here: a
 * render that uses them bundles a registry of its own checked components in
 * place of this module (scripts/remotion/render.mjs).
 */
export const CUSTOM_GRAPHICS: Record<string, React.FC<CustomGraphicProps>> = {};
