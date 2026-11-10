import {bundle, webpack} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import path from 'node:path';
import process from 'node:process';
import {readFile} from 'node:fs/promises';

// Two steps, so one bundle can serve many renders:
//   render.mjs bundle ENTRY OUT_DIR PUBLIC_DIR [CUSTOM_REGISTRY]
//   render.mjs render SERVE_DIR PROPS_JSON OUTPUT
// The caller owns every directory: where a bundle is kept, the copy a render
// is served from, and removing both.
const USAGE =
  'usage: render.mjs bundle ENTRY OUT_DIR PUBLIC_DIR [CUSTOM_REGISTRY]\n' +
  '       render.mjs render SERVE_DIR PROPS_JSON OUTPUT';
const [mode, ...args] = process.argv.slice(2);

// Progress for the caller: one JSON object per line on stderr behind a prefix
// nothing else prints, at most twice a second.
const PROGRESS_PREFIX = '@@social-video-progress ';
const started = Date.now();
let lastReport = 0;
const report = (stage, fields, force = false) => {
  const now = Date.now();
  if (!force && now - lastReport < 500) {
    return;
  }
  lastReport = now;
  process.stderr.write(
    `${PROGRESS_PREFIX}${JSON.stringify({stage, elapsed_ms: now - started, ...fields})}\n`,
  );
};

if (mode === 'bundle') {
  const [entryPoint, outDir, publicDir, customRegistry] = args;
  if (!entryPoint || !outDir || !publicDir) {
    throw new Error(USAGE);
  }
  // Components written for one reel (`custom` elements) were checked in Python
  // and come with a registry of their own, which replaces the empty one.
  const webpackOverride = (config) =>
    customRegistry
      ? {
          ...config,
          plugins: [
            ...(config.plugins ?? []),
            new webpack.NormalModuleReplacementPlugin(
              /^\.\/customGraphics$/,
              path.resolve(customRegistry),
            ),
          ],
        }
      : config;
  report('bundle', {progress: 0}, true);
  // PUBLIC_DIR is empty on purpose: a render's own files are put next to the
  // bundle afterwards, so the bundle holds nothing of any one reel.
  await bundle({
    entryPoint: path.resolve(entryPoint),
    outDir: path.resolve(outDir),
    publicDir: path.resolve(publicDir),
    webpackOverride,
    onProgress: (percent) => report('bundle', {progress: percent / 100}),
  });
  report('bundle', {progress: 1}, true);
} else if (mode === 'render') {
  const [serveDir, propsPath, output] = args;
  if (!serveDir || !propsPath || !output) {
    throw new Error(USAGE);
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
      throw new Error(
        `SOCIAL_VIDEO_REMOTION_CONCURRENCY must be a count or a percentage, got ${concurrencyEnv}`,
      );
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

  const serveUrl = path.resolve(serveDir);
  const composition = await selectComposition({
    serveUrl,
    id: 'SocialVideo',
    inputProps,
    chromiumOptions,
  });
  const total = composition.durationInFrames;
  report('render', {progress: 0, rendered: 0, encoded: 0, total}, true);

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
    ffmpegOverride: ({type, args: ffmpegArgs}) => {
      if (type !== 'stitcher') {
        return ffmpegArgs;
      }
      const duration = inputProps.durationInFrames / inputProps.fps;
      return [
        ...ffmpegArgs.slice(0, -1),
        '-t',
        duration.toFixed(9),
        '-movflags',
        '+faststart',
        ...ffmpegArgs.slice(-1),
      ];
    },
    outputLocation: path.resolve(output),
    inputProps,
    onProgress: ({progress, renderedFrames, encodedFrames}) =>
      report('render', {progress, rendered: renderedFrames, encoded: encodedFrames, total}),
  });
  report('render', {progress: 1, rendered: total, encoded: total, total}, true);
} else {
  throw new Error(USAGE);
}
