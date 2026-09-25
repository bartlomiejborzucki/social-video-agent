import React from 'react';
import {AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {MotionElement, SocialVideoProps} from './types';
import {entranceTransform, type StylePack} from './stylePacks';

type Props = {
  element: MotionElement;
  accent: string;
  text: string;
  background: string;
  font: string;
  durationInFrames: number;
  safeMargins: SocialVideoProps['safeMargins'];
  pack: StylePack;
};

export const DATA_GRAPHICS = new Set(['hook_card', 'chart', 'compare', 'steps']);

const chartValue = (item: string): {label: string; value: number; shown: string} => {
  const cut = item.lastIndexOf(':');
  const label = item.slice(0, cut).trim();
  const raw = item.slice(cut + 1).trim();
  const match = /-?\d+(?:[.,]\d+)?/.exec(raw);
  return {label, value: match ? Number(match[0].replace(',', '.')) : 0, shown: raw};
};

const splitLabel = (item: string): {label: string; body: string} => {
  const cut = item.indexOf(':');
  return {label: item.slice(0, cut).trim(), body: item.slice(cut + 1).trim()};
};

/**
 * The 1.2/1.3 graphics: the opening hook card and the three data graphics.
 * They take their shape from the style pack and their colours and font from
 * the brand contract, and stay inside the safe margins, above the caption area.
 */
export const DataGraphic: React.FC<Props> = ({
  element,
  accent,
  text,
  background,
  font,
  durationInFrames,
  safeMargins,
  pack,
}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const entrance = spring({frame, fps, config: {damping: 18, stiffness: 160}});
  const exit = interpolate(
    frame,
    [Math.max(0, durationInFrames - Math.round(fps * 0.2)), durationInFrames],
    [1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  const cardFill = pack.card === 'accent' ? accent : pack.card;
  const cardText = pack.card === 'accent' ? background : text;
  const side = {
    paddingLeft: (width * safeMargins.left) / 100,
    paddingRight: (width * safeMargins.right) / 100,
  };
  const heading: React.CSSProperties = {
    fontFamily: font,
    fontWeight: pack.weight,
    textTransform: pack.uppercase ? 'uppercase' : 'none',
    letterSpacing: pack.letterSpacing,
  };

  if (element.type === 'hook_card') {
    const sweep = interpolate(frame, [Math.round(fps * 0.15), Math.round(fps * 0.6)], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    });
    return (
      <AbsoluteFill style={{opacity: exit}}>
        <AbsoluteFill
          style={{background: `linear-gradient(180deg, ${background}CC 0%, ${background}66 55%, transparent 100%)`}}
        />
        <AbsoluteFill style={{...side, justifyContent: 'center', alignItems: 'center'}}>
          <div
            style={{
              ...heading,
              color: text,
              fontSize: Math.round(width * 0.105),
              lineHeight: 1.04,
              textAlign: 'center',
              maxWidth: '92%',
              transform: entranceTransform(pack, entrance),
              opacity: entrance,
              textShadow: '0 8px 40px rgba(0,0,0,0.45)',
            }}
          >
            {element.text}
          </div>
          <div
            style={{
              marginTop: 28,
              height: 14,
              width: `${46 * sweep}%`,
              borderRadius: 7,
              background: accent,
            }}
          />
          {element.secondary_text ? (
            <div style={{...heading, fontWeight: 600, color: text, fontSize: 40, marginTop: 24, opacity: sweep}}>
              {element.secondary_text}
            </div>
          ) : null}
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  const items = element.items ?? [];
  const card: React.CSSProperties = {
    background: cardFill,
    color: cardText,
    borderRadius: pack.radius,
    padding: '34px 40px',
    boxShadow: '0 18px 50px rgba(0,0,0,0.28)',
    borderLeft: pack.border === 'left' ? `12px solid ${accent}` : undefined,
    borderTop: pack.border === 'top' ? `8px solid ${accent}` : undefined,
    fontFamily: font,
    width: '100%',
  };
  const title = element.text ? (
    <div style={{...heading, fontSize: 46, marginBottom: 24}}>{element.text}</div>
  ) : null;
  const wrap = (content: React.ReactNode) => (
    <AbsoluteFill
      style={{
        ...side,
        justifyContent: 'center',
        paddingBottom: height * 0.18,
        opacity: exit,
      }}
    >
      <div style={{...card, transform: entranceTransform(pack, entrance), opacity: entrance}}>
        {title}
        {content}
      </div>
    </AbsoluteFill>
  );
  const reveal = (index: number, of: number) =>
    spring({frame: frame - (durationInFrames * 0.6 * index) / Math.max(1, of), fps, config: {damping: 20, stiffness: 170}});

  if (element.type === 'chart') {
    const values = items.map(chartValue);
    const max = Math.max(...values.map((item) => Math.abs(item.value)), 1);
    return wrap(
      values.map((item, index) => {
        const grow = reveal(index, values.length);
        return (
          <div key={`${index}-${item.label}`} style={{margin: '14px 0'}}>
            <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 34, fontWeight: 600}}>
              <span>{item.label}</span>
              <span style={{fontVariantNumeric: 'tabular-nums', opacity: grow}}>{item.shown}</span>
            </div>
            <div style={{height: 26, borderRadius: 13, background: 'rgba(255,255,255,0.14)', marginTop: 8}}>
              <div
                style={{
                  height: '100%',
                  width: `${(Math.abs(item.value) / max) * 100 * grow}%`,
                  borderRadius: 13,
                  background: pack.card === 'accent' ? background : accent,
                }}
              />
            </div>
          </div>
        );
      }),
    );
  }

  if (element.type === 'compare') {
    const [left, right] = items.map(splitLabel);
    const slideIn = (from: number, index: number) =>
      `translateX(${(1 - reveal(index, 2)) * from}px)`;
    return wrap(
      <div style={{display: 'flex', alignItems: 'stretch', gap: 20}}>
        {[left, right].map((side, index) => (
          <div
            key={side?.label ?? index}
            style={{
              flex: 1,
              borderRadius: Math.max(6, pack.radius - 6),
              padding: '22px 20px',
              // The second side is the point; it takes the colour the card is not.
              background:
                index === 1 ? (pack.card === 'accent' ? background : accent) : 'rgba(255,255,255,0.12)',
              color: index === 1 ? (pack.card === 'accent' ? accent : background) : cardText,
              transform: slideIn(index === 0 ? -60 : 60, index),
              opacity: reveal(index, 2),
            }}
          >
            <div style={{...heading, fontSize: 30, opacity: 0.85}}>{side?.label}</div>
            <div style={{fontSize: 44, fontWeight: 800, lineHeight: 1.1, marginTop: 10}}>{side?.body}</div>
          </div>
        ))}
      </div>,
    );
  }

  // steps
  return wrap(
    items.map((item, index) => {
      const shown = reveal(index, items.length);
      return (
        <div
          key={`${index}-${item}`}
          style={{display: 'flex', alignItems: 'center', gap: 22, margin: '14px 0', opacity: shown}}
        >
          <div
            style={{
              ...heading,
              width: 64,
              height: 64,
              flex: '0 0 auto',
              borderRadius: 32,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 34,
              background: pack.card === 'accent' ? background : accent,
              color: pack.card === 'accent' ? accent : background,
              transform: `scale(${0.6 + 0.4 * shown})`,
            }}
          >
            {index + 1}
          </div>
          <div style={{fontSize: 42, fontWeight: 700, lineHeight: 1.15}}>{item}</div>
        </div>
      );
    }),
  );
};
