import React, {useEffect, useState} from 'react';
import {Video} from '@remotion/media';
import {
  AbsoluteFill,
  Easing,
  Img,
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
  FittedBlock,
  FittedCard,
  MotionElement,
  PunchIn,
  Shake,
  SocialVideoProps,
} from './types';
import {DATA_GRAPHICS, DataGraphic} from './DataGraphics';
import {SceneFrame, rgba} from './SceneFrame';
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
  holdToEnd?: boolean;
}> = ({element, accent, text, background, font, durationInFrames, holdToEnd = false}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const entrance = spring({frame, fps, config: {damping: 20, stiffness: 170}});
  // An element that runs to the last frame of the video stays on it: fading
  // out there would end the video on whatever is underneath.
  const exit = holdToEnd
    ? 1
    : interpolate(
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

  if (isEnd && element.fitted) {
    return (
      <EndCard
        element={element}
        fitted={element.fitted}
        plate={plate}
        dim={dim}
        accent={accent}
        text={text}
        background={background}
        font={font}
        opacity={opacity}
        y={y}
      />
    );
  }

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
          <Img
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

/**
 * The end card, drawn from lines measured in Python: no wrapping here, so a
 * link is never split, and the sizes are the ones that were checked to fit.
 * ``image_top`` puts the whole image (a book cover) above the text instead of
 * dimming it behind the words.
 */
const EndCard: React.FC<{
  element: MotionElement;
  fitted: FittedCard;
  plate: string | null;
  dim: number;
  accent: string;
  text: string;
  background: string;
  font: string;
  opacity: number;
  y: number;
}> = ({element, fitted, plate, dim, accent, text, background, font, opacity, y}) => {
  const {height} = useVideoConfig();
  const u = height / 1920;
  const imageTop = element.layout === 'image_top' && plate !== null;
  const lines = (block: FittedBlock, weight: number, lineHeight: number) =>
    block.lines.map((line, index) => (
      <div
        key={index}
        style={{fontSize: block.font_px, fontWeight: weight, lineHeight, whiteSpace: 'nowrap'}}
      >
        {line === '' ? '\u00a0' : line}
      </div>
    ));
  const words = (
    <div style={{position: 'relative', color: text, textAlign: 'center', maxWidth: fitted.max_width}}>
      {lines(fitted.title, 800, 1.08)}
      {fitted.secondary ? (
        <div style={{marginTop: 22 * u}}>{lines(fitted.secondary, 500, 1.25)}</div>
      ) : null}
    </div>
  );
  return (
    <AbsoluteFill
      style={{
        fontFamily: font,
        opacity,
        transform: `translateY(${y}px)`,
        background: imageTop || !plate
          ? `radial-gradient(circle at 50% 35%, ${accent}26 0%, ${background} 58%)`
          : 'transparent',
        alignItems: 'center',
        justifyContent: imageTop ? 'flex-start' : 'center',
        padding: 90 * u,
      }}
    >
      {plate && !imageTop ? (
        <>
          <Img
            src={staticFile(plate)}
            style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}}
          />
          <AbsoluteFill style={{backgroundColor: background, opacity: dim}} />
        </>
      ) : null}
      {imageTop && plate ? (
        <Img
          src={staticFile(plate)}
          style={{
            width: '100%',
            height: '50%',
            marginTop: 60 * u,
            objectFit: 'contain',
            flexShrink: 0,
          }}
        />
      ) : null}
      <div
        style={{
          display: 'flex',
          flex: imageTop ? 1 : undefined,
          alignItems: 'center',
          justifyContent: 'center',
          marginTop: imageTop ? 40 * u : 0,
        }}
      >
        {words}
      </div>
    </AbsoluteFill>
  );
};

