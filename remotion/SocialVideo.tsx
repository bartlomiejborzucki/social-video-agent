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
import type {
  CaptionCue,
  CaptionStyle,
  CaptionWord,
  MotionElement,
  SocialVideoProps,
} from './types';

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

const Caption: React.FC<{
  cue: CaptionCue;
  style: CaptionStyle;
  font: string;
  height: number;
  width: number;
  safeMargins: SocialVideoProps['safeMargins'];
}> = ({
  cue,
  style,
  font,
  height,
  width,
  safeMargins,
}) => {
  const position = style.position;
  const vertical: React.CSSProperties =
    position === 'top'
      ? {justifyContent: 'flex-start', paddingTop: (height * style.margin_pct) / 100}
      : position === 'center'
        ? {justifyContent: 'center'}
        : {justifyContent: 'flex-end', paddingBottom: (height * style.margin_pct) / 100};
  const background = style.background_style === 'none' ? 'transparent' : style.background_colour;
  const words = style.highlight_active_word ? (cue.words ?? []) : [];
  return (
    <AbsoluteFill
      style={{
        ...vertical,
        alignItems: 'center',
        paddingLeft: (width * safeMargins.left) / 100,
        paddingRight: (width * safeMargins.right) / 100,
      }}
    >
      <div
        style={{
          display: '-webkit-box',
          WebkitBoxOrient: 'vertical',
          WebkitLineClamp: style.max_lines,
          overflow: 'hidden',
          maxWidth: '88%',
          padding: style.background_style === 'none' ? 0 : '14px 25px 17px',
          borderRadius: style.background_style === 'rounded_box' ? style.corner_radius : 0,
          background,
          color: style.primary_colour,
          fontFamily: font,
          fontWeight: style.bold ? 700 : 400,
          fontSize: Math.max(8, Math.round((height * style.font_size_pct) / 100)),
          lineHeight: 1.05,
          textAlign: 'center',
          WebkitTextStroke: style.outline_width > 0 ? `${style.outline_width}px ${style.outline_colour}` : undefined,
          textShadow: style.shadow > 0 ? `0 ${style.shadow}px ${style.shadow * 2}px ${style.outline_colour}` : undefined,
          whiteSpace: 'normal',
        }}
      >
        {words.length > 0 ? (
          <ActiveWords words={words} cueStart={cue.start} highlight={style.highlight_colour} />
        ) : (
          cue.text
        )}
      </div>
    </AbsoluteFill>
  );
};

/**
 * The active-word highlight the bold-caption brand contract asks for.
 *
 * The FFmpeg route has always drawn this with ASS \k timing. Until now the
 * Remotion route silently dropped the word timings and rendered flat text, so
 * the default renderer quietly produced something other than the contract.
 */
const ActiveWords: React.FC<{
  words: CaptionWord[];
  cueStart: number;
  highlight: string;
}> = ({words, cueStart, highlight}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // The sequence is offset to the cue, so add the cue start back to compare
  // against word times, which are on the output timeline.
  const now = cueStart + frame / fps;
  return (
    <>
      {words.map((word, index) => {
        const active = now >= word.start && now < word.end;
        return (
          <span key={`${word.start}-${index}`} style={{color: active ? highlight : undefined}}>
            {index === 0 ? '' : ' '}
            {word.text}
          </span>
        );
      })}
    </>
  );
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
  const plate = element.image_source ?? null;
  const dim = Math.min(90, Math.max(0, element.image_dim_pct ?? 45)) / 100;
  const isLower = element.type === 'lower_third';
  const isCallout = element.type === 'callout';

  return (
    <AbsoluteFill
      style={{
        justifyContent: isEnd ? 'center' : isLower ? 'flex-end' : isCallout ? 'center' : 'flex-start',
        alignItems: isEnd ? 'center' : isCallout ? 'center' : 'flex-start',
        padding: isEnd ? 90 : '140px 72px',
        paddingBottom: isLower ? 260 : undefined,
        background:
          isEnd && !plate
            ? `radial-gradient(circle at 50% 35%, ${accent}26 0%, ${background} 58%)`
            : 'transparent',
        fontFamily: font,
        opacity,
        transform: `translateY(${y}px)`,
      }}
    >
      {plate ? (
        <>
          <img
            src={staticFile(plate)}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              objectFit: 'cover',
            }}
          />
          <AbsoluteFill style={{backgroundColor: background, opacity: dim}} />
        </>
      ) : null}
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
      {props.logoSource && props.logoUsage !== 'none' ? (
        <img
          src={staticFile(props.logoSource)}
          style={{
            position: 'absolute',
            top: `${props.safeMargins.top}%`,
            right: `${props.safeMargins.right}%`,
            width: '16%',
            maxHeight: '10%',
            objectFit: 'contain',
          }}
        />
      ) : null}
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
      {props.captionStyle
        ? props.captions.map((cue) => {
            const from = Math.round(cue.start * props.fps);
            const duration = Math.max(1, Math.round((cue.end - cue.start) * props.fps));
            return (
              <Sequence key={`caption-${cue.index}`} from={from} durationInFrames={duration}>
                <Caption
                  cue={cue}
                  style={props.captionStyle as CaptionStyle}
                  font={props.fontFamily}
                  height={props.height}
                  width={props.width}
                  safeMargins={props.safeMargins}
                />
              </Sequence>
            );
          })
        : null}
    </AbsoluteFill>
  );
};
