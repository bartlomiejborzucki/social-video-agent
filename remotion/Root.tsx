import React from 'react';
import {Composition} from 'remotion';
import {SocialVideo} from './SocialVideo';
import type {SocialVideoProps} from './types';

const defaults: SocialVideoProps = {
  source: 'base.mp4',
  durationInFrames: 30,
  fps: 30,
  width: 1080,
  height: 1920,
  accentColor: '#FFD400',
  textColor: '#FFFFFF',
  backgroundColor: '#101114',
  fontFamily: 'Inter, Arial, sans-serif',
  fontSource: null,
  elements: [],
  punchIns: [],
  captions: [],
  captionStyle: null,
  captionLayout: null,
  logoSource: null,
  logoUsage: 'none',
  safeMargins: {top: 6, right: 6, bottom: 12, left: 6},
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="SocialVideo"
    component={SocialVideo}
    durationInFrames={defaults.durationInFrames}
    fps={defaults.fps}
    width={defaults.width}
    height={defaults.height}
    defaultProps={defaults}
    calculateMetadata={({props}) => ({
      durationInFrames: props.durationInFrames,
      fps: props.fps,
      width: props.width,
      height: props.height,
    })}
  />
);
