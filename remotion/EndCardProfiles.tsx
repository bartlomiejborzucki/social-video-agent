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
 * next, and a closing line. The title and the closing line arrive measured
 * from Python (`fitted`), like every end card; the rest is short by schema.
 * A person without a picture gets their initials in the brand's second colour.
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
  const portrait = (people.length <= 1 ? 380 : people.length === 2 ? 320 : 250) * u;
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
        padding: `${150 * u}px ${80 * u}px`,
        textAlign: 'center',
      }}
    >
      {element.kicker ? (
        <div
          style={{
            background: secondary,
            color: inkOn(secondary),
            fontSize: 30 * u,
            fontWeight: 700,
            letterSpacing: 4 * u,
            textTransform: 'uppercase',
            padding: `${12 * u}px ${30 * u}px`,
            borderRadius: 999,
            marginBottom: 44 * u,
            whiteSpace: 'nowrap',
          }}
        >
          {element.kicker}
        </div>
      ) : null}
      <div style={{maxWidth: fitted.max_width}}>{lines(fitted.title, 800, 1.1)}</div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          gap: (people.length === 3 ? 30 : 50) * u,
          marginTop: 70 * u,
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
            <div key={index} style={{width: portrait + 30 * u}}>
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
              <div style={{fontSize: 38 * u, fontWeight: 700, marginTop: 22 * u, lineHeight: 1.15}}>
                {person.name}
              </div>
              {person.handle ? (
                <div style={{fontSize: 27 * u, opacity: 0.72, marginTop: 6 * u}}>{person.handle}</div>
              ) : null}
            </div>
          );
        })}
      </div>
      {element.next_text ? (
        <div
          style={{
            background: accent,
            color: inkOn(accent),
            borderRadius: 28 * u,
            padding: `${26 * u}px ${44 * u}px`,
            marginTop: 80 * u,
            maxWidth: 880 * u,
            boxShadow: `0 ${10 * u}px ${30 * u}px ${rgba(accent, 0.35)}`,
          }}
        >
          {element.next_label ? (
            <div
              style={{
                fontSize: 25 * u,
                fontWeight: 700,
                letterSpacing: 4 * u,
                textTransform: 'uppercase',
                opacity: 0.85,
                marginBottom: 8 * u,
              }}
            >
              {element.next_label}
            </div>
          ) : null}
          <div style={{fontSize: 44 * u, fontWeight: 800, lineHeight: 1.15, textWrap: 'balance'}}>
            {element.next_text}
          </div>
        </div>
      ) : null}
      {fitted.secondary ? (
        <div style={{marginTop: 56 * u, opacity: 0.8}}>{lines(fitted.secondary, 500, 1.25)}</div>
      ) : null}
    </AbsoluteFill>
  );
};
