import React from 'react';
import {AbsoluteFill, Easing, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
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
export const WORD_GRAPHICS = new Set(['strike', 'bubble', 'icon', 'process']);

type Props = {
  element: MotionElement;
  accent: string;
  secondary: string;
  brandColors?: string[];
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
  if (props.element.type === 'bubble') {
    return <Bubble {...props} />;
  }
  if (props.element.type === 'icon') {
    return <Icon {...props} />;
  }
  if (props.element.type === 'process') {
    return <Process {...props} />;
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

/**
 * A line said (speech, with a tail at the speaker or out of the frame) or a
 * message received (with a notification dot), popping in over the head on
 * its word. A fixed-size bubble in the top zone: never a card over the shot.
 */
const Bubble: React.FC<Props> = ({element, accent, secondary, font, durationInFrames, safeMargins, holdToEnd = false}) => {
  const {width, height} = useVideoConfig();
  const {frame, fps, exit} = useEnvelope(durationInFrames, holdToEnd);
  const u = height / 1920;
  const pop = spring({frame, fps, config: {damping: 10, stiffness: 210}});
  const message = element.variant === 'message';
  const tail = element.tail ?? 'speaker';
  const tailSize = 34 * u;
  const pad = {
    top: (height * safeMargins.top) / 100,
    left: (width * safeMargins.left) / 100,
    right: (width * safeMargins.right) / 100,
  };
  // The tail grows from the bubble's lower edge: centred over the speaker,
  // or at a corner when the voice comes from off the frame on that side.
  const tailLeft = tail === 'left' ? '14%' : tail === 'right' ? '86%' : '50%';
  const tailSkew = tail === 'left' ? -28 : tail === 'right' ? 28 : 0;
  const dot = 32 * u;
  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-start',
        alignItems: 'center',
        paddingTop: pad.top + 10 * u,
        paddingLeft: pad.left,
        paddingRight: pad.right,
        fontFamily: font,
        opacity: exit * Math.min(1, pop * 2),
      }}
    >
      <div
        style={{
          position: 'relative',
          maxWidth: '100%',
          background: '#FFFFFF',
          color: secondary,
          borderRadius: (message ? 26 : 44) * u,
          padding: `${28 * u}px ${36 * u}px`,
          boxShadow: `0 ${10 * u}px ${30 * u}px ${rgba(secondary, 0.3)}`,
          transform: `scale(${interpolate(pop, [0, 1], [0.55, 1])})`,
          transformOrigin: tail === 'left' ? '14% 100%' : tail === 'right' ? '86% 100%' : '50% 100%',
          textAlign: message ? 'left' : 'center',
          borderLeft: message ? `${8 * u}px solid ${accent}` : undefined,
        }}
      >
        {element.secondary_text ? (
          <div style={{fontSize: 30 * u, fontWeight: 700, lineHeight: 1.3, opacity: 0.7, marginBottom: 6 * u}}>
            {element.secondary_text}
          </div>
        ) : null}
        <div style={{fontSize: 46 * u, fontWeight: 800, lineHeight: 1.2}}>{element.text}</div>
        {message ? (
          <div
            style={{
              position: 'absolute',
              top: -dot / 3,
              right: -dot / 3,
              width: dot,
              height: dot,
              borderRadius: dot,
              background: accent,
              border: `${4 * u}px solid #FFFFFF`,
              transform: `scale(${interpolate(frame / fps, [0.15, 0.35], [0, 1], clamp)})`,
            }}
          />
        ) : (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: tailLeft,
              width: 0,
              height: 0,
              borderLeft: `${tailSize * 0.6}px solid transparent`,
              borderRight: `${tailSize * 0.6}px solid transparent`,
              borderTop: `${tailSize}px solid #FFFFFF`,
              marginTop: -1,
              transform: `translateX(-50%) skewX(${tailSkew}deg)`,
            }}
          />
        )}
      </div>
    </AbsoluteFill>
  );
};

/**
 * The thing just named, as a small flat icon over the head: a white disc with
 * an accent rim, the icon's strokes in the brand's second colour. The SVG is
 * the set's own file, painted through a mask so it takes the brand colour.
 */
