export type MotionElement = {
  type:
    | 'hook'
    | 'lower_third'
    | 'callout'
    | 'end_card'
    | 'quote'
    | 'stat'
    | 'list'
    | 'chapter'
    | 'cta'
    | 'progress'
    | 'logo_reveal'
    | 'hook_card'
    | 'chart'
    | 'compare'
    | 'steps'
    | 'label'
    | 'sticker'
    | 'strike'
    | 'bubble'
    | 'icon'
    | 'process'
    | 'kinetic_word';
  start: number;
  end: number;
  text: string;
  secondary_text?: string;
  items?: string[];
  reason: string;
  /** Staged public-directory filename of the end-card plate, never a local path. */
  image_source?: string | null;
  image_dim_pct?: number;
  /** Resolved placement of a cta (above_captions | top), list/steps (center | top) or strike. */
  position?: 'top' | 'center' | 'above_captions' | null;
  /** For a label: the text of the label it takes over from without a break. */
  continues?: string | null;
  /** For a label in a scene frame: its title size, and the previous title's. */
  tab_font_px?: number | null;
  continues_font_px?: number | null;
  /** End card: held after the last word (the timeline was extended for it). */
  hold?: boolean;
  /** End card: text over a dimmed image, or the image above the text. */
  layout?: 'overlay' | 'image_top';
  /** End card: lines and sizes measured in Python; links are never split. */
  fitted?: FittedCard | null;
  /** Sticker: one emoji (drawn from the emoji font) or image_source. */
  emoji?: string | null;
  /** Sticker: the Noto Animated Emoji clip staged as animated-emoji/<name>.webm. */
  animated_emoji_name?: string | null;
  animation?: 'pop' | 'shake' | 'pulse' | 'drop';
  /** Sticker height as a percentage of the output height. */
  size_pct?: number;
  /** Sticker centre as fractions of the output width and height. */
  x_pct?: number;
  y_pct?: number;
  /** List/steps: when each item enters, on the output timeline (its spoken word). */
  item_times?: number[] | null;
  /** Strike: the line that takes the crossed-out one's place. */
  replacement?: string | null;
  /** Strike: crossed out, then replaced, on the output timeline. */
  strike_at?: number | null;
  replace_at?: number | null;
  strike_mark?: 'none' | 'scissors' | 'cross';
  /** Bubble: something said or written, and where a speech tail points. */
  variant?: 'speech' | 'message' | null;
  tail?: 'speaker' | 'left' | 'right' | null;
  /** Icon: its name, and the SVG staged as icons/<name>.svg. */
  icon?: string | null;
  icon_source?: string | null;
  /** Process: the state it ends in, shown with a tick. */
  done_text?: string | null;
};

export type Shake = {start: number; end: number; amplitude_pct: number; frequency_hz: number};

export type FittedBlock = {font_px: number; lines: string[]};

export type FittedCard = {title: FittedBlock; secondary?: FittedBlock; max_width: number};

/** The scene frame in output pixels, computed in Python (motion/layout.py). */
export type SceneFrameGeometry = {
  left: number;
  top: number;
  width: number;
  height: number;
  radius: number;
  border: number;
  tab_font_px: number;
  tab_pad_x: number;
  tab_pad_y: number;
  tab_border: number;
  tab_dot: number;
  tab_top: number;
  tab_height: number;
  caption_centre: number;
};

export type SocialVideoProps = {
  source: string;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
  accentColor: string;
  textColor: string;
  backgroundColor: string;
  fontFamily: string;
  fontSource: string | null;
  elements: MotionElement[];
  punchIns: PunchIn[];
  transitions: Transition[];
  /** Style pack of the motion layer (editorial, bold-social, tech-minimal). */
  style: string;
  captions: CaptionCue[];
  captionStyle: CaptionStyle | null;
  captionLayout: CaptionLayout | null;
  logoSource: string | null;
  logoUsage: 'none' | 'optional' | 'required';
  safeMargins: {top: number; right: number; bottom: number; left: number};
  /** The brand's second colour: scene-frame tab, list card, CTA text. */
  secondaryColor: string;
  /** Every brand colour, in order: a process bar's stages. */
  brandColors?: string[];
  /** How a label is drawn: a chip in the top zone, or a frame title. */
  labelStyle: 'chip' | 'scene_frame';
  sceneFrame: SceneFrameGeometry | null;
  /** Moments the picture shakes, on the output timeline. */
  shakes?: Shake[];
  /** Staged Noto Color Emoji file, when a sticker shows an emoji. */
  emojiFontSource?: string | null;
};

/** An effect across one cut, centred on its output time. */
export type Transition = {
  at: number;
  style: 'zoom' | 'slide' | 'flash' | 'light_leak';
  duration: number;
  reason: string;
};

/** A timed push in on the picture only; captions and graphics stay put. */
export type PunchIn = {
  start: number;
  end: number;
  scale: number;
  focus_x: number;
  focus_y: number;
  reason: string;
};

export type CaptionWord = {text: string; start: number; end: number; emphasis?: boolean};

/**
 * One line, already wrapped and already measured in Python.
 *
 * The compositor does not wrap, clamp or shorten captions. It used to, with
 * `-webkit-line-clamp` plus `overflow: hidden`, which silently replaced the
 * end of a long Polish phrase with an ellipsis nobody spoke.
 */
export type CaptionLine = {
  text: string;
  width_px: number;
  /** Shipped when the contract asks for an active-word highlight or emphasis words. */
  words?: CaptionWord[];
};

export type CaptionCue = {
  index: number;
  start: number;
  end: number;
  text: string;
  speaker?: string;
  /** Pre-wrapped lines; exactly what gets drawn, in order. */
  lines: CaptionLine[];
  /** Per-cue size in pixels: a cue that needed shrinking carries a smaller one. */
  font_size_px: number;
  /** Drawn centred in the scene frame of the label it falls under. */
  framed?: boolean;
};

export type CaptionLayout = {
  box_width_px: number;
  text_width_px: number;
  padding_x: number;
  padding_top: number;
  padding_bottom: number;
  line_height: number;
};
export type CaptionStyle = {
  font_family: string;
  font_size_pct: number;
  bold: boolean;
  primary_colour: string;
  background_colour: string;
  background_style: 'none' | 'box' | 'rounded_box' | 'rounded_lines';
  corner_radius: number;
  outline_colour: string;
  outline_width: number;
  shadow: number;
  position: 'bottom' | 'center' | 'top' | 'lower_third' | 'lower_safe_zone';
  margin_pct: number;
  max_lines: number;
  max_chars_per_cue: number;
  highlight_active_word: boolean;
  highlight_colour: string;
  emphasis_words: string[];
  emphasis_colour: string;
  emphasis_mark?: EmphasisMark;
  animation: 'none' | 'pop' | 'box';
  /** Opacity of the cue's words not spoken yet; 1 draws them like the rest. */
  upcoming_word_opacity?: number;
};

export type EmphasisMark = 'none' | 'highlight' | 'underline' | 'circle';
