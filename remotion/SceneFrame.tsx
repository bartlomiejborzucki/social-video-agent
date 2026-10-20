import React from 'react';
import {AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneFrameGeometry} from './types';

/** `#RRGGBB` at an opacity, for fills and glows drawn in a brand colour. */
export const rgba = (hex: string, alpha: number): string => {
  const value = hex.replace('#', '');
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
};

/** Seconds the title takes to flip when one scene hands over to the next. */
const FLIP_S = 0.5;

/**
 * A scene label drawn as the title of a frame around that scene's captions.
 *
 * The label names the scene; the captions inside the frame are what is said.
 * Drawn as a title tab on the frame, it can never be read as a caption. The
 * geometry comes from Python (motion/layout.py) and is the same for every cue
 * of the scene, so the frame never jumps from one cue to the next. When the
 * next label starts exactly where this one ends, the frame stays and only the
 * title flips over, with a short flash of the brand accent.
 */
export const SceneFrame: React.FC<{
  text: string;
  previous?: string | null;
  geometry: SceneFrameGeometry;
  accent: string;
  secondary: string;
  font: string;
  /** This title's size, fitted to the tab in Python; the frame's own if unset. */
  fontPx?: number | null;
  previousFontPx?: number | null;
}> = ({text, previous, geometry: g, accent, secondary, font, fontPx, previousFontPx}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const flip = Math.max(2, Math.round(fps * FLIP_S));
  const half = Math.round(flip * 0.45);
  const enter = previous ? 1 : spring({frame, fps, config: {damping: 18, stiffness: 160}});
  const tab = previous ? 1 : spring({frame: frame - 4, fps, config: {damping: 16, stiffness: 180}});
  const showOld = Boolean(previous) && frame < half;
  const rotation = !previous
    ? 0
    : showOld
      ? interpolate(frame, [0, half], [0, 90], {extrapolateRight: 'clamp', easing: Easing.in(Easing.cubic)})
      : interpolate(frame, [half, flip], [-90, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
          easing: Easing.out(Easing.back(1.6)),
        });
  const glow = previous
    ? interpolate(frame, [half, half + Math.round(fps * 0.15), half + fps], [0, 1, 0], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      })
    : 0;
  const shown = showOld ? previous : text;
  const size = (showOld ? previousFontPx : fontPx) ?? g.tab_font_px;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          left: g.left,
          top: g.top,
          width: g.width,
          height: g.height,
          boxSizing: 'border-box',
          borderRadius: g.radius,
          border: `${g.border}px solid ${glow > 0.05 ? accent : 'rgba(255,255,255,0.95)'}`,
          background: rgba(secondary, 0.3),
          backdropFilter: 'blur(3px)',
          boxShadow: `0 ${g.border * 2}px ${g.border * 8}px rgba(20,24,40,0.35)`,
          opacity: enter,
          transform: `scale(${0.94 + 0.06 * enter})`,
          transformOrigin: '50% 100%',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 0,
          width: '100%',
          top: g.tab_top,
          height: g.tab_height,
          display: 'flex',
          justifyContent: 'center',
          opacity: tab,
          transform: `translateY(${(1 - tab) * g.tab_height * 0.25}px) perspective(${g.tab_height * 8}px) rotateX(${rotation}deg)`,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            boxSizing: 'border-box',
            height: g.tab_height,
            gap: g.tab_dot,
            fontFamily: font,
            fontSize: size,
            fontWeight: 800,
            letterSpacing: size * 0.07,
            textTransform: 'uppercase',
            lineHeight: 1.15,
            color: '#FFFFFF',
            background: secondary,
            border: `${g.tab_border}px solid rgba(255,255,255,0.95)`,
            padding: `${g.tab_pad_y}px ${g.tab_pad_x}px`,
            borderRadius: 999,
            whiteSpace: 'nowrap',
            boxShadow: `0 0 ${g.tab_font_px * 0.85 * glow}px ${g.tab_font_px * 0.25 * glow}px ${rgba(accent, 0.8 * glow)}`,
          }}
        >
          <span style={{width: g.tab_dot, height: g.tab_dot, borderRadius: 999, background: accent, flex: 'none'}} />
          <span>{shown}</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