const Icon: React.FC<Props> = ({element, accent, secondary, durationInFrames}) => {
  const {width, height} = useVideoConfig();
  const {frame, fps} = useEnvelope(durationInFrames, false);
  const size = ((element.size_pct ?? 9) / 100) * height;
  const pop = spring({frame, fps, config: {damping: 9, stiffness: 230}});
  const leave = interpolate(frame, [Math.max(0, durationInFrames - Math.round(fps * 0.15)), durationInFrames], [1, 0], clamp);
  const source = element.icon_source ? `url(${staticFile(element.icon_source)})` : undefined;
  const u = height / 1920;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          left: (element.x_pct ?? 0.5) * width - size / 2,
          top: (element.y_pct ?? 0.17) * height - size / 2,
          width: size,
          height: size,
          borderRadius: size,
          background: '#FFFFFF',
          border: `${8 * u}px solid ${accent}`,
          boxShadow: `0 ${8 * u}px ${24 * u}px ${rgba(secondary, 0.35)}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          opacity: leave * Math.min(1, pop * 3),
          transform: `scale(${interpolate(pop, [0, 1], [0.2, 1])}) rotate(${interpolate(pop, [0, 1], [-14, 0])}deg)`,
        }}
      >
        <div
          style={{
            width: size * 0.62,
            height: size * 0.62,
            backgroundColor: secondary,
            WebkitMaskImage: source,
            maskImage: source,
            WebkitMaskSize: 'contain',
            maskSize: 'contain',
            WebkitMaskRepeat: 'no-repeat',
            maskRepeat: 'no-repeat',
            WebkitMaskPosition: 'center',
            maskPosition: 'center',
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

/**
 * A process as a bar: each stage enters in a brand colour on its word, then a
 * pointer runs through the stages and the closing state arrives with a tick.
 * A card in the brand's second colour, so its stages never take that colour.
 */
const Process: React.FC<Props> = ({element, accent, secondary, brandColors = [], font, durationInFrames, safeMargins, holdToEnd = false}) => {
  const {width, height} = useVideoConfig();
  const {t, frame, fps, entrance, exit} = useEnvelope(durationInFrames, holdToEnd);
  const u = height / 1920;
  const items = element.items ?? [];
  const length = element.end - element.start;
  const palette = brandColors.filter((c) => c.toUpperCase() !== secondary.toUpperCase());
  const colours = palette.length > 0 ? palette : [accent];
  // On its word when the plan anchors it; otherwise over the first half.
  const enters = items.map((_, index) =>
    element.item_times?.[index] !== undefined && element.item_times?.[index] !== null
      ? (element.item_times[index] as number) - element.start
      : (length * 0.5 * index) / Math.max(1, items.length),
  );
  const last = enters[enters.length - 1] ?? 0;
  const runFrom = last + 0.45;
  const runTo = Math.max(runFrom + 0.3, Math.min(runFrom + 1.2, length - 0.9));
  const run = interpolate(t, [runFrom, runTo], [0, 1], {...clamp, easing: Easing.inOut(Easing.cubic)});
  const done = element.done_text ? spring({frame: frame - runTo * fps, fps, config: {damping: 12, stiffness: 200}}) : 0;
  const pad = {
    top: (height * safeMargins.top) / 100,
    left: (width * safeMargins.left) / 100,
    right: (width * safeMargins.right) / 100,
  };
  const labelPx = (items.length > 4 ? 26 : 30) * u;
  const barH = 40 * u;
  const knob = 30 * u;
  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-start',
        paddingTop: pad.top + 10 * u,
        paddingLeft: pad.left,
        paddingRight: pad.right,
        fontFamily: font,
        opacity: exit,
      }}
    >
      <div
        style={{
          background: rgba(secondary, 0.92),
          border: `${4 * u}px solid rgba(255,255,255,0.95)`,
          borderRadius: 30 * u,
          padding: `${26 * u}px ${30 * u}px`,
          color: '#FFFFFF',
          display: 'flex',
          flexDirection: 'column',
          gap: 16 * u,
          opacity: entrance,
          transform: `translateY(${interpolate(entrance, [0, 1], [-28 * u, 0])}px)`,
        }}
      >
        {element.text ? (
          <div style={{fontSize: 46 * u, fontWeight: 800, lineHeight: 1.2}}>{element.text}</div>
        ) : null}
        <div style={{position: 'relative', display: 'flex', gap: 8 * u, height: barH}}>
          {items.map((item, index) => {
            const shown = spring({frame: frame - enters[index] * fps, fps, config: {damping: 16, stiffness: 190}});
            return (
              <div
                key={`${index}-${item}`}
                style={{
                  flex: 1,
                  borderRadius: barH / 2,
                  background: colours[index % colours.length],
                  transform: `scaleX(${shown})`,
                  transformOrigin: 'left center',
                  opacity: Math.min(1, shown * 2),
                }}
              />
            );
          })}
          {run > 0 ? (
            <div
              style={{
                position: 'absolute',
                top: (barH - knob) / 2,
                left: `calc((100% - ${knob}px) * ${run})`,
                width: knob,
                height: knob,
                borderRadius: knob,
                background: '#FFFFFF',
                boxShadow: `0 0 0 ${5 * u}px ${rgba('#FFFFFF', 0.35)}`,
              }}
            />
          ) : null}
        </div>
        <div style={{display: 'flex', gap: 8 * u}}>
          {items.map((item, index) => {
            const shown = interpolate(t, [enters[index], enters[index] + 0.25], [0, 1], clamp);
            return (
              <div
                key={`label-${index}-${item}`}
                style={{flex: 1, fontSize: labelPx, fontWeight: 700, lineHeight: 1.3, textAlign: 'center', opacity: shown, whiteSpace: 'nowrap'}}
              >
                {item}
              </div>
            );
          })}
        </div>
        {element.done_text ? (
          <div
            style={{
              alignSelf: 'center',
              display: 'flex',
              alignItems: 'center',
              gap: 12 * u,
              fontSize: 40 * u,
              fontWeight: 800,
              lineHeight: 1.3,
              color: secondary,
              background: '#FFFFFF',
              borderRadius: 999,
              padding: `${4 * u}px ${26 * u}px`,
              opacity: Math.min(1, done * 2),
              transform: `scale(${interpolate(done, [0, 1], [0.6, 1])})`,
            }}
          >
            <span style={{color: accent, fontWeight: 900}}>✓</span>
            <span>{element.done_text}</span>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
