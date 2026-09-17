export type MotionElement = {
  type: 'hook' | 'lower_third' | 'callout' | 'end_card';
  start: number;
  end: number;
  text: string;
  secondary_text?: string;
  reason: string;
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
  captions: CaptionCue[];
  captionStyle: CaptionStyle | null;
  logoSource: string | null;
  logoUsage: 'none' | 'optional' | 'required';
  safeMargins: {top: number; right: number; bottom: number; left: number};
};

export type CaptionCue = {index: number; start: number; end: number; text: string; speaker?: string};
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
};
