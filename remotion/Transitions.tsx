import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Transition} from './types';

/** `leak` is a light leak's progress through its transition, or null when none is open. */
export type TransitionState = {scale: number; blur: number; shiftX: number; flash: number; leak: number | null; seed: number};

const IDLE: TransitionState = {scale: 1, blur: 0, shiftX: 0, flash: 0, leak: null, seed: 0};

/**
 * The effect of whichever transition spans this frame. Each one is centred on
 * its cut: it builds up to the cut and resolves after it, so the cut itself
 * lands at the peak, where the eye expects it.
 */
export const useTransition = (transitions: Transition[]): TransitionState => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const now = frame / fps;
  const index = transitions.findIndex(
    (item) => now >= item.at - item.duration / 2 && now < item.at + item.duration / 2,
  );
  if (index < 0) {
    return IDLE;
  }
  const active = transitions[index];
  const progress = interpolate(
    now,
    [active.at - active.duration / 2, active.at + active.duration / 2],
    [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  const peak = Math.sin(Math.PI * progress);
  if (active.style === 'light_leak') {
    // The leak reveals over the first half and retracts over the second, so
    // it covers most of the frame on the cut. The seed varies its shape from
    // one cut to the next and stays fixed within one.
    return {...IDLE, leak: progress, seed: index + 1};
  }
  if (active.style === 'slide') {
    const direction = progress < 0.5 ? -1 : 1;
    return {...IDLE, blur: 10 * peak, shiftX: direction * width * 0.12 * peak};
  }
  if (active.style === 'flash') {
    return {...IDLE, scale: 1 + 0.03 * peak, flash: 0.6 * peak};
  }
  return {...IDLE, scale: 1 + 0.2 * peak, blur: 7 * peak};
};

/**
 * The hue shift that turns the leak's own yellow-orange (about 35 degrees)
 * into the brand accent's hue. A grey accent keeps the warm default.
 *
 * The effect's shader builds its rotation with GLSL's column-major `mat3`,
 * which turns the hue back by `hueShift`, not forward: a turquoise accent
 * asked for as `hue - 35` came out violet. So the shift is `35 - hue`.
 */
export const leakHueShift = (accent: string): number => {
  const value = accent.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((at) => parseInt(value.slice(at, at + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const chroma = max - min;
  if (!(chroma > 0.05)) {
    return 0;
  }
  const hue =
    max === r ? 60 * (((g - b) / chroma) % 6) : max === g ? 60 * ((b - r) / chroma + 2) : 60 * ((r - g) / chroma + 4);
  return (((35 - hue) % 360) + 360) % 360;
};
