import React from 'react';
import {Video} from '@remotion/media';
import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import type {MotionElement} from './types';

/**
 * A second shot cut in over the whole frame (`insert`) and a picture from the
 * project's prop library on its word (`prop`). The insert is muted: the voice
 * under it is the main recording's, muxed back after the render.
 */
export const INSERT_TYPES = new Set(['insert', 'prop']);

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

const Insert: React.FC<{element: MotionElement; durationInFrames: number}> = ({element, durationInFrames}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  if (!element.video_source) {
    return null;
  }
  const whoosh = element.cut_style === 'whoosh';
  const edge = Math.max(1, Math.round(fps * 0.15));
  const into = interpolate(frame, [0, edge], [1, 0], clamp);
  const out = interpolate(frame, [durationInFrames - edge, durationInFrames], [0, 1], clamp);
  const blur = whoosh ? 50 * Math.max(into, out) : 0;
  const shift = whoosh ? width * 0.12 * (into - out) : 0;
  return (
    <AbsoluteFill style={{backgroundColor: '#000', overflow: 'hidden'}}>
      <svg width={0} height={0} style={{position: 'absolute'}}>
        <filter id="insert-whip">
          <feGaussianBlur stdDeviation={`${blur} 0`} />
        </filter>
      </svg>
      <AbsoluteFill style={{transform: `translateX(${shift}px) scale(${whoosh ? 1.08 : 1})`, filter: blur > 0.5 ? 'url(#insert-whip)' : undefined}}>
        <Video
          src={staticFile(element.video_source)}
          muted
          trimBefore={Math.round((element.source_start ?? 0) * fps)}
          trimAfter={element.source_end ? Math.round(element.source_end * fps) : undefined}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Prop: React.FC<{element: MotionElement; durationInFrames: number; holdToEnd: boolean}> = ({
  element,
  durationInFrames,
  holdToEnd,
}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const box = element.box;
  if (!box || !element.image_source) {
    return null;
  }
  const u = height / 1920;
  const enter = spring({frame, fps, config: {damping: 14, stiffness: 180}});
  const exit = holdToEnd
    ? 1
    : interpolate(frame, [Math.max(0, durationInFrames - Math.round(fps * 0.2)), durationInFrames], [1, 0], clamp);
  const slide = element.entry === 'slide';
  const scale = slide ? 1 : interpolate(enter, [0, 1], [0.4, 1]);
  const dy = slide ? interpolate(enter, [0, 1], [height * 0.25, 0]) : 0;
  const screenshot = element.prop_style === 'screenshot';
  return (
    <AbsoluteFill style={{opacity: exit * Math.min(1, enter * 2)}}>
      <div
        style={{
          position: 'absolute',
          left: box.left * width,
          top: box.top * height,
          width: box.width * width,
          height: box.height * height,
          transform: `translateY(${dy}px) scale(${scale}) rotate(${screenshot ? 0 : -2}deg)`,
          boxSizing: 'border-box',
          padding: screenshot ? 12 * u : 0,
          background: screenshot ? '#FFFFFF' : 'transparent',
          borderRadius: screenshot ? 28 * u : 0,
          boxShadow: screenshot ? `0 ${18 * u}px ${50 * u}px rgba(0,0,0,0.45)` : undefined,
          filter: screenshot ? undefined : `drop-shadow(0 ${14 * u}px ${30 * u}px rgba(0,0,0,0.5))`,
          overflow: 'hidden',
        }}
      >
        <Img
          src={staticFile(element.image_source)}
          style={{width: '100%', height: '100%', objectFit: 'contain', borderRadius: screenshot ? 18 * u : 0}}
        />
      </div>
    </AbsoluteFill>
  );
};

export const InsertGraphic: React.FC<{element: MotionElement; durationInFrames: number; holdToEnd: boolean}> = (
  props,
) => (props.element.type === 'insert' ? <Insert {...props} /> : <Prop {...props} />);
