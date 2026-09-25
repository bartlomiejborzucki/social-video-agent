import React, {useEffect, useState} from 'react';
import {Video} from '@remotion/media';
import {
  AbsoluteFill,
  Easing,
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
  CaptionLayout,
  CaptionStyle,
  CaptionWord,
  MotionElement,
  PunchIn,
  SocialVideoProps,
} from './types';
import {DATA_GRAPHICS, DataGraphic} from './DataGraphics';
import {stylePack} from './stylePacks';
import {useTransition} from './Transitions';

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

/**
 * Draw one cue exactly as Python measured it.
 *
 * There is deliberately no wrapping, clamping, ellipsis or overflow rule here.
 * The previous implementation used `display: -webkit-box` with
 * `WebkitLineClamp` and `overflow: hidden`, which is a UI idiom for shortening
 * a label: at 5% of a 1920px frame an ordinary Polish phrase overflowed two
 * lines and the browser replaced its ending with `...`. A subtitle is a
 * transcript, so the lines and the per-cue size arrive pre-computed and this
 * component only paints them.
 */
const Caption: React.FC<{
  cue: CaptionCue;
  style: CaptionStyle;
  layout: CaptionLayout;
  font: string;
  height: number;
  width: number;
  safeMargins: SocialVideoProps['safeMargins'];
}> = ({
  cue,
  style,
  layout,
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
  const boxed = style.background_style !== 'none';
  const background = boxed ? style.background_colour : 'transparent';
  const highlight = style.highlight_active_word;
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
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          maxWidth: layout.box_width_px,
          padding: boxed
            ? `${layout.padding_top}px ${layout.padding_x}px ${layout.padding_bottom}px`
            : 0,
          borderRadius: style.background_style === 'rounded_box' ? style.corner_radius : 0,
          background,
          color: style.primary_colour,
          fontFamily: font,
          fontWeight: style.bold ? 700 : 400,
          fontSize: cue.font_size_px,
          lineHeight: layout.line_height,
          textAlign: 'center',
          WebkitTextStroke: style.outline_width > 0 ? `${style.outline_width}px ${style.outline_colour}` : undefined,
          textShadow: style.shadow > 0 ? `0 ${style.shadow}px ${style.shadow * 2}px ${style.outline_colour}` : undefined,
        }}
      >
        {cue.lines.map((line, index) => (
          <div
            key={`line-${cue.index}-${index}`}
            // `pre` keeps the measured break: the browser must not re-wrap a
            // line Python already fitted, and must not collapse its spaces.
            style={{whiteSpace: 'pre'}}
          >
            {line.words && line.words.length > 0 ? (
              <ActiveWords
                words={line.words}
                cueStart={cue.start}
                highlight={highlight ? style.highlight_colour : undefined}
                emphasis={style.emphasis_colour}
                animation={highlight ? style.animation ?? 'none' : 'none'}
                boxText={boxed ? style.background_colour : '#111111'}
              />
            ) : (
              line.text
            )}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

/**
 * The active-word highlight and brand-keyword emphasis the contract asks for.
 *
 * The spoken word takes the highlight colour while it is spoken; a brand
 * keyword rests in the emphasis colour. The FFmpeg route draws the same thing
 * with timed ASS colour transforms.
 */
const ActiveWords: React.FC<{
  words: CaptionWord[];
  cueStart: number;
  highlight?: string;
  emphasis: string;
  animation?: 'none' | 'pop' | 'box';
  boxText?: string;
}> = ({words, cueStart, highlight, emphasis, animation = 'none', boxText = '#111111'}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // The sequence is offset to the cue, so add the cue start back to compare
  // against word times, which are on the output timeline.
  const now = cueStart + frame / fps;
  return (
    <>
      {words.map((word, index) => {
        const active = highlight !== undefined && now >= word.start && now < word.end;
        const colour = active ? highlight : word.emphasis ? emphasis : undefined;
        // pop springs the spoken word up; box slides a highlight behind it.
        // Both use transform and box-shadow, which never change the measured
        // layout, so a line cannot reflow or overflow while it animates.
        const since = now - word.start;
        // Kept small: a scaled word grows over the spaces beside it, so the
        // pop is mostly a lift, with just enough scale to read as a spring.
        const popped =
          active && animation === 'pop'
            ? interpolate(since, [0, 0.1, 0.28], [0, 1, 0.6], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              })
            : 0;
        const boxed = active && animation === 'box';
        return (
          <React.Fragment key={`${word.start}-${index}`}>
            {index === 0 ? '' : ' '}
            <span
              style={{
                display: 'inline-block',
                color: boxed ? boxText : colour,
                transform: `translateY(${-0.14 * popped}em) scale(${1 + 0.06 * popped})`,
                background: boxed ? highlight : undefined,
                boxShadow: boxed ? `0 0 0 0.14em ${highlight}` : undefined,
                borderRadius: boxed ? '0.18em' : undefined,
                WebkitTextStroke: boxed ? '0' : undefined,
              }}
            >
              {word.text}
            </span>
          </React.Fragment>
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
          // Positioned, so it paints above the plate. An absolutely positioned
          // background image otherwise covers this in-flow text, which hid the
          // end card's own words -- the one thing that must be drawn locally.
          position: 'relative',
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

const EXTENDED = new Set(['quote', 'stat', 'list', 'chapter', 'cta', 'progress', 'logo_reveal']);

/** Split "73,5%" into prefix, number, suffix so the number can count up. */
const splitFigure = (text: string): {prefix: string; value: number; decimals: number; comma: boolean; suffix: string} | null => {
  const match = /^(\D*?)(\d+(?:[.,]\d+)?)(.*)$/.exec(text);
  if (!match) {
    return null;
  }
  const digits = match[2];
  const comma = digits.includes(',');
  const fraction = digits.split(/[.,]/)[1] ?? '';
  return {
    prefix: match[1],
    value: Number(digits.replace(',', '.')),
    decimals: fraction.length,
    comma,
    suffix: match[3],
  };
};

/**
 * The graphics added in 1.0: pull quote, figure, list, chapter title, call to
 * action, progress bar and logo reveal. Same brand colours and typography as
 * the originals, same entrance and exit, and every one of them stays inside
 * the safe margins and clear of the caption area at the bottom.
 */
const ExtendedGraphic: React.FC<{
  element: MotionElement;
  accent: string;
  text: string;
  background: string;
  font: string;
  durationInFrames: number;
  logoSource: string | null;
  safeMargins: SocialVideoProps['safeMargins'];
}> = ({element, accent, text, background, font, durationInFrames, logoSource, safeMargins}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const entrance = spring({frame, fps, config: {damping: 20, stiffness: 170}});
  const exit = interpolate(
    frame,
    [Math.max(0, durationInFrames - Math.round(fps * 0.2)), durationInFrames],
    [1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  const opacity = interpolate(entrance, [0, 1], [0, 1]) * exit;
  const rise = interpolate(entrance, [0, 1], [28, 0]);
  const pad = {
    top: (height * safeMargins.top) / 100,
    right: (width * safeMargins.right) / 100,
    bottom: (height * safeMargins.bottom) / 100,
    left: (width * safeMargins.left) / 100,
  };
  const card: React.CSSProperties = {
    background: 'rgba(10, 11, 14, 0.82)',
    borderRadius: 18,
    color: text,
    fontFamily: font,
    boxShadow: '0 18px 50px rgba(0,0,0,0.28)',
  };

  if (element.type === 'progress') {
    const done = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    return (
      <AbsoluteFill style={{paddingTop: pad.top * 0.5, paddingLeft: pad.left, paddingRight: pad.right}}>
        <div style={{height: 10, borderRadius: 5, background: 'rgba(255,255,255,0.22)', opacity: exit}}>
          <div style={{height: '100%', width: `${done * 100}%`, borderRadius: 5, background: accent}} />
        </div>
      </AbsoluteFill>
    );
  }

  if (element.type === 'logo_reveal') {
    if (!logoSource) {
      return null;
    }
    const sweep = interpolate(entrance, [0, 1], [0, 1]);
    return (
      <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', opacity}}>
        <div style={{position: 'relative', width: width * 0.46, padding: 36}}>
          <div
            style={{
              position: 'absolute',
              inset: 0,
              borderRadius: 28,
              background,
              transform: `scaleX(${sweep})`,
              transformOrigin: 'left center',
              borderBottom: `10px solid ${accent}`,
            }}
          />
          <img
            src={staticFile(logoSource)}
            style={{position: 'relative', width: '100%', objectFit: 'contain', transform: `scale(${0.85 + 0.15 * sweep})`}}
          />
        </div>
      </AbsoluteFill>
    );
  }

  if (element.type === 'stat') {
    const figure = splitFigure(element.text);
    const count = interpolate(frame, [0, Math.min(fps, durationInFrames * 0.6)], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    });
    const shown = figure
      ? figure.prefix +
        (figure.value * count).toFixed(figure.decimals).replace('.', figure.comma ? ',' : '.') +
        figure.suffix
      : element.text;
    return (
      <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', opacity, transform: `translateY(${rise}px)`}}>
        <div style={{...card, padding: '36px 56px', textAlign: 'center', borderTop: `12px solid ${accent}`}}>
          <div style={{fontSize: 150, fontWeight: 900, lineHeight: 1, color: accent, fontVariantNumeric: 'tabular-nums'}}>
            {shown}
          </div>
          {element.secondary_text ? (
            <div style={{fontSize: 38, fontWeight: 600, marginTop: 16, maxWidth: 760}}>{element.secondary_text}</div>
          ) : null}
        </div>
      </AbsoluteFill>
    );
  }

  if (element.type === 'list') {
    const items = element.items ?? [];
    const window = Math.max(1, durationInFrames * 0.7);
    return (
      <AbsoluteFill style={{justifyContent: 'center', paddingLeft: pad.left + 24, paddingRight: pad.right + 24, opacity: exit}}>
        <div style={{...card, padding: '30px 38px'}}>
          {items.map((item, index) => {
            const at = (window / items.length) * index;
            const shown = spring({frame: frame - at, fps, config: {damping: 20, stiffness: 170}});
            return (
              <div
                key={`${index}-${item}`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 22,
                  fontSize: 48,
                  fontWeight: 700,
                  lineHeight: 1.2,
                  margin: '12px 0',
                  opacity: shown,
                  transform: `translateX(${interpolate(shown, [0, 1], [-40, 0])}px)`,
                }}
              >
                <span style={{width: 18, height: 18, borderRadius: 9, background: accent, flex: '0 0 auto'}} />
                {item}
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    );
  }

  if (element.type === 'quote') {
    return (
      <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', paddingLeft: pad.left, paddingRight: pad.right, opacity, transform: `translateY(${rise}px)`}}>
        <div style={{...card, padding: '40px 48px', maxWidth: 880}}>
          <div style={{fontSize: 140, lineHeight: 0.6, color: accent, fontWeight: 900}}>“</div>
          <div style={{fontSize: 56, fontWeight: 700, lineHeight: 1.15}}>{element.text}</div>
          {element.secondary_text ? (
            <div style={{fontSize: 34, fontWeight: 500, marginTop: 22, color: accent}}>— {element.secondary_text}</div>
          ) : null}
        </div>
      </AbsoluteFill>
    );
  }

  if (element.type === 'chapter') {
    const slide = interpolate(entrance, [0, 1], [-60, 0]);
    return (
      <AbsoluteFill style={{paddingTop: pad.top + 40, paddingLeft: pad.left, opacity: exit}}>
        <div style={{...card, alignSelf: 'flex-start', padding: '18px 30px', transform: `translateX(${slide}px)`, opacity: entrance}}>
          {element.secondary_text ? (
            <div style={{fontSize: 28, fontWeight: 700, letterSpacing: 3, textTransform: 'uppercase', color: accent}}>
              {element.secondary_text}
            </div>
          ) : null}
          <div style={{fontSize: 52, fontWeight: 800, lineHeight: 1.1}}>{element.text}</div>
        </div>
      </AbsoluteFill>
    );
  }

  // cta: above the caption area, which owns the bottom of the frame.
  const pulse = 1 + 0.04 * Math.sin((frame / fps) * Math.PI * 2);
  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: pad.bottom + height * 0.16, opacity}}>
      <div
        style={{
          fontFamily: font,
          fontSize: 46,
          fontWeight: 800,
          color: background,
          background: accent,
          padding: '20px 44px',
          borderRadius: 999,
          transform: `translateY(${rise}px) scale(${entrance >= 0.99 ? pulse : entrance})`,
          boxShadow: '0 16px 40px rgba(0,0,0,0.3)',
        }}
      >
        {element.text}
      </div>
    </AbsoluteFill>
  );
};

/**
 * The picture's scale and fixed point at this frame.
 *
 * Each punch-in eases in over a quarter of its length (at most 0.35 s), holds,
 * and eases back out, so the push reads as a deliberate move rather than a
 * jump. Outside every punch-in the picture is untouched.
 */
const usePunchIn = (punchIns: PunchIn[]): {scale: number; origin: string} => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const now = frame / fps;
  const active = punchIns.find((p) => now >= p.start && now < p.end);
  if (!active) {
    return {scale: 1, origin: '50% 50%'};
  }
  const ease = Math.min(0.35, (active.end - active.start) / 4);
  const amount = interpolate(
    now,
    [active.start, active.start + ease, active.end - ease, active.end],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)},
  );
  return {
    scale: 1 + (active.scale - 1) * amount,
    origin: `${active.focus_x * 100}% ${active.focus_y * 100}%`,
  };
};

export const SocialVideo: React.FC<SocialVideoProps> = (props) => {
  useProjectFont(props.fontFamily, props.fontSource);
  const punch = usePunchIn(props.punchIns ?? []);
  const cut = useTransition(props.transitions ?? []);
  const pack = stylePack(props.style);
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      <AbsoluteFill
        style={{
          overflow: 'hidden',
          transform: `translateX(${cut.shiftX}px) scale(${punch.scale * cut.scale})`,
          transformOrigin: punch.origin,
          filter: cut.blur > 0.05 ? `blur(${cut.blur}px)` : undefined,
        }}
      >
        <Video src={staticFile(props.source)} style={{width: '100%', height: '100%'}} />
      </AbsoluteFill>
      {cut.flash > 0.01 ? (
        <AbsoluteFill style={{backgroundColor: props.accentColor, opacity: cut.flash}} />
      ) : null}
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
            {DATA_GRAPHICS.has(element.type) ? (
              <DataGraphic
                element={element}
                accent={props.accentColor}
                text={props.textColor}
                background={props.backgroundColor}
                font={props.fontFamily}
                durationInFrames={duration}
                safeMargins={props.safeMargins}
                pack={pack}
              />
            ) : EXTENDED.has(element.type) ? (
              <ExtendedGraphic
                element={element}
                accent={props.accentColor}
                text={props.textColor}
                background={props.backgroundColor}
                font={props.fontFamily}
                durationInFrames={duration}
                logoSource={props.logoSource}
                safeMargins={props.safeMargins}
              />
            ) : (
              <MotionGraphic
                element={element}
                accent={props.accentColor}
                text={props.textColor}
                background={props.backgroundColor}
                font={props.fontFamily}
                durationInFrames={duration}
              />
            )}
          </Sequence>
        );
      })}
      {props.captionStyle && props.captionLayout
        ? props.captions.map((cue) => {
            const from = Math.round(cue.start * props.fps);
            const duration = Math.max(1, Math.round((cue.end - cue.start) * props.fps));
            return (
              <Sequence key={`caption-${cue.index}`} from={from} durationInFrames={duration}>
                <Caption
                  cue={cue}
                  style={props.captionStyle as CaptionStyle}
                  layout={props.captionLayout as CaptionLayout}
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
