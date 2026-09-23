export type MotionElement = {
  type: 'hook' | 'lower_third' | 'callout' | 'end_card';
  start: number;
  end: number;
  text: string;
  secondary_text?: string;
  reason: string;
  /** Staged public-directory filename of the end-card plate, never a local path. */
  image_source?: string | null;
  image_dim_pct?: number;
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
  captions: CaptionCue[];
  captionStyle: CaptionStyle | null;
  captionLayout: CaptionLayout | null;
  logoSource: string | null;
  logoUsage: 'none' | 'optional' | 'required';
  safeMargins: {top: number; right: number; bottom: number; left: number};
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
  background_style: 'none' | 'box' | 'rounded_box';
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
};
