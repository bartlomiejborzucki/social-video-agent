import React from 'react';
import {Video} from '@remotion/media';
import {AbsoluteFill, Easing, interpolate, random, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import type {PictureEffect} from './types';

/**
 * Picture effects on a static camera: the base picture redrawn for a moment
 * in a frame, a phone, a mirror, three slices, a tilt, black and white; or a
 * layer over it (a torn-paper sweep, a halftone screen, speed lines). Every
 * one is drawn here from CSS and SVG -- no texture or footage is added -- and
 * none separates the person from the background: there is no segmentation,
 * so halftone and speed lines are a translucent layer over the whole frame.
 */

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/** The effect open now, and how far in (0 at the edges, 1 when fully on). */
export const useActiveEffect = (
  effects: PictureEffect[],
): {effect: PictureEffect | null; amount: number; progress: number} => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const now = frame / fps;
  const effect = effects.find((e) => now >= e.start && now < e.end) ?? null;
  if (!effect) {
    return {effect: null, amount: 0, progress: 0};
  }
  const length = Math.max(effect.end - effect.start, 1e-3);
  const ease = Math.min(0.15, length / 3);
  const amount = interpolate(
    now,
    [effect.start, effect.start + ease, effect.end - ease, effect.end],
    [0, 1, 1, 0],
    {...clamp, easing: Easing.inOut(Easing.cubic)},
  );
  return {effect, amount, progress: (now - effect.start) / length};
};

const Picture: React.FC<{source: string; style?: React.CSSProperties}> = ({source, style}) => (
  <Video src={staticFile(source)} muted style={{width: '100%', height: '100%', objectFit: 'cover', ...style}} />
);

/** A slice of the picture: the frame's centre, `share` of its width. */
const Slice: React.FC<{source: string; share: number; mirrored?: boolean; style?: React.CSSProperties}> = ({
  source,
  share,
  mirrored = false,
  style,
}) => {
  const {width} = useVideoConfig();
  return (
    <div style={{position: 'relative', width: width * share, height: '100%', overflow: 'hidden', ...style}}>
      <div
        style={{
          position: 'absolute',
          top: 0,
          height: '100%',
          width,
          left: -(width * (1 - share)) / 2,
          transform: mirrored ? 'scaleX(-1)' : undefined,
        }}
      >
        <Picture source={source} />
      </div>
    </div>
  );
};

/**
 * The base picture, redrawn by the effect open now. Outside every effect it
 * is the plain picture, exactly as before.
 */
export const EffectedPicture: React.FC<{source: string; effects: PictureEffect[]; accent: string}> = ({
  source,
  effects,
  accent,
}) => {
  const {effect, amount} = useActiveEffect(effects);
  const {width, height} = useVideoConfig();
  const u = height / 1920;
  if (!effect) {
    return <Picture source={source} />;
  }
  switch (effect.type) {
    case 'frame_in_frame': {
      const scale = interpolate(amount, [0, 1], [1, 0.8]);
      return (
        <AbsoluteFill>
          <Picture source={source} style={{filter: `blur(${24 * amount}px) brightness(${1 - 0.25 * amount})`, transform: 'scale(1.1)'}} />
          <AbsoluteFill style={{transform: `scale(${scale}) rotate(${-1.2 * amount}deg)`}}>
            <div style={{width: '100%', height: '100%', boxSizing: 'border-box', border: `${14 * u * amount}px solid #FFFFFF`, boxShadow: `0 ${20 * u}px ${60 * u}px rgba(0,0,0,${0.45 * amount})`, overflow: 'hidden'}}>
              <Picture source={source} />
            </div>
          </AbsoluteFill>
        </AbsoluteFill>
      );
    }
    case 'device_frame': {
      const scale = interpolate(amount, [0, 1], [1, 0.72]);
      const bezel = 22 * u;
      return (
        <AbsoluteFill>
          <Picture source={source} style={{filter: `blur(${30 * amount}px) brightness(${1 - 0.4 * amount})`, transform: 'scale(1.12)'}} />
          <AbsoluteFill style={{transform: `scale(${scale})`}}>
            <div
              style={{
                position: 'absolute',
                inset: 0,
                borderRadius: 90 * u * amount,
                border: `${bezel * amount}px solid #111214`,
                boxShadow: `0 ${30 * u}px ${80 * u}px rgba(0,0,0,${0.55 * amount})`,
                overflow: 'hidden',
              }}
            >
              <Picture source={source} />
              <div style={{position: 'absolute', top: 18 * u, left: '50%', width: 220 * u, height: 46 * u, marginLeft: -110 * u, borderRadius: 23 * u, background: '#111214', opacity: amount}} />
            </div>
          </AbsoluteFill>
        </AbsoluteFill>
      );
    }
    case 'split_mirror':
      return (
        <AbsoluteFill style={{flexDirection: 'row'}}>
          <Slice source={source} share={0.5} />
          <Slice source={source} share={0.5} mirrored style={{borderLeft: `${6 * u}px solid #FFFFFF`}} />
        </AbsoluteFill>
      );
    case 'triptych':
      return (
        <AbsoluteFill style={{flexDirection: 'row', background: '#FFFFFF', gap: 8 * u}}>
          <Slice source={source} share={0.3} style={{filter: 'saturate(0.6) brightness(0.85)'}} />
          <Slice source={source} share={0.4 - (16 * u) / width} />
          <Slice source={source} share={0.3} mirrored style={{filter: 'saturate(0.6) brightness(0.85)'}} />
        </AbsoluteFill>
      );
    case 'whip_blur': {
      const shift = interpolate(amount, [0, 1], [0, width * 0.08]);
      return (
        <AbsoluteFill style={{transform: `translateX(${shift}px) scale(1.1)`}}>
          <svg width={0} height={0} style={{position: 'absolute'}}>
            <filter id="whip-blur">
              <feGaussianBlur stdDeviation={`${60 * amount} 0`} />
            </filter>
          </svg>
          <Picture source={source} style={{filter: 'url(#whip-blur)'}} />
        </AbsoluteFill>
      );
    }
    case 'bw_flash':
      return (
        <AbsoluteFill>
          <Picture source={source} style={{filter: `grayscale(${amount}) contrast(${1 + 0.8 * amount}) brightness(${1 + 0.1 * amount})`}} />
          <AbsoluteFill style={{backgroundColor: '#FFFFFF', opacity: 0.55 * Math.max(0, 1 - amount * 2.5) * (amount > 0 ? 1 : 0)}} />
        </AbsoluteFill>
      );
    case 'tilt': {
      const angle = ((effect.tilt_deg ?? 4) * Math.PI) / 180;
      const theta = Math.abs(angle) * amount;
      // Just enough to keep the tilted picture covering the frame.
      const cover = Math.cos(theta) + (height / width) * Math.sin(theta);
      return (
        <AbsoluteFill style={{transform: `rotate(${(effect.tilt_deg ?? 4) * amount}deg) scale(${cover})`}}>
          <Picture source={source} />
        </AbsoluteFill>
      );
    }
    default:
      // tear, halftone_bg and speed_lines are layers over the plain picture.
      return <Picture source={source} />;
  }
};

