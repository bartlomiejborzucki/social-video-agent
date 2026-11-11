import React from 'react';
import {AbsoluteFill, Img, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {rgba} from './SceneFrame';
import type {FittedBlock, FittedCard, MotionElement} from './types';

/** Black or white, whichever reads on a fill of this colour. */
const inkOn = (hex: string): string => {
  const value = hex.replace('#', '');
  const channel = (at: number) => parseInt(value.slice(at, at + 2), 16) / 255;
  const luma = 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
  return luma > 0.6 ? '#14181F' : '#FFFFFF';
};

const initials = (name: string): string =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');

/**
 * An end card with people on it: who the viewer just watched and where to
 * find them, what comes next, and the ask.
 *
 * From the top: a kicker pill (a series name and part), the title, one to
 * three round portraits with a name and a handle each, a box with what comes
 * next, and a closing line. Every size and every line break arrives measured
 * from Python (`fitted`), like every end card: the card fills the frame, and
 * a long name or handle shrinks all of them together rather than wrapping in
 * the browser. A person without a picture gets their initials in the brand's
 * second colour.
 */
export const ProfilesEndCard: React.FC<{
  element: MotionElement;
  fitted: FittedCard;
  accent: string;
  secondary: string;
  text: string;
  background: string;
  font: string;
  opacity: number;
  y: number;
}> = ({element, fitted, accent, secondary, text, background, font, opacity, y}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  const u = height / 1920;
  const people = element.people ?? [];
  const row = fitted.people;
  if (!row) {
    return null;
  }
  const portrait = row.portrait;
  const lines = (block: FittedBlock, weight: number, lineHeight: number) =>
    block.lines.map((line, index) => (
      <div
        key={index}
        style={{fontSize: block.font_px, fontWeight: weight, lineHeight, whiteSpace: 'nowrap'}}
      >
        {line === '' ? ' ' : line}
      </div>
    ));
  return (
    <AbsoluteFill
      style={{
        fontFamily: font,
        opacity,
        transform: `translateY(${y}px)`,
        // A tint of the accent over the solid background. The tint fades to
        // nothing, not to the background colour: a see-through centre would
        // show the picture underneath.
        background: `radial-gradient(circle at 50% 30%, ${rgba(accent, 0.14)} 0%, ${rgba(accent, 0)} 62%), ${background}`,
        color: text,
        alignItems: 'center',
        justifyContent: 'center',
        padding: `${120 * u}px ${80 * u}px`,
        textAlign: 'center',
      }}
    >
      {element.kicker ? (
        <div
          style={{
            background: secondary,
            color: inkOn(secondary),
            fontSize: 32 * u,
            fontWeight: 700,
            letterSpacing: 4 * u,
            textTransform: 'uppercase',
            padding: `${13 * u}px ${32 * u}px`,
            borderRadius: 999,
            marginBottom: 40 * u,
            whiteSpace: 'nowrap',
          }}
        >
          {element.kicker}
        </div>
      ) : null}
      <div style={{maxWidth: fitted.max_width}}>{lines(fitted.title, 800, 1.08)}</div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'flex-start',
          gap: row.gap,
          marginTop: 64 * u,
        }}
      >
        {people.map((person, index) => {
          // Each portrait pops in a beat after the one before it.
          const pop = spring({
            frame: frame - Math.round(fps * (0.15 + index * 0.12)),
            fps,
            config: {damping: 13, stiffness: 180},
          });
          return (
            <div key={index} style={{width: row.column}}>
              <div
                style={{
                  width: portrait,
                  height: portrait,
                  margin: '0 auto',
                  borderRadius: '50%',
                  overflow: 'hidden',
                  border: `${8 * u}px solid ${accent}`,
                  boxSizing: 'border-box',
                  background: secondary,
                  color: inkOn(secondary),
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: portrait * 0.34,
                  fontWeight: 800,
                  transform: `scale(${0.6 + 0.4 * pop})`,
                  opacity: Math.min(1, pop * 1.5),
                  boxShadow: `0 ${10 * u}px ${34 * u}px ${rgba('#141828', 0.22)}`,
                }}
              >
                {person.image_source ? (
                  <Img
                    src={staticFile(person.image_source)}
                    style={{width: '100%', height: '100%', objectFit: 'cover'}}
                  />
                ) : (
                  initials(person.name)
                )}
              </div>
              <div
                style={{fontSize: row.name_px, fontWeight: 700, marginTop: 24 * u, lineHeight: 1.15}}
              >
                {(row.names[index] ?? [person.name]).map((line, at) => (
                  <div key={at} style={{whiteSpace: 'nowrap'}}>
                    {line}
                  </div>
                ))}
              </div>
              {person.handle ? (
                <div
                  style={{
                    fontSize: row.handle_px,
                    opacity: 0.78,
                    marginTop: 8 * u,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {person.handle}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      {fitted.next ? (
        <div
          style={{
            background: accent,
            color: inkOn(accent),
            borderRadius: 36 * u,
            padding: `${30 * u}px ${48 * u}px`,
            marginTop: 72 * u,
            width: fitted.max_width,
            boxSizing: 'border-box',
            boxShadow: `0 ${12 * u}px ${36 * u}px ${rgba(accent, 0.35)}`,
          }}
        >
          {element.next_label ? (
            <div
              style={{
                fontSize: 31 * u,
                fontWeight: 700,
                letterSpacing: 3 * u,
                textTransform: 'uppercase',
                opacity: 0.88,
                marginBottom: 8 * u,
              }}
            >
              {element.next_label}
            </div>
          ) : null}
          {lines(fitted.next, 800, 1.12)}
        </div>
      ) : null}
      {fitted.secondary ? (
        <div style={{marginTop: 56 * u, opacity: 0.85}}>{lines(fitted.secondary, 600, 1.25)}</div>
      ) : null}
    </AbsoluteFill>
  );
};
