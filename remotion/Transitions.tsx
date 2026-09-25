import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Transition} from './types';

export type TransitionState = {scale: number; blur: number; shiftX: number; flash: number};

const IDLE: TransitionState = {scale: 1, blur: 0, shiftX: 0, flash: 0};

/**
 * The effect of whichever transition spans this frame. Each one is centred on
 * its cut: it builds up to the cut and resolves after it, so the cut itself
 * lands at the peak, where the eye expects it.
 */
export const useTransition = (transitions: Transition[]): TransitionState => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const now = frame / fps;
  const active = transitions.find(
    (item) => now >= item.at - item.duration / 2 && now < item.at + item.duration / 2,
  );
  if (!active) {
    return IDLE;
  }
  const progress = interpolate(
    now,
    [active.at - active.duration / 2, active.at + active.duration / 2],
    [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  const peak = Math.sin(Math.PI * progress);
  if (active.style === 'slide') {
    const direction = progress < 0.5 ? -1 : 1;
    return {scale: 1, blur: 10 * peak, shiftX: direction * width * 0.12 * peak, flash: 0};
  }
  if (active.style === 'flash') {
    return {scale: 1 + 0.03 * peak, blur: 0, shiftX: 0, flash: 0.6 * peak};
  }
  return {scale: 1 + 0.2 * peak, blur: 7 * peak, shiftX: 0, flash: 0};
};
