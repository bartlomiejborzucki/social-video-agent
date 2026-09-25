/**
 * Visual families for the motion layer. Every pack takes the brand's accent,
 * text colour, background and font from the contract; the pack decides shape,
 * weight, entrance and how cards sit on the picture.
 */
export type StylePack = {
  radius: number;
  /** 'accent' fills cards with the brand accent; otherwise a CSS colour. */
  card: string;
  border: 'left' | 'top' | 'none';
  weight: number;
  entrance: 'rise' | 'pop' | 'slide';
  uppercase: boolean;
  letterSpacing: number;
};

export const STYLE_PACKS: Record<string, StylePack> = {
  editorial: {
    radius: 18,
    card: 'rgba(10, 11, 14, 0.82)',
    border: 'left',
    weight: 800,
    entrance: 'rise',
    uppercase: false,
    letterSpacing: 0,
  },
  'bold-social': {
    radius: 30,
    card: 'accent',
    border: 'none',
    weight: 900,
    entrance: 'pop',
    uppercase: true,
    letterSpacing: 1,
  },
  'tech-minimal': {
    radius: 6,
    card: 'rgba(8, 10, 14, 0.9)',
    border: 'top',
    weight: 600,
    entrance: 'slide',
    uppercase: false,
    letterSpacing: 0.5,
  },
};

export const stylePack = (name: string | undefined): StylePack =>
  STYLE_PACKS[name === 'editorial_clean' || !name ? 'editorial' : name] ?? STYLE_PACKS.editorial;

/** Entrance transform for a pack, from a 0..1 spring value. */
export const entranceTransform = (pack: StylePack, progress: number): string => {
  if (pack.entrance === 'pop') {
    return `scale(${0.7 + 0.3 * progress})`;
  }
  if (pack.entrance === 'slide') {
    return `translateX(${(1 - progress) * -80}px)`;
  }
  return `translateY(${(1 - progress) * 32}px)`;
};