/** A torn paper edge sweeping across the frame, with grain. */
const Tear: React.FC<{progress: number; seed: string}> = ({progress, seed}) => {
  const {width, height} = useVideoConfig();
  const x = interpolate(progress, [0, 1], [-width * 0.3, width * 1.3]);
  const teeth = 28;
  const points: string[] = [];
  for (let i = 0; i <= teeth; i++) {
    const y = (i / teeth) * height;
    const jag = (random(`${seed}-${i}`) - 0.5) * width * 0.06;
    points.push(`${x + jag},${y}`);
  }
  const back = `${x - width * 0.5},${height} ${x - width * 0.5},0`;
  return (
    <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
      <filter id="paper-grain">
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={3} />
        <feColorMatrix type="saturate" values="0" />
        <feComponentTransfer>
          <feFuncA type="linear" slope={0.35} />
        </feComponentTransfer>
        <feComposite in2="SourceGraphic" operator="in" />
      </filter>
      <polygon points={`${points.join(' ')} ${back}`} fill="#F4EFE6" />
      <polygon points={`${points.join(' ')} ${back}`} fill="#F4EFE6" filter="url(#paper-grain)" />
      <polyline points={points.join(' ')} fill="none" stroke="rgba(0,0,0,0.25)" strokeWidth={6} />
    </svg>
  );
};

/** A dot screen in the accent colour; translucent, the person not cut out. */
const Halftone: React.FC<{amount: number; accent: string}> = ({amount, accent}) => {
  const {height} = useVideoConfig();
  const step = Math.round(height / 120);
  return (
    <AbsoluteFill
      style={{
        opacity: 0.38 * amount,
        mixBlendMode: 'multiply',
        backgroundImage: `radial-gradient(circle, ${accent} ${step * 0.32}px, transparent ${step * 0.36}px)`,
        backgroundSize: `${step}px ${step}px`,
      }}
    />
  );
};

/** Lines rushing in from the edges, the centre kept clear; translucent. */
const SpeedLines: React.FC<{amount: number}> = ({amount}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const cx = width / 2;
  const cy = height * 0.42;
  const outer = Math.hypot(width, height);
  const inner = Math.min(width, height) * 0.42;
  const lines = Array.from({length: 48}, (_, i) => {
    const angle = (i / 48) * Math.PI * 2 + (random(`s-${i}-${Math.floor(frame / 2)}`) - 0.5) * 0.08;
    const start = inner * (1 + random(`r-${i}-${Math.floor(frame / 2)}`) * 0.35);
    const spread = 0.012 + random(`w-${i}`) * 0.01;
    const p = (r: number, a: number) => `${cx + Math.cos(a) * r},${cy + Math.sin(a) * r}`;
    return `${p(start, angle)} ${p(outer, angle - spread)} ${p(outer, angle + spread)}`;
  });
  return (
    <svg width={width} height={height} style={{position: 'absolute', inset: 0, opacity: 0.75 * amount}}>
      {lines.map((points, i) => (
        <polygon key={i} points={points} fill="#FFFFFF" />
      ))}
    </svg>
  );
};

/** The layer effects, drawn over the picture and under the graphics. */
export const EffectLayer: React.FC<{effects: PictureEffect[]; accent: string}> = ({effects, accent}) => {
  const {effect, amount, progress} = useActiveEffect(effects);
  if (!effect) {
    return null;
  }
  if (effect.type === 'tear') {
    return <Tear progress={progress} seed={`${effect.start}`} />;
  }
  if (effect.type === 'halftone_bg') {
    return <Halftone amount={amount} accent={accent} />;
  }
  if (effect.type === 'speed_lines') {
    return <SpeedLines amount={amount} />;
  }
  return null;
};