const EXTENDED = new Set(['quote', 'stat', 'list', 'chapter', 'cta', 'progress', 'logo_reveal', 'label']);

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
  secondary: string;
  captionBackground: string | null;
  holdToEnd?: boolean;
}> = ({element, accent, text, background, font, durationInFrames, logoSource, safeMargins, secondary, captionBackground, holdToEnd = false}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  // One pixel of a 1920-high frame: new placements scale with the output, so
  // a 720x1280 preview is the final, smaller.
  const u = height / 1920;
  const entrance = spring({frame, fps, config: {damping: 20, stiffness: 170}});
  // An element that runs to the last frame of the video stays on it: fading
  // out there would end the video on whatever is underneath.
  const exit = holdToEnd
    ? 1
    : interpolate(
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
          <Img
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
    // `top` keeps the list over the shot's upper zone, clear of a face in the
    // middle: a card in the brand's second colour with a white rim.
    const top = element.position === 'top';
    return (
      <AbsoluteFill
        style={{
          justifyContent: top ? 'flex-start' : 'center',
          paddingTop: top ? pad.top + 10 * u : undefined,
          paddingLeft: pad.left + 24,
          paddingRight: pad.right + 24,
          opacity: exit,
        }}
      >
        <div
          style={
            top
              ? {...card, background: rgba(secondary, 0.92), border: `${4 * u}px solid rgba(255,255,255,0.95)`, borderRadius: 30 * u, padding: `${24 * u}px ${34 * u}px`, color: '#FFFFFF'}
              : {...card, padding: '30px 38px'}
          }
        >
          {items.map((item, index) => {
            const at = (window / items.length) * index;
            const shown = spring({frame: frame - at, fps, config: {damping: 20, stiffness: 170}});
            return (
              <div
                key={`${index}-${item}`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 22 * (top ? u : 1),
                  fontSize: top ? 56 * u : 48,
                  fontWeight: top ? 800 : 700,
                  lineHeight: top ? 1.18 : 1.2,
                  margin: top ? `${12 * u}px 0` : '12px 0',
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

  if (element.type === 'label') {
    // A chip naming the scene, in the top safe zone. It must never look like
    // a caption, so it never takes the caption box colour: a white pill with
    // text in the brand's second colour and an accent dot -- or, when the
    // captions themselves sit on white, the second colour with white text.
    const onWhite = (captionBackground ?? '').toUpperCase() === '#FFFFFF';
    const fill = onWhite ? secondary : 'rgba(255,255,255,0.94)';
    const ink = onWhite ? '#FFFFFF' : secondary;
    return (
      <AbsoluteFill style={{paddingTop: pad.top, paddingLeft: pad.left, paddingRight: pad.right, alignItems: 'center', opacity}}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 14 * u,
            fontFamily: font,
            fontSize: 34 * u,
            fontWeight: 800,
            letterSpacing: 3 * u,
            textTransform: 'uppercase',
            lineHeight: 1.15,
            color: ink,
            background: fill,
            padding: `${12 * u}px ${28 * u}px`,
            borderRadius: 999,
            boxShadow: `0 ${4 * u}px ${18 * u}px ${rgba(secondary, 0.25)}`,
            textAlign: 'center',
            maxWidth: '100%',
            transform: `translateY(${-rise}px)`,
          }}
        >
          <span style={{width: 14 * u, height: 14 * u, borderRadius: 999, background: accent, flex: 'none'}} />
          <span>{element.text}</span>
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

  // cta: above the caption area, which owns the bottom of the frame -- or,
  // with `position: top`, in the top safe zone, where it never meets a scene
  // frame: a white pill, text in the second colour, an accent bookmark.
  const pulse = 1 + 0.04 * Math.sin((frame / fps) * Math.PI * 2);
  if (element.position === 'top') {
    return (
      <AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'center', paddingTop: pad.top + 20 * u, opacity}}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 18 * u,
            fontFamily: font,
            fontSize: 62 * u,
            fontWeight: 800,
            lineHeight: 1.15,
            color: secondary,
            background: '#FFFFFF',
            border: `${5 * u}px solid ${accent}`,
            padding: `${18 * u}px ${40 * u}px`,
            borderRadius: 999,
            boxShadow: `0 ${10 * u}px ${36 * u}px rgba(20,24,40,0.35)`,
            transform: `translateY(${-rise}px) scale(${entrance >= 0.99 ? pulse : entrance})`,
          }}
        >
          <svg width={38 * u} height={48 * u} viewBox="0 0 38 48">
            <path d="M4 2h30v44L19 34 4 46z" fill={accent} />
          </svg>
          <span>{element.text}</span>
        </div>
      </AbsoluteFill>
    );
  }
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
/**
 * The caption style for one cue: as contracted, or -- inside a scene frame --
 * moved so the cue's box is centred in the frame, the same place for every
 * cue of the scene.
 */
const framedStyle = (cue: CaptionCue, props: SocialVideoProps): CaptionStyle => {
  const style = props.captionStyle as CaptionStyle;
  const layout = props.captionLayout as CaptionLayout;
  const g = props.sceneFrame;
  if (!cue.framed || !g) {
    return style;
  }
  const boxed = style.background_style !== 'none';
  const boxH =
    cue.lines.length * cue.font_size_px * layout.line_height +
    (boxed ? layout.padding_top + layout.padding_bottom : 0);
  const bottom = props.height - g.caption_centre - boxH / 2;
  return {...style, position: 'bottom', margin_pct: (bottom / props.height) * 100};
};

const usePunchIn = (punchIns: PunchIn[]): {scale: number; origin: string; focusX: number} => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const now = frame / fps;
  const active = punchIns.find((p) => now >= p.start && now < p.end);
  if (!active) {
    return {scale: 1, origin: '50% 50%', focusX: 0.5};
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
    focusX: active.focus_x,
  };
};

const EMOJI_FAMILY = 'StickerEmoji';

/** The picture's displacement in pixels while a shake is open; it rises and falls. */
const useShake = (shakes: Shake[]): {x: number; y: number} => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const now = frame / fps;
  const active = shakes.find((s) => now >= s.start && now <= s.end);
  if (!active) {
    return {x: 0, y: 0};
  }
  const length = Math.max(active.end - active.start, 1e-3);
  const rise = Math.sin((Math.PI * (now - active.start)) / length);
  const wave = (now - active.start) * active.frequency_hz * 2 * Math.PI;
  const amp = (active.amplitude_pct / 100) * width;
  return {x: amp * rise * Math.sin(wave), y: amp * 0.6 * rise * Math.cos(wave * 1.3)};
};

/**
 * A reaction on one word: an emoji or a small project image, 0.6-1.5 s,
 * placed by its centre. pop springs it in, drop falls it in, shake wobbles it,
 * pulse beats it; every one leaves in the last 0.15 s.
 */
const Sticker: React.FC<{element: MotionElement; durationInFrames: number}> = ({
  element,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const size = ((element.size_pct ?? 12) / 100) * height;
  const enter = spring({frame, fps, config: {damping: 11, stiffness: 220}});
  const leave = interpolate(
    frame,
    [Math.max(0, durationInFrames - Math.round(fps * 0.15)), durationInFrames],
    [1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  const t = frame / fps;
  const animation = element.animation ?? 'pop';
  const scale =
    animation === 'pop'
      ? interpolate(enter, [0, 1], [0.2, 1])
      : animation === 'pulse'
        ? 1 + 0.12 * Math.sin(t * Math.PI * 6)
        : 1;
  const dy = animation === 'drop' ? interpolate(enter, [0, 1], [-size * 1.2, 0]) : 0;
  const rotate = animation === 'shake' ? 14 * Math.sin(t * Math.PI * 14) * Math.exp(-t * 2) : 0;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          left: (element.x_pct ?? 0.78) * width - size / 2,
          top: (element.y_pct ?? 0.3) * height - size / 2,
          width: size,
          height: size,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          opacity: leave * Math.min(1, enter * 3),
          transform: `translateY(${dy}px) rotate(${rotate}deg) scale(${scale})`,
        }}
      >
        {element.image_source ? (
          <Img src={staticFile(element.image_source)} style={{width: '100%', height: '100%', objectFit: 'contain'}} />
        ) : (
          <span style={{fontFamily: EMOJI_FAMILY, fontSize: size * 0.86, lineHeight: 1}}>{element.emoji}</span>
        )}
      </div>
    </AbsoluteFill>
  );
};

export const SocialVideo: React.FC<SocialVideoProps> = (props) => {
  useProjectFont(props.fontFamily, props.fontSource);
  useProjectFont(EMOJI_FAMILY, props.emojiFontSource ?? null);
  const shake = useShake(props.shakes ?? []);
  const punch = usePunchIn(props.punchIns ?? []);
  const cut = useTransition(props.transitions ?? []);
  const pack = stylePack(props.style);
  // A slide moves the picture sideways; scaling it just enough that it still
  // covers the frame keeps the edge it moves away from from showing black.
  const anchor = Math.max(1, props.width * Math.min(punch.focusX, 1 - punch.focusX));
  // A shake moves the picture too: enlarge it just enough to keep the frame covered.
  const shaken = 1 + 2.2 * Math.max(Math.abs(shake.x) / props.width, Math.abs(shake.y) / props.height);
  const scale = Math.max(punch.scale * cut.scale, 1 + Math.abs(cut.shiftX) / anchor, shaken);
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      <AbsoluteFill
        style={{
          overflow: 'hidden',
          transform: `translate(${cut.shiftX + shake.x}px, ${shake.y}px) scale(${scale})`,
          transformOrigin: punch.origin,
          filter: cut.blur > 0.05 ? `blur(${cut.blur}px)` : undefined,
        }}
      >
        <Video src={staticFile(props.source)} muted style={{width: '100%', height: '100%'}} />
      </AbsoluteFill>
      {cut.flash > 0.01 ? (
        <AbsoluteFill style={{backgroundColor: props.accentColor, opacity: cut.flash}} />
      ) : null}
      {props.logoSource && props.logoUsage !== 'none' ? (
        <Img
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
        const holdToEnd = from + duration >= props.durationInFrames - 1;
        return (
          <Sequence key={`${element.type}-${index}`} from={from} durationInFrames={duration}>
            {element.type === 'sticker' ? (
              <Sticker element={element} durationInFrames={duration} />
            ) : element.type === 'label' && props.labelStyle === 'scene_frame' && props.sceneFrame ? (
              <SceneFrame
                text={element.text}
                previous={element.continues}
                geometry={props.sceneFrame}
                accent={props.accentColor}
                secondary={props.secondaryColor}
                font={props.fontFamily}
                fontPx={element.tab_font_px}
                previousFontPx={element.continues_font_px}
              />
            ) : DATA_GRAPHICS.has(element.type) ? (
              <DataGraphic
                element={element}
                accent={props.accentColor}
                text={props.textColor}
                background={props.backgroundColor}
                font={props.fontFamily}
                durationInFrames={duration}
                safeMargins={props.safeMargins}
                pack={pack}
                secondary={props.secondaryColor}
                holdToEnd={holdToEnd}
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
                secondary={props.secondaryColor}
                captionBackground={props.captionStyle?.background_style !== 'none' ? props.captionStyle?.background_colour ?? null : null}
                holdToEnd={holdToEnd}
              />
            ) : (
              <MotionGraphic
                element={element}
                accent={props.accentColor}
                text={props.textColor}
                background={props.backgroundColor}
                font={props.fontFamily}
                durationInFrames={duration}
                holdToEnd={holdToEnd}
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
                  style={framedStyle(cue, props)}
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
