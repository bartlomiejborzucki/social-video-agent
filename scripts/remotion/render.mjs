import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import path from 'node:path';
import process from 'node:process';
import {readFile, rm} from 'node:fs/promises';

const [entryPoint, publicDir, propsPath, output] = process.argv.slice(2);
if (!entryPoint || !publicDir || !propsPath || !output) {
  throw new Error('usage: render.mjs ENTRY PUBLIC_DIR PROPS_JSON OUTPUT');
}

const inputProps = JSON.parse(await readFile(propsPath, 'utf8'));

// Optional tuning from the environment; unset keeps Remotion's defaults.
// Concurrency is a tab count ("4") or a share of the cores ("50%").
const concurrencyEnv = process.env.SOCIAL_VIDEO_REMOTION_CONCURRENCY?.trim();
let concurrency = null;
if (concurrencyEnv) {
  if (/^[1-9]\d*$/.test(concurrencyEnv)) {
    concurrency = Number(concurrencyEnv);
  } else if (/^(100|[1-9]\d?)%$/.test(concurrencyEnv)) {
    concurrency = concurrencyEnv;
  } else {
    throw new Error(`SOCIAL_VIDEO_REMOTION_CONCURRENCY must be a count or a percentage, got ${concurrencyEnv}`);
  }
}

// The OpenGL backend Chrome draws with. "angle" uses the GPU for blur and
// shadows where one is available; the default is a software renderer.
const GL_BACKENDS = ['angle', 'egl', 'swiftshader', 'swangle', 'vulkan', 'angle-egl'];
const gl = process.env.SOCIAL_VIDEO_REMOTION_GL?.trim() || null;
if (gl && !GL_BACKENDS.includes(gl)) {
  throw new Error(`SOCIAL_VIDEO_REMOTION_GL must be one of ${GL_BACKENDS.join(', ')}, got ${gl}`);
}
const chromiumOptions = gl ? {gl} : {};

// The bundle is a ~30 MB webpack build written to the system temp directory,
// which is often RAM-backed tmpfs. Remotion never removes it, so this does.
const serveUrl = await bundle({entryPoint: path.resolve(entryPoint), publicDir: path.resolve(publicDir)});
try {
  const composition = await selectComposition({
    serveUrl,
    id: 'SocialVideo',
    inputProps,
    chromiumOptions,
  });

  await renderMedia({
    composition,
    serveUrl,
    codec: 'h264',
    concurrency,
    chromiumOptions,
    // The compositor draws pictures only. Its audio path re-encodes the base
    // render's AAC without trimming encoder priming, which lands the sound
    // ~45 ms after the picture; the caller muxes the base audio back instead.
    muted: true,
    pixelFormat: 'yuv420p',
    colorSpace: 'bt709',
    crf: 18,
    x264Preset: 'medium',
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
} finally {
  await rm(serveUrl, {recursive: true, force: true});
}
