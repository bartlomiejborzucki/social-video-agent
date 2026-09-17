import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import path from 'node:path';
import process from 'node:process';
import {readFile} from 'node:fs/promises';

const [entryPoint, publicDir, propsPath, output] = process.argv.slice(2);
if (!entryPoint || !publicDir || !propsPath || !output) {
  throw new Error('usage: render.mjs ENTRY PUBLIC_DIR PROPS_JSON OUTPUT');
}

const inputProps = JSON.parse(await readFile(propsPath, 'utf8'));
const serveUrl = await bundle({entryPoint: path.resolve(entryPoint), publicDir: path.resolve(publicDir)});
const composition = await selectComposition({
  serveUrl,
  id: 'SocialVideo',
  inputProps,
});

await renderMedia({
  composition,
  serveUrl,
  codec: 'h264',
  audioCodec: 'aac',
  audioBitrate: '192K',
  sampleRate: 48000,
  pixelFormat: 'yuv420p',
  colorSpace: 'bt709',
  crf: 18,
  x264Preset: 'medium',
  enforceAudioTrack: true,
  ffmpegOverride: ({type, args}) => {
    if (type !== 'stitcher') {
      return args;
    }
    const duration = inputProps.durationInFrames / inputProps.fps;
    return [
      ...args.slice(0, -1),
      '-t',
      duration.toFixed(9),
      '-movflags',
      '+faststart',
      ...args.slice(-1),
    ];
  },
  outputLocation: path.resolve(output),
  inputProps,
});
