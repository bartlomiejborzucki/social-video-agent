import React, {useEffect, useState} from 'react';
import {Video} from '@remotion/media';
import {
  AbsoluteFill,
  Sequence,
  cancelRender,
  continueRender,
  delayRender,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import type {MotionElement, SocialVideoProps} from './types';

const useProjectFont = (family: string, source: string | null): void => {
  const [handle] = useState(() => delayRender('Load project motion-design font'));
  useEffect(() => {
    if (!source) {
      continueRender(handle);
      return;
    }
    const face = new FontFace(family, `url(${staticFile(source)})`);
    face
      .load()
      .then((loaded) =>
        (document.fonts as unknown as {add: (font: FontFace) => void}).add(loaded),
      )
      .then(() => continueRender(handle))
      .catch((error: unknown) => cancelRender(error));
  }, [family, handle, source]);
};

const MotionGraphic: React.FC<{
  element: MotionElement;
  accent: string;
  text: string;
  background: string;
  font: string;
  durationInFrames: number;
}> = ({element, accent, text, background, font, durationInFrames}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const entrance = spring({frame, fps, config: {damping: 20, stiffness: 170}});
  const exit = interpolate(
    frame,
    [Math.max(0, durationInFrames - Math.round(fps * 0.2)), durationInFrames],
    [1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  const opacity = interpolate(entrance, [0, 1], [0, 1]) * exit;
  const y = interpolate(entrance, [0, 1], [32, 0]);
  const isEnd = element.type === 'end_card';
  const isLower = element.type === 'lower_third';
  const isCallout = element.type === 'callout';

  return (
    <AbsoluteFill
      style={{
        justifyContent: isEnd ? 'center' : isLower ? 'flex-end' : isCallout ? 'center' : 'flex-start',
        alignItems: isEnd ? 'center' : isCallout ? 'center' : 'flex-start',
        padding: isEnd ? 90 : '140px 72px',
        paddingBottom: isLower ? 260 : undefined,
        background: isEnd
          ? `radial-gradient(circle at 50% 35%, ${accent}26 0%, ${background} 58%)`
          : 'transparent',
        fontFamily: font,
        opacity,
        transform: `translateY(${y}px)`,
      }}
    >
      <div
        style={{
          maxWidth: isCallout ? 820 : 900,
          borderLeft: isEnd ? undefined : `12px solid ${accent}`,
          padding: isEnd ? 0 : '22px 30px',
          background: isEnd ? 'transparent' : 'rgba(10, 11, 14, 0.82)',
          borderRadius: 18,
          color: text,
          textAlign: isEnd || isCallout ? 'center' : 'left',
          boxShadow: isEnd ? 'none' : '0 18px 50px rgba(0,0,0,0.28)',
        }}
      >
        <div style={{fontSize: isEnd ? 72 : 58, fontWeight: 800, lineHeight: 1.05}}>
          {element.text}
        </div>
        {element.secondary_text ? (
          <div style={{fontSize: 34, fontWeight: 500, lineHeight: 1.2, marginTop: 18}}>
            {element.secondary_text}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const SocialVideo: React.FC<SocialVideoProps> = (props) => {
  useProjectFont(props.fontFamily, props.fontSource);
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      <Video src={staticFile(props.source)} style={{width: '100%', height: '100%'}} />
      {props.elements.map((element, index) => {
        const from = Math.round(element.start * props.fps);
        const duration = Math.max(1, Math.round((element.end - element.start) * props.fps));
        return (
          <Sequence key={`${element.type}-${index}`} from={from} durationInFrames={duration}>
            <MotionGraphic
              element={element}
              accent={props.accentColor}
              text={props.textColor}
              background={props.backgroundColor}
              font={props.fontFamily}
              durationInFrames={duration}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
