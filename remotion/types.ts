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
};
