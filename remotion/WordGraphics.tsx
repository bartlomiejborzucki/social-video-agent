import React from 'react';
import {AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {MotionElement, SocialVideoProps} from './types';
import {rgba} from './SceneFrame';

/**
 * Graphics that illustrate what is said at the moment it is said: a habit
 * crossed out and replaced, a speech or message bubble, an icon over the
 * head, a process bar, a word built letter by letter, an image card. Each
 * takes the brand's colours and font, sits in the top zone over the head
 * unless the plan says otherwise, and moves on the times Python resolved
 * from the caption words, never on a timer of its own.
 */
export const WORD_GRAPHICS = new Set(['strike']);

type Props = {
  element: MotionElement;
  accent: string;
  secondary: string;
  font: string;
  durationInFrames: number;
  safeMargins: SocialVideoProps['safeMargins'];
  holdToEnd?: boolean;
};

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/** Seconds since the element started, and the entrance/exit envelope. */
const useEnvelope = (durationInFrames: number, holdToEnd: boolean) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const entrance = spring({frame, fps, config: {damping: 18, stiffness: 170}});
  const exit = holdToEnd
    ? 1
    : interpolate(frame, [Math.max(0, durationInFrames - Math.round(fps * 0.2)), durationInFrames], [1, 0], clamp);
  return {t: frame / fps, frame, fps, entrance, exit};
};

/** Scissors drawn for this project: two rings and two blades. */
const Scissors: React.FC<{size: number; colour: string}> = ({size, colour}) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" stroke={colour} strokeWidth={4} strokeLinecap="round">
    <circle cx={10} cy={14} r={6} />
    <circle cx={10} cy={34} r={6} />
    <path d="M15 17 L44 36 M15 31 L44 12" />
  </svg>
);

export const WordGraphic: React.FC<Props> = (props) => {
  if (props.element.type === 'strike') {
    return <Strike {...props} />;
  }
  return null;
};

/**
 * "Nie płacz!" appears, a stroke in the accent crosses it out on its word, and
 * "Widzę, że ci smutno." takes its place. The stroke is a background on the
 * text cloned per line, so a line that wraps is crossed out line by line.
 */
const Strike: React.FC<Props> = ({element, accent, secondary, font, durationInFrames, safeMargins, holdToEnd = false}) => {
  const {width, height} = useVideoConfig();
  const {t, entrance, exit} = useEnvelope(durationInFrames, holdToEnd);
  const u = height / 1920;
  const crossed = (element.strike_at ?? element.start + 1) - element.start;
  const replaced = (element.replace_at ?? element.start + 1.7) - element.start;
  const stroke = interpolate(t, [crossed, crossed + 0.3], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  const out = interpolate(t, [replaced, replaced + 0.25], [1, 0], clamp);
  const inside = interpolate(t, [replaced + 0.05, replaced + 0.4], [0, 1], {...clamp, easing: Easing.out(Easing.back(1.6))});
  const top = element.position !== 'center';
  const pad = {
    top: (height * safeMargins.top) / 100,
    left: (width * safeMargins.left) / 100,
    right: (width * safeMargins.right) / 100,
  };
  const markSize = 54 * u;
  const line: React.CSSProperties = {
    gridArea: '1 / 1',
    fontSize: 50 * u,
    fontWeight: 800,
    lineHeight: 1.2,
    textAlign: 'center',
  };
  return (
    <AbsoluteFill
      style={{
        justifyContent: top ? 'flex-start' : 'center',
        alignItems: 'center',
        paddingTop: top ? pad.top + 10 * u : undefined,
        paddingLeft: pad.left,
        paddingRight: pad.right,
        opacity: exit * entrance,
        fontFamily: font,
      }}
    >
      <div
        style={{
          position: 'relative',
          display: 'grid',
          background: 'rgba(255,255,255,0.96)',
          color: secondary,
          borderRadius: 30 * u,
          padding: `${26 * u}px ${34 * u}px`,
          maxWidth: '100%',
          boxShadow: `0 ${10 * u}px ${32 * u}px ${rgba(secondary, 0.3)}`,
          transform: `translateY(${interpolate(entrance, [0, 1], [-24 * u, 0])}px) scale(${0.92 + 0.08 * entrance})`,
        }}
      >
        <div style={{...line, opacity: out * (1 - 0.35 * stroke), transform: `translateY(${(1 - out) * -30 * u}px)`}}>
          <span
            style={{
              backgroundImage: `linear-gradient(${accent}, ${accent})`,
              backgroundRepeat: 'no-repeat',
              backgroundPosition: '0 58%',
              backgroundSize: `${stroke * 100}% ${0.14}em`,
              WebkitBoxDecorationBreak: 'clone',
              boxDecorationBreak: 'clone',
            }}
          >
            {element.text}
          </span>
        </div>
        <div style={{...line, opacity: inside, transform: `translateY(${(1 - inside) * 30 * u}px)`}}>
          {element.replacement}
        </div>
        {element.strike_mark === 'scissors' && stroke > 0 && out > 0 ? (
          <div
            style={{
              position: 'absolute',
              top: '50%',
              left: `calc(${34 * u}px + (100% - ${68 * u}px) * ${stroke})`,
              transform: `translate(-50%, -50%) rotate(${-12 + 24 * stroke}deg)`,
              opacity: out,
            }}
          >
            <Scissors size={markSize} colour={accent} />
          </div>
        ) : null}
        {element.strike_mark === 'cross' && stroke >= 1 && out > 0 ? (
          <div
            style={{
              position: 'absolute',
              right: -markSize / 3,
              top: -markSize / 3,
              width: markSize,
              height: markSize,
              borderRadius: markSize,
              background: accent,
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: markSize * 0.62,
              fontWeight: 900,
              opacity: out,
              transform: `scale(${interpolate(t, [crossed + 0.3, crossed + 0.5], [0.3, 1], clamp)})`,
            }}
          >
            ✗
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
