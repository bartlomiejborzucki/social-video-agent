import React from 'react';
import {AbsoluteFill, Easing, interpolate, random, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {MotionElement, SocialVideoProps} from './types';
import {rgba} from './SceneFrame';

/**
 * The reel's title over the speaker (`hook_title`) and what comes next over
 * the last seconds (`end_teaser`). Neither is a card: the picture stays live
 * under it, and the captions keep running below. The lines were measured and
 * broken in Python; this draws them, word by word or with a pop, on marker
 * fields in the accent colour (`highlight`), in one pill (`pill`) or as
 * outlined text (`plain`). A subtitle ("part 1.") enters with a short glitch.
 */
export const TITLE_TYPES = new Set(['hook_title', 'end_teaser']);

type Props = {
  element: MotionElement;
  accent: string;
  secondary: string;
  text: string;
  font: string;
  durationInFrames: number;
  safeMargins: SocialVideoProps['safeMargins'];
  captionBackground: string;
  holdToEnd: boolean;
};

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

const key = (word: string): string =>
  Array.from(word.toLocaleLowerCase()).filter((ch) => /[\p{L}\p{N}]/u.test(ch)).join('');

export const TitleOverlay: React.FC<Props> = ({
  element,
  accent,
  secondary,
  text,
  font,
  durationInFrames,
  safeMargins,
  captionBackground,
  holdToEnd,
}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const u = height / 1920;
  const fitted = element.fitted;
  if (!fitted) {
    return null;
  }
  const style = element.title_style ?? 'highlight';
  const entry = element.entry ?? 'typewriter';
  const fontPx = fitted.title.font_px;
  const emphasis = new Set(element.emphasis_keys ?? []);
  const words = fitted.title.lines.map((line) => line.split(' '));
  const total = words.reduce((sum, line) => sum + line.length, 0);
  // Typewriter: every word is in by 0.4 s; pop: the whole title springs in.
  const typeSpan = Math.max(1, Math.round(fps * 0.4));
  const pop = spring({frame, fps, config: {damping: 13, stiffness: 190}});
  const exit = holdToEnd
    ? 1
    : interpolate(frame, [Math.max(0, durationInFrames - Math.round(fps * 0.2)), durationInFrames], [1, 0], clamp);
  const position = element.position ?? (element.type === 'end_teaser' ? 'above_captions' : 'top');
  const top =
    position === 'center'
      ? height * 0.38
      : position === 'above_captions'
        ? height * 0.5
        : height * (safeMargins.top / 100) + 120 * u;
  const padX = 28 * u;
  const padY = 10 * u;
  let seen = 0;
  const lineNodes = words.map((line, lineIndex) => {
    const wordNodes = line.map((word, wordIndex) => {
      const order = seen++;
      const appears =
        entry === 'typewriter' ? Math.round((order / Math.max(1, total)) * typeSpan) : 0;
      const visible = frame >= appears ? 1 : 0;
      const marked = emphasis.has(key(word));
      return (
        <span
          key={`w-${lineIndex}-${wordIndex}`}
          style={{
            opacity: visible,
            color: marked ? (style === 'highlight' ? secondary : accent) : text,
          }}
        >
          {wordIndex > 0 ? ' ' : ''}
          {word}
        </span>
      );
    });
    const lineIn = entry === 'pop' ? pop : 1;
    return (
      <div
        key={`l-${lineIndex}`}
        style={{
          display: 'inline-block',
          alignSelf: 'center',
          padding: style === 'pill' ? 0 : `${padY}px ${padX}px`,
          background: style === 'highlight' ? accent : 'transparent',
          border: style === 'highlight' ? `${Math.max(2, 4 * u)}px solid ${rgba(text, 0.9)}` : 'none',
          borderRadius: style === 'highlight' ? 8 * u : 0,
          marginTop: lineIndex > 0 && style === 'highlight' ? -Math.max(2, 4 * u) : 0,
          transform: `scale(${interpolate(lineIn, [0, 1], [0.6, 1])})`,
          whiteSpace: 'pre',
          WebkitTextStroke: style === 'plain' ? `${Math.max(2, fontPx * 0.08)}px #000` : undefined,
          paintOrder: 'stroke fill',
        }}
      >
        {wordNodes}
      </div>
    );
  });
  // The subtitle comes in 40 % of the way through, with a short glitch.
  const subtitleAt = Math.round(durationInFrames * 0.4);
  const since = frame - subtitleAt;
  const glitching = since >= 0 && since < Math.round(fps * 0.25);
  const jitter = glitching ? (random(`g-${frame}`) - 0.5) * 18 * u : 0;
  return (
    <AbsoluteFill style={{opacity: exit}}>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          fontFamily: font,
          fontWeight: 900,
          fontSize: fontPx,
          lineHeight: 1.12,
          color: text,
          textAlign: 'center',
        }}
      >
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            padding: style === 'pill' ? `${padY * 1.6}px ${padX * 1.4}px` : 0,
            background: style === 'pill' ? secondary : 'transparent',
            borderRadius: style === 'pill' ? fontPx : 0,
          }}
        >
          {lineNodes}
        </div>
        {element.subtitle && since >= 0 ? (
          <div
            style={{
              marginTop: 14 * u,
              padding: `${6 * u}px ${18 * u}px`,
              background: captionBackground,
              color: captionBackground.toUpperCase() === '#FFFFFF' ? '#000000' : text,
              fontSize: Math.round(fontPx * 0.5),
              fontWeight: 800,
              transform: `translateX(${jitter}px)`,
              opacity: interpolate(since, [0, Math.round(fps * 0.12)], [0, 1], {
                ...clamp,
                easing: Easing.out(Easing.cubic),
              }),
              textShadow: glitching ? `${3 * u}px 0 ${accent}, ${-3 * u}px 0 ${secondary}` : undefined,
            }}
          >
            {element.subtitle}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
