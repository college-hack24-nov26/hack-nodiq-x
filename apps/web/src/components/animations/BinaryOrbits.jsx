'use client';

import React, {
  useEffect,
  useRef,
  forwardRef,
  useImperativeHandle,
  useSyncExternalStore
} from 'react';
import * as THREE from 'three';

const TWO_PI = 2 * Math.PI;

const subscribeReducedMotion = (cb) => {
  const media = window.matchMedia('(prefers-reduced-motion: reduce)');
  media.addEventListener('change', cb);
  return () => media.removeEventListener('change', cb);
};

const getReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const clamp = (val, min, max) => Math.min(max, Math.max(min, val));

let colorProbe = null;
const parseColor = (colorStr, fallback = [0.04, 0.04, 0.04]) => {
  if (typeof document === 'undefined') return fallback;
  if (!colorProbe) {
    colorProbe = document.createElement('canvas').getContext('2d');
  }
  if (!colorProbe) return fallback;
  colorProbe.fillStyle = '#010203';
  colorProbe.fillStyle = colorStr;
  const styleStr = String(colorProbe.fillStyle);
  if (styleStr === '#010203' && colorStr.trim().toLowerCase() !== '#010203') {
    return fallback;
  }
  if (styleStr.startsWith('#')) {
    const hex = styleStr.slice(1);
    return [
      parseInt(hex.slice(0, 2), 16) / 255,
      parseInt(hex.slice(2, 4), 16) / 255,
      parseInt(hex.slice(4, 6), 16) / 255
    ];
  }
  const digits = styleStr.match(/[\d.]+/g);
  if (!digits || digits.length < 3) return fallback;
  return [Number(digits[0]) / 255, Number(digits[1]) / 255, Number(digits[2]) / 255];
};

const toLinear = (c) =>
  c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);

const rgbToOklab = ([r, g, b]) => {
  const lr = toLinear(r);
  const lg = toLinear(g);
  const lb = toLinear(b);
  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
  ];
};

const SHADER_ORBIT_CHUNK = `
uniform float uTime;
uniform float uSpin;
uniform float uCoreRadius;
uniform float uArms;
uniform float uTwist;
uniform float uEps;
uniform float uPattern;

float omega(float a) {
  return uSpin / sqrt(a * a + uCoreRadius * uCoreRadius);
}

vec3 orbit(float a, float psi, float bulge, out float phase) {
  float th = psi + omega(a) * uTime;
  phase = uArms * (th + uTwist * log(max(a, 1e-3)) - uPattern * uTime);
  float r = a * (1.0 - uEps * cos(phase) * (1.0 - bulge));
  return vec3(r * cos(th), r * sin(th), th);
}
`;

const SHADER_PERTURBATION = `
precision highp float;
uniform sampler2D uStatic;
uniform sampler2D uState;
uniform vec4 uSegment;
uniform float uGather;
uniform float uDrag;
uniform float uWidth;
uniform float uDecay;
${SHADER_ORBIT_CHUNK}
out vec4 fragColor;

void main() {
  ivec2 cell = ivec2(gl_FragCoord.xy);
  vec2 offset = texelFetch(uState, cell, 0).xy;
  if (uGather > 0.0) {
    vec4 star = texelFetch(uStatic, cell, 0);
    float phase;
    vec3 at = orbit(star.x, star.y, star.z, phase);
    vec2 radial = vec2(cos(at.z), sin(at.z));
    vec2 tangent = vec2(-radial.y, radial.x);
    vec2 p = at.xy + radial * offset.x + tangent * offset.y;
    vec2 d = uSegment.zw - uSegment.xy;
    float len = length(d);
    vec2 dir = len > 1e-6 ? d / len : vec2(1.0, 0.0);
    float along = clamp(dot(p - uSegment.xy, dir), 0.0, len);
    vec2 n = p - uSegment.xy - dir * along;
    float w = exp(-dot(n, n) / (uWidth * uWidth)) * (1.0 - 0.7 * star.z) * smoothstep(0.05, 0.3, star.x);
    vec2 delta = (dir * uDrag * uWidth - n * uGather) * w;
    offset += vec2(dot(delta, radial), dot(delta, tangent));
  }
  fragColor = vec4(offset * uDecay, 0.0, 1.0);
}
`;

const SHADER_STAR_VERT = `
in vec4 aOrbit;
in vec4 aTraits;
uniform sampler2D uState;
uniform int uStride;
uniform vec2 uResolution;
uniform vec2 uCenter;
uniform float uFocal;
uniform float uDistance;
uniform float uIncline;
uniform float uRoll;
uniform float uPixelRatio;
uniform float uRealTime;
uniform float uDust;
uniform float uCore;
uniform float uVoid;
uniform float uSize;
uniform float uSizeScale;
uniform float uSparkle;
uniform float uTwinkle;
uniform float uBack;
uniform float uEnergy;
uniform float uInk;
uniform vec3 uLabA;
uniform vec3 uLabB;
uniform vec4 uRipples[6];
uniform float uActive;
${SHADER_ORBIT_CHUNK}
out vec3 vColor;
out float vGain;

vec3 labToLinear(vec3 lab) {
  float l = lab.x + 0.3963377774 * lab.y + 0.2158037573 * lab.z;
  float m = lab.x - 0.1055613458 * lab.y - 0.0638541728 * lab.z;
  float s = lab.x - 0.0894841775 * lab.y - 1.2914855480 * lab.z;
  l = l * l * l;
  m = m * m * m;
  s = s * s * s;
  return max(vec3(
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
  ), 0.0);
}

void main() {
  float a = aOrbit.x;
  float bulge = aTraits.x;
  float phase;
  vec3 at = orbit(a, aOrbit.y, bulge, phase);
  vec2 radial = vec2(cos(at.z), sin(at.z));
  vec2 tangent = vec2(-radial.y, radial.x);
  vec2 offset = texelFetch(uState, ivec2(gl_VertexID % uStride, gl_VertexID / uStride), 0).xy;
  vec3 p = vec3(at.xy + radial * offset.x + tangent * offset.y, aOrbit.z);
  float tidal = smoothstep(0.004, 0.03, length(offset));
  float ring = 0.0;
  if (uActive > 0.5) {
    for (int k = 0; k < 6; k++) {
      vec4 wave = uRipples[k];
      if (wave.w <= 0.0) continue;
      float age = uRealTime - wave.z;
      if (age < 0.0 || age > 7.0) continue;
      vec2 rel = p.xy - wave.xy;
      float rr = length(rel);
      float front = 0.05 + 0.32 * age;
      float width = 0.07 + 0.03 * age;
      float g = (rr - front) / width;
      float band = exp(-g * g);
      float envelope = wave.w * smoothstep(0.0, 0.7, age) * exp(-age / 2.2) * smoothstep(0.03, 0.2, front + length(wave.xy));
      p.xy -= rel / max(rr, 1e-4) * (rr - front) * 0.55 * envelope * band;
      p.z += 0.03 * envelope * band;
      ring += envelope * band;
    }
  }

  float ci = cos(uIncline);
  float si = sin(uIncline);
  vec3 q = vec3(p.x, p.y * ci + p.z * si, -p.y * si + p.z * ci);
  float cr = cos(uRoll);
  float sr = sin(uRoll);
  q.xy = vec2(cr * q.x - sr * q.y, sr * q.x + cr * q.y);
  float depth = uDistance - q.z;
  vec2 screen = uCenter + uFocal * q.xy / depth;

  float mk = uArms * uTwist;
  float crest = (cos(phase) - mk * sin(phase)) / sqrt(1.0 + mk * mk);
  float arm = pow(max(crest, 0.0), 2.0) * (1.0 - bulge);
  float laneCrest = (cos(phase - 0.55) - mk * sin(phase - 0.55)) / sqrt(1.0 + mk * mk);
  float lane = pow(max(laneCrest, 0.0), 8.0) * (1.0 - arm) * (1.0 - bulge) * smoothstep(0.1, 0.3, a);

  float reach = smoothstep(0.02, 0.55, a);
  vec3 tone = labToLinear(mix(uLabB, uLabA, reach));
  vec3 core = labToLinear(vec3(min(uLabB.x * 1.08 + 0.06, 0.98), uLabB.yz * 0.45));
  vec3 color = mix(tone, core, bulge * 0.75);
  vec3 youngColor = labToLinear(vec3(min(uLabB.x * 0.92, 0.9), uLabB.yz * 1.25));
  float young = smoothstep(0.84, 0.97, aTraits.z) * arm;
  float kindled = clamp(tidal * 0.7 + ring * 1.5, 0.0, 0.75) * (1.0 - bulge * 0.7);
  color = mix(color, youngColor, max(young * 0.75, kindled));
  float bright = step(1.0 - uSparkle, aTraits.y) * (1.0 - bulge * 0.6);
  color = mix(color, vec3(1.0, 0.97, 1.0), bright * 0.35);

  float twinkle = 1.0 - uTwinkle * 0.55 * (0.5 + 0.5 * sin(uRealTime * (0.6 + 1.6 * aTraits.w) + aTraits.w * 61.0));
  float body = mix(0.5 + 1.2 * arm + young * 1.4, uCore * 1.1, bulge) * (1.0 + bright * 2.2);
  body *= 1.0 - uDust * 0.8 * lane;
  float edge = 1.0 - smoothstep(0.82, 1.08, a);
  float hollow = smoothstep(uVoid * 0.85, uVoid * 1.15 + 0.01, a);
  float near = clamp(0.5 + 0.5 * q.z / 0.9, 0.0, 1.0);
  float gain = body * edge * hollow * twinkle * mix(uBack, 1.0, near) * (1.0 + uEnergy * 0.15);
  gain *= 1.0 + 0.9 * tidal * (1.0 - bulge * 0.7) + 0.5 * min(ring, 1.0);

  vColor = mix(color, labToLinear(vec3(uLabA.x * 0.62, uLabA.yz * 1.15)), uInk * 0.35);
  vGain = gain;
  float size = uSize * uSizeScale * uPixelRatio * mix(0.6, 1.1, fract(aTraits.y * 7.31)) * (1.0 + bright * 0.7 + young * 0.4);
  gl_PointSize = max(size * uDistance / depth, 1.0);
  gl_Position = vec4(screen / uResolution * 2.0 - 1.0, 0.0, 1.0);
}
`;

const SHADER_STAR_FRAG = `
precision highp float;
uniform float uStarGain;
in vec3 vColor;
in float vGain;
out vec4 fragColor;

void main() {
  vec2 q = gl_PointCoord * 2.0 - 1.0;
  float r2 = dot(q, q);
  float e = (exp(-r2 * 6.0) + 0.25 * exp(-r2 * 2.0)) * vGain * uStarGain;
  fragColor = vec4(vColor * e, e);
}
`;

const SHADER_FULLSCREEN_VERT = `
in vec3 position;
in vec2 uv;
out vec2 vUv;

void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

const SHADER_DOWNSAMPLE = `
precision highp float;
uniform sampler2D uSource;
uniform vec2 uTexel;
in vec2 vUv;
out vec4 fragColor;

void main() {
  vec4 a = texture(uSource, vUv + uTexel * vec2(-1.0, -1.0));
  vec4 b = texture(uSource, vUv + uTexel * vec2(1.0, -1.0));
  vec4 c = texture(uSource, vUv + uTexel * vec2(-1.0, 1.0));
  vec4 d = texture(uSource, vUv + uTexel * vec2(1.0, 1.0));
  fragColor = (a + b + c + d) * 0.125 + texture(uSource, vUv) * 0.5;
}
`;

const SHADER_UPSAMPLE = `
precision highp float;
uniform sampler2D uSource;
uniform sampler2D uBase;
uniform vec2 uTexel;
in vec2 vUv;
out vec4 fragColor;

void main() {
  vec4 sum = texture(uSource, vUv) * 4.0;
  sum += texture(uSource, vUv + uTexel * vec2(-1.0, 0.0)) * 2.0;
  sum += texture(uSource, vUv + uTexel * vec2(1.0, 0.0)) * 2.0;
  sum += texture(uSource, vUv + uTexel * vec2(0.0, -1.0)) * 2.0;
  sum += texture(uSource, vUv + uTexel * vec2(0.0, 1.0)) * 2.0;
  sum += texture(uSource, vUv + uTexel * vec2(-1.0, -1.0));
  sum += texture(uSource, vUv + uTexel * vec2(1.0, -1.0));
  sum += texture(uSource, vUv + uTexel * vec2(-1.0, 1.0));
  sum += texture(uSource, vUv + uTexel * vec2(1.0, 1.0));
  fragColor = texture(uBase, vUv) + sum / 16.0;
}
`;

const SHADER_COMPOSITE = `
precision highp float;
uniform sampler2D uLines;
uniform sampler2D uBloom;
uniform vec3 uBackground;
uniform float uGlow;
uniform float uExposure;
uniform float uMode;
uniform float uGrain;
in vec2 vUv;
out vec4 fragColor;

float hash(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

vec3 encode(vec3 c) {
  c = clamp(c, 0.0, 1.0);
  return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c));
}

void main() {
  vec4 lines = texture(uLines, vUv);
  vec4 bloom = texture(uBloom, vUv);
  vec3 color;
  if (uMode < 0.5) {
    vec3 light = (lines.rgb + bloom.rgb * uGlow) * uExposure;
    vec3 exposed = 1.0 - exp(-light);
    float peak = max(exposed.r, max(exposed.g, exposed.b));
    exposed = mix(exposed, vec3(peak), smoothstep(0.75, 1.0, peak) * 0.35);
    color = uBackground + (1.0 - uBackground) * exposed;
  } else {
    float energy = lines.a + bloom.a * uGlow * 0.2;
    vec3 hue = (lines.rgb + bloom.rgb * uGlow * 0.2) / max(energy, 1e-4);
    float cover = clamp(1.0 - exp(-energy * uExposure * 1.4), 0.0, 0.94);
    color = mix(uBackground, clamp(hue * 0.8, 0.0, 1.0), cover);
  }
  float grain = hash(gl_FragCoord.xy + uGrain * 311.0) - 0.5;
  fragColor = vec4(encode(color) + grain * (1.2 / 255.0), 1.0);
}
`;

const BinaryOrbits = forwardRef(function BinaryOrbits(
  {
    colors = ['#FF7A18', '#FFD8A8'],
    backgroundColor = '#101416',
    mode = 'auto',
    stars = 70000,
    starSize = 1.7,
    sparkle = 0.5,
    arms = 3,
    twist = 3.5,
    armStrength = 0.5,
    dust = 0.5,
    core = 1,
    coreSize = 0.07,
    innerVoid = 0,
    thickness = 0.02,
    tilt = 62,
    roll = -8,
    scale = 1,
    centerX = 0.5,
    centerY = 0.52,
    speed = 1,
    twinkle = 0.35,
    depth = 0.4,
    glow = 0.45,
    intensity = 1,
    interactive = true,
    hoverWake = true,
    clickRipple = true,
    wakeStrength = 1,
    rippleStrength = 1,
    hoverBoost = 0.5,
    paused = false,
    quality = 1,
    className = '',
    style,
    children
  },
  ref
) {
  const containerRef = useRef(null);
  const controllerRef = useRef(null);
  const reducedMotion = useSyncExternalStore(
    subscribeReducedMotion,
    getReducedMotion,
    () => false
  );

  const propsRef = useRef({
    colors,
    backgroundColor,
    mode,
    stars,
    starSize,
    sparkle,
    arms,
    twist,
    armStrength,
    dust,
    core,
    coreSize,
    innerVoid,
    thickness,
    tilt,
    roll,
    scale,
    centerX,
    centerY,
    speed,
    twinkle,
    depth,
    glow,
    intensity,
    interactive,
    hoverWake,
    clickRipple,
    wakeStrength,
    rippleStrength,
    hoverBoost,
    paused,
    quality,
    reduced: reducedMotion
  });

  useEffect(() => {
    propsRef.current = {
      colors,
      backgroundColor,
      mode,
      stars,
      starSize,
      sparkle,
      arms,
      twist,
      armStrength,
      dust,
      core,
      coreSize,
      innerVoid,
      thickness,
      tilt,
      roll,
      scale,
      centerX,
      centerY,
      speed,
      twinkle,
      depth,
      glow,
      intensity,
      interactive,
      hoverWake,
      clickRipple,
      wakeStrength,
      rippleStrength,
      hoverBoost,
      paused,
      quality,
      reduced: reducedMotion
    };
    controllerRef.current?.sync();
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const controller = ((containerElem, currentPropsRef) => {
      let renderer;
      const canvas = document.createElement('canvas');
      canvas.setAttribute('aria-hidden', 'true');
      canvas.style.position = 'absolute';
      canvas.style.inset = '0';
      canvas.style.width = '100%';
      canvas.style.height = '100%';
      canvas.style.display = 'block';
      canvas.style.pointerEvents = 'none';
      containerElem.prepend(canvas);

      try {
        renderer = new THREE.WebGLRenderer({
          canvas,
          alpha: false,
          antialias: false,
          powerPreference: 'high-performance'
        });
      } catch {
        canvas.remove();
        return null;
      }

      if (!renderer.capabilities.isWebGL2) {
        renderer.dispose();
        canvas.remove();
        return null;
      }

      renderer.autoClear = false;

      const halfFloatOrByte =
        renderer.extensions.has('EXT_color_buffer_float') ||
        renderer.extensions.has('EXT_color_buffer_half_float')
          ? THREE.HalfFloatType
          : THREE.UnsignedByteType;

      const orthoCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      const quadGeom = new THREE.PlaneGeometry(2, 2);
      const ripples = Array.from({ length: 6 }, () => new THREE.Vector4(0, 0, -100, 0));
      const floatOrHalf = renderer.extensions.has('EXT_color_buffer_float')
        ? THREE.FloatType
        : THREE.HalfFloatType;

      const orbitUniforms = {
        uTime: { value: 0 },
        uSpin: { value: 0.11 },
        uCoreRadius: { value: 0.12 },
        uArms: { value: 3 },
        uTwist: { value: 3.5 },
        uEps: { value: 0.1 },
        uPattern: { value: 0.04 }
      };

      const starMaterial = new THREE.RawShaderMaterial({
        glslVersion: THREE.GLSL3,
        uniforms: {
          ...orbitUniforms,
          uState: { value: null },
          uStride: { value: 512 },
          uResolution: { value: new THREE.Vector2(1, 1) },
          uCenter: { value: new THREE.Vector2() },
          uFocal: { value: 1 },
          uDistance: { value: 3.6 },
          uIncline: { value: 1 },
          uRoll: { value: 0 },
          uPixelRatio: { value: 1 },
          uRealTime: { value: 0 },
          uDust: { value: 0.5 },
          uCore: { value: 1 },
          uVoid: { value: 0 },
          uSize: { value: 1.4 },
          uSizeScale: { value: 1 },
          uSparkle: { value: 0.08 },
          uTwinkle: { value: 0.4 },
          uBack: { value: 0.5 },
          uEnergy: { value: 0 },
          uInk: { value: 0 },
          uLabA: { value: new THREE.Vector3() },
          uLabB: { value: new THREE.Vector3() },
          uRipples: { value: ripples },
          uActive: { value: 0 },
          uStarGain: { value: 0.3 }
        },
        vertexShader: SHADER_STAR_VERT,
        fragmentShader: SHADER_STAR_FRAG,
        depthTest: false,
        depthWrite: false,
        transparent: true,
        blending: THREE.CustomBlending,
        blendEquation: THREE.AddEquation,
        blendSrc: THREE.OneFactor,
        blendDst: THREE.OneFactor,
        blendSrcAlpha: THREE.OneFactor,
        blendDstAlpha: THREE.OneFactor
      });

      const createQuadMat = (fragShader, uniforms) =>
        new THREE.RawShaderMaterial({
          glslVersion: THREE.GLSL3,
          uniforms,
          vertexShader: SHADER_FULLSCREEN_VERT,
          fragmentShader: fragShader,
          depthTest: false,
          depthWrite: false,
          blending: THREE.NoBlending
        });

      const perturbationMat = createQuadMat(SHADER_PERTURBATION, {
        ...orbitUniforms,
        uStatic: { value: null },
        uState: { value: null },
        uSegment: { value: new THREE.Vector4() },
        uGather: { value: 0 },
        uDrag: { value: 0 },
        uWidth: { value: 0.09 },
        uDecay: { value: 1 }
      });

      const downsampleMat = createQuadMat(SHADER_DOWNSAMPLE, {
        uSource: { value: null },
        uTexel: { value: new THREE.Vector2() }
      });

      const upsampleMat = createQuadMat(SHADER_UPSAMPLE, {
        uSource: { value: null },
        uBase: { value: null },
        uTexel: { value: new THREE.Vector2() }
      });

      const compositeMat = createQuadMat(SHADER_COMPOSITE, {
        uLines: { value: null },
        uBloom: { value: null },
        uBackground: { value: new THREE.Vector3() },
        uGlow: { value: 0.5 },
        uExposure: { value: 1 },
        uMode: { value: 0 },
        uGrain: { value: 0 }
      });

      const starPoints = new THREE.Points(new THREE.BufferGeometry(), starMaterial);
      starPoints.frustumCulled = false;

      const starScene = new THREE.Scene();
      starScene.add(starPoints);

      const quadMesh = new THREE.Mesh(quadGeom, compositeMat);
      quadMesh.frustumCulled = false;

      const quadScene = new THREE.Scene();
      quadScene.add(quadMesh);

      let cachedStarKey = '';
      let staticTexture = null;
      let stateTargets = [];
      let activeStateIndex = 0;

      const createRT = (w, h) =>
        new THREE.WebGLRenderTarget(Math.max(1, w), Math.max(1, h), {
          type: halfFloatOrByte,
          format: THREE.RGBAFormat,
          minFilter: THREE.LinearFilter,
          magFilter: THREE.LinearFilter,
          depthBuffer: false,
          stencilBuffer: false,
          generateMipmaps: false
        });

      let mainRT = null;
      let downsampleRTs = [];
      let upsampleRTs = [];
      let isDestroyed = false;
      let animFrameId = 0;
      let lastTime = 0;
      let isVisible = true;
      let simTime = 40;
      let realTime = 0;
      let hoverEnergy = 0;
      let viewWidth = 1;
      let viewHeight = 1;
      let pixelRatio = 1;
      let grainSeed = 0;
      let lastWakeTime = -100;

      const pointerState = {
        inside: false,
        disc: null,
        trail: null
      };

      const disposeRTs = () => {
        mainRT?.dispose();
        downsampleRTs.forEach((rt) => rt.dispose());
        upsampleRTs.forEach((rt) => rt.dispose());
        mainRT = null;
        downsampleRTs = [];
        upsampleRTs = [];
      };

      const renderPass = (material, target) => {
        quadMesh.material = material;
        renderer.setRenderTarget(target);
        renderer.render(quadScene, orthoCamera);
      };

      const rebuildGalaxy = () => {
        const p = currentPropsRef.current;
        const starCount = Math.round(clamp(p.stars, 2000, 250000));
        const cSize = clamp(p.coreSize, 0.02, 0.3);
        const thick = clamp(p.thickness, 0, 0.2);
        const key = [starCount, cSize, thick].join('|');
        if (key === cachedStarKey) return;
        cachedStarKey = key;

        starPoints.geometry.dispose();
        staticTexture?.dispose();
        stateTargets.forEach((rt) => rt.dispose());

        const buildData = (count, cRad, th) => {
          let seed = 23;
          const rng = () => (seed = (16807 * seed) % 0x7fffffff) / 0x7fffffff;
          const gauss = () =>
            Math.sqrt(-2 * Math.log(Math.max(rng(), 1e-9))) * Math.cos(TWO_PI * rng());

          const rows = Math.ceil(count / 512);
          const starBuf = new Float32Array(count * 8);
          const staticBuf = new Float32Array(512 * rows * 4);

          for (let i = 0; i < count; i++) {
            let aDist;
            let zDisp;
            const isBulge = rng() < 0.16;
            if (isBulge) {
              aDist = Math.min(
                cRad / Math.sqrt(Math.pow(Math.min(Math.max(rng(), 1e-4), 0.995), -2 / 3) - 1),
                4 * cRad
              );
              zDisp = gauss() * aDist * 0.5;
            } else {
              do {
                aDist = -0.32 * Math.log(Math.max(rng() * rng(), 1e-9));
              } while (aDist > 1.08);
              aDist = Math.max(aDist, 0.012);
              zDisp = gauss() * th * (0.5 + 0.5 * Math.exp(-aDist / 0.25));
            }
            const psi = rng() * TWO_PI;
            starBuf.set([aDist, psi, zDisp, rng(), +isBulge, rng(), rng(), rng()], i * 8);
            staticBuf.set([aDist, psi, +isBulge, 0], i * 4);
          }

          const geom = new THREE.BufferGeometry();
          const interleaved = new THREE.InterleavedBuffer(starBuf, 8);
          geom.setAttribute('aOrbit', new THREE.InterleavedBufferAttribute(interleaved, 4, 0));
          geom.setAttribute('aTraits', new THREE.InterleavedBufferAttribute(interleaved, 4, 4));
          geom.setAttribute('position', new THREE.InterleavedBufferAttribute(interleaved, 3, 0));

          const tex = new THREE.DataTexture(
            staticBuf,
            512,
            rows,
            THREE.RGBAFormat,
            floatOrHalf
          );
          tex.minFilter = THREE.NearestFilter;
          tex.magFilter = THREE.NearestFilter;
          tex.generateMipmaps = false;
          tex.needsUpdate = true;

          return { geometry: geom, texture: tex, rows };
        };

        const data = buildData(starCount, cSize, thick);
        starPoints.geometry = data.geometry;
        staticTexture = data.texture;

        stateTargets = [0, 1].map(
          () =>
            new THREE.WebGLRenderTarget(512, data.rows, {
              type: floatOrHalf,
              format: THREE.RGBAFormat,
              minFilter: THREE.NearestFilter,
              magFilter: THREE.NearestFilter,
              depthBuffer: false,
              stencilBuffer: false,
              generateMipmaps: false
            })
        );

        activeStateIndex = 0;
        for (const rt of stateTargets) {
          renderer.setRenderTarget(rt);
          renderer.setClearColor(0, 0);
          renderer.clear();
        }

        perturbationMat.uniforms.uStatic.value = staticTexture;
        starMaterial.uniforms.uState.value = stateTargets[0].texture;
      };

      const getProjection = () => {
        const p = currentPropsRef.current;
        const w = viewWidth * pixelRatio;
        const h = viewHeight * pixelRatio;
        const s = 0.36 * clamp(p.scale, 0.2, 4) * Math.min(w, 1.7 * h);
        return {
          incline: (clamp(p.tilt, 0, 85) * Math.PI) / 180,
          roll: (clamp(p.roll, -180, 180) * Math.PI) / 180,
          focal: 3.6 * s,
          center: [clamp(p.centerX, -0.5, 1.5) * w, (1 - clamp(p.centerY, -0.5, 1.5)) * h]
        };
      };

      const unproject = (clientX, clientY) => {
        const rect = containerElem.getBoundingClientRect();
        const proj = getProjection();
        const sx = (clientX - rect.left) * pixelRatio;
        const sy = (rect.height - (clientY - rect.top)) * pixelRatio;
        const nx = (sx - proj.center[0]) / proj.focal;
        const ny = (sy - proj.center[1]) / proj.focal;
        const cosRoll = Math.cos(proj.roll);
        const sinRoll = Math.sin(proj.roll);
        const rx = -sinRoll * nx + cosRoll * ny;
        const cosInc = Math.cos(proj.incline);
        const sinInc = Math.sin(proj.incline);
        const denom = cosInc - rx * sinInc;
        if (denom <= 0.02) return null;
        const dist = (3.6 * rx) / denom;
        return {
          x: (cosRoll * nx + sinRoll * ny) * (3.6 + dist * sinInc),
          y: dist
        };
      };

      const triggerRipple = (x = 0, y = 0) => {
        const p = currentPropsRef.current;
        if (p.reduced || p.paused) return;
        const strength = clamp(p.rippleStrength, 0, 3);
        let oldest = 0;
        let newest = 0;
        for (let i = 1; i < 6; i++) {
          if (ripples[i].z > ripples[newest].z) newest = i;
          if (ripples[i].z < ripples[oldest].z) oldest = i;
        }
        const topRip = ripples[newest];
        if (
          topRip.w > 0 &&
          realTime - topRip.z < 0.35 &&
          Math.hypot(topRip.x - x, topRip.y - y) < 0.15
        ) {
          topRip.w = Math.min(topRip.w + 0.3 * strength, 1.6 * strength);
        } else if (realTime - ripples[oldest].z > 7) {
          ripples[oldest].set(x, y, realTime, strength);
        } else {
          topRip.w = Math.min(topRip.w + 0.25 * strength, 1.6 * strength);
        }
        wake();
      };

      const hasActiveRipples = () =>
        ripples.some((r) => r.w > 0 && realTime - r.z < 7);

      const renderGalaxy = () => {
        if (!mainRT || !downsampleRTs.length) return;
        rebuildGalaxy();

        const p = currentPropsRef.current;
        const u = starMaterial.uniforms;
        const w = viewWidth * pixelRatio;
        const h = viewHeight * pixelRatio;
        const proj = getProjection();

        const bgRgb = parseColor(p.backgroundColor, [0.04, 0.04, 0.04]);
        const bgLuma = 0.2126 * bgRgb[0] + 0.7152 * bgRgb[1] + 0.0722 * bgRgb[2];
        const isInk = p.mode === 'ink' || (p.mode === 'auto' && bgLuma > 0.5);

        const colA = rgbToOklab(parseColor(p.colors[0], [0.48, 0.3, 1]));
        const colB = rgbToOklab(parseColor(p.colors[1], [1, 0.78, 0.95]));

        const numArms = Math.round(clamp(p.arms, 1, 8));
        const numTwist = clamp(p.twist, 0.5, 8);
        const aStrength = clamp(p.armStrength, 0, 1);

        u.uResolution.value.set(w, h);
        u.uCenter.value.set(proj.center[0], proj.center[1]);
        u.uFocal.value = proj.focal;
        u.uIncline.value = proj.incline;
        u.uRoll.value = proj.roll;
        u.uPixelRatio.value = pixelRatio;

        orbitUniforms.uTime.value = simTime;
        u.uRealTime.value = realTime;
        orbitUniforms.uArms.value = numArms;
        orbitUniforms.uTwist.value = numTwist;
        orbitUniforms.uEps.value =
          (0.92 * aStrength) / Math.sqrt(1 + numArms * numArms * numTwist * numTwist);

        u.uDust.value = clamp(p.dust, 0, 1);
        u.uCore.value = clamp(p.core, 0, 3);
        u.uVoid.value = clamp(p.innerVoid, 0, 0.6);
        u.uSize.value = clamp(p.starSize, 0.3, 6);
        u.uSparkle.value = 0.2 * clamp(p.sparkle, 0, 1);
        u.uTwinkle.value = p.reduced ? 0 : clamp(p.twinkle, 0, 1);
        u.uBack.value = 1 - clamp(p.depth, 0, 1);
        u.uEnergy.value = hoverEnergy;
        u.uInk.value = isInk ? 1 : 0;
        u.uLabA.value.set(colA[0], colA[1], colA[2]);
        u.uLabB.value.set(colB[0], colB[1], colB[2]);
        u.uActive.value = hasActiveRipples() ? 1 : 0;

        const starCount = Math.round(clamp(p.stars, 2000, 250000));
        const focalScale = Math.pow(proj.focal / 3.6 / pixelRatio / 380, 2);
        const countRatio = clamp(focalScale, 0.2, 1);
        const sizeScale = clamp(Math.pow(focalScale, 0.25), 0.9, 1.22);

        starPoints.geometry.setDrawRange(0, Math.round(starCount * countRatio));
        u.uSizeScale.value = sizeScale;
        u.uStarGain.value =
          0.3 *
          Math.sqrt(60000 / starCount) *
          clamp(focalScale / (countRatio * sizeScale * sizeScale), 0.5, 1.5);

        const compU = compositeMat.uniforms;
        compU.uBackground.value.set(toLinear(bgRgb[0]), toLinear(bgRgb[1]), toLinear(bgRgb[2]));
        compU.uGlow.value = clamp(p.glow, 0, 3);
        compU.uExposure.value =
          (isInk ? 4.5 : 1) * clamp(p.intensity, 0, 4) * (1 + 0.08 * hoverEnergy);
        compU.uMode.value = isInk ? 1 : 0;
        compU.uGrain.value = grainSeed;

        renderer.setRenderTarget(mainRT);
        renderer.setClearColor(0, 0);
        renderer.clear();
        renderer.render(starScene, orthoCamera);

        let currSrc = mainRT;
        for (const rt of downsampleRTs) {
          downsampleMat.uniforms.uSource.value = currSrc.texture;
          downsampleMat.uniforms.uTexel.value.set(1 / currSrc.width, 1 / currSrc.height);
          renderPass(downsampleMat, rt);
          currSrc = rt;
        }

        let currBloom = downsampleRTs[downsampleRTs.length - 1];
        for (let i = downsampleRTs.length - 2; i >= 0; i--) {
          upsampleMat.uniforms.uSource.value = currBloom.texture;
          upsampleMat.uniforms.uBase.value = downsampleRTs[i].texture;
          upsampleMat.uniforms.uTexel.value.set(1 / currBloom.width, 1 / currBloom.height);
          renderPass(upsampleMat, upsampleRTs[i]);
          currBloom = upsampleRTs[i];
        }

        compositeMat.uniforms.uLines.value = mainRT.texture;
        compositeMat.uniforms.uBloom.value = currBloom.texture;
        renderPass(compositeMat, null);
      };

      const getTargetHover = () => {
        const p = currentPropsRef.current;
        return pointerState.inside && p.interactive && !p.reduced
          ? clamp(p.hoverBoost, 0, 2)
          : 0;
      };

      const tick = (now) => {
        animFrameId = 0;
        if (isDestroyed) return;

        const dt = Math.min(0.05, Math.max(0, (now - lastTime) / 1000));
        lastTime = now;
        const p = currentPropsRef.current;

        hoverEnergy += (getTargetHover() - hoverEnergy) * (1 - Math.exp(-dt / 0.5));

        if (!p.paused && !p.reduced) {
          realTime += dt;
          simTime += dt * clamp(p.speed, -4, 4) * (1 + 0.25 * hoverEnergy);
          grainSeed = (grainSeed + 0.618034) % 1;
        }

        rebuildGalaxy();

        if (stateTargets.length && !p.paused && !p.reduced && dt > 0) {
          let gather = 0;
          let drag = 0;
          const trail = pointerState.trail;
          const disc = pointerState.disc;
          const pertU = perturbationMat.uniforms;

          if (pointerState.inside && p.interactive && p.hoverWake && trail && disc) {
            const moveDist = Math.hypot(disc.x - trail.x, disc.y - trail.y);
            if (moveDist > 1e-5) {
              const speedRatio = clamp((moveDist / Math.max(dt, 1 / 240) - 0.05) / 1.15, 0, 1);
              gather =
                0.9 *
                clamp(p.wakeStrength, 0, 3) *
                speedRatio *
                speedRatio *
                (3 - 2 * speedRatio) *
                (moveDist / (moveDist + 0.15948));
              drag = 0.25 * gather;
              pertU.uSegment.value.set(trail.x, trail.y, disc.x, disc.y);
              if (gather > 0) lastWakeTime = realTime;
            }
          }

          pointerState.trail = disc ? { x: disc.x, y: disc.y } : null;

          if (gather > 0 || realTime - lastWakeTime <= 24.5) {
            pertU.uGather.value = gather;
            pertU.uDrag.value = drag;
            pertU.uDecay.value = Math.exp(-dt / 3.5);
            pertU.uState.value = stateTargets[activeStateIndex].texture;
            pertU.uTime.value = simTime;

            quadMesh.material = perturbationMat;
            renderer.setRenderTarget(stateTargets[1 - activeStateIndex]);
            renderer.render(quadScene, orthoCamera);
            activeStateIndex = 1 - activeStateIndex;
            starMaterial.uniforms.uState.value = stateTargets[activeStateIndex].texture;
          }
        }

        renderGalaxy();

        const activeMotion = !p.paused && !p.reduced;
        const transitioning =
          Math.abs(hoverEnergy - getTargetHover()) > 0.002 ||
          hasActiveRipples() ||
          realTime - lastWakeTime < 24.5;

        if (isVisible && !document.hidden && (activeMotion || transitioning)) {
          animFrameId = requestAnimationFrame(tick);
        }
      };

      function wake() {
        if (!isDestroyed && !animFrameId && isVisible) {
          lastTime = performance.now();
          animFrameId = requestAnimationFrame(tick);
        }
      }

      const resize = () => {
        const rect = containerElem.getBoundingClientRect();
        viewWidth = Math.max(1, rect.width);
        viewHeight = Math.max(1, rect.height);
        pixelRatio =
          Math.min(window.devicePixelRatio || 1, 2) *
          clamp(currentPropsRef.current.quality, 0.25, 1);

        renderer.setPixelRatio(pixelRatio);
        renderer.setSize(viewWidth, viewHeight, false);

        const targetW = Math.round(viewWidth * pixelRatio);
        const targetH = Math.round(viewHeight * pixelRatio);

        disposeRTs();
        mainRT = createRT(targetW, targetH);

        const levels = clamp(Math.floor(Math.log2(Math.min(targetW, targetH) / 8)), 3, 7);
        for (let i = 1; i <= levels; i++) {
          downsampleRTs.push(createRT(Math.max(1, targetW >> i), Math.max(1, targetH >> i)));
          upsampleRTs.push(createRT(Math.max(1, targetW >> i), Math.max(1, targetH >> i)));
        }

        renderGalaxy();
        wake();
      };

      const onPointerMove = (e) => {
        const p = currentPropsRef.current;
        if (e.pointerType === 'touch' || !p.interactive) return;
        if (!pointerState.inside) {
          pointerState.inside = true;
          pointerState.trail = null;
          wake();
        }
        const coords = unproject(e.clientX, e.clientY);
        pointerState.disc = coords && Math.hypot(coords.x, coords.y) < 1.6 ? coords : null;
        if (!pointerState.disc) pointerState.trail = null;
        wake();
      };

      const onPointerLeave = () => {
        pointerState.inside = false;
        pointerState.disc = null;
        pointerState.trail = null;
        wake();
      };

      const onPointerDown = (e) => {
        const p = currentPropsRef.current;
        if (e.button !== 0 || !p.interactive || !p.clickRipple) return;
        const coords = unproject(e.clientX, e.clientY);
        const hit = coords && Math.hypot(coords.x, coords.y) < 1.2;
        triggerRipple(hit ? coords.x : 0, hit ? coords.y : 0);
      };

      containerElem.addEventListener('pointermove', onPointerMove);
      containerElem.addEventListener('pointerleave', onPointerLeave);
      containerElem.addEventListener('pointercancel', onPointerLeave);
      containerElem.addEventListener('pointerdown', onPointerDown);

      const resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(containerElem);

      const intersectionObserver = new IntersectionObserver(
        (entries) => {
          isVisible = entries.some((e) => e.isIntersecting);
          if (isVisible) wake();
        },
        { rootMargin: '80px' }
      );
      intersectionObserver.observe(containerElem);

      const onVisibilityChange = () => {
        if (!document.hidden) wake();
      };
      document.addEventListener('visibilitychange', onVisibilityChange);

      const onContextLost = (e) => e.preventDefault();
      canvas.addEventListener('webglcontextlost', onContextLost);

      resize();

      return {
        sync: () => {
          const currentPR =
            Math.min(window.devicePixelRatio || 1, 2) *
            clamp(currentPropsRef.current.quality, 0.25, 1);
          if (Math.abs(currentPR - pixelRatio) > 0.001) resize();
          else renderGalaxy();
          wake();
        },
        destroy: () => {
          isDestroyed = true;
          cancelAnimationFrame(animFrameId);
          containerElem.removeEventListener('pointermove', onPointerMove);
          containerElem.removeEventListener('pointerleave', onPointerLeave);
          containerElem.removeEventListener('pointercancel', onPointerLeave);
          containerElem.removeEventListener('pointerdown', onPointerDown);
          document.removeEventListener('visibilitychange', onVisibilityChange);
          canvas.removeEventListener('webglcontextlost', onContextLost);
          resizeObserver.disconnect();
          intersectionObserver.disconnect();
          disposeRTs();
          starPoints.geometry.dispose();
          staticTexture?.dispose();
          stateTargets.forEach((rt) => rt.dispose());
          quadGeom.dispose();
          [starMaterial, perturbationMat, downsampleMat, upsampleMat, compositeMat].forEach(
            (m) => m.dispose()
          );
          renderer.dispose();
          renderer.forceContextLoss();
          canvas.remove();
        },
        ripple: () => triggerRipple(0, 0)
      };
    })(container, propsRef);

    controllerRef.current = controller;
    return () => {
      controller?.destroy();
      controllerRef.current = null;
    };
  }, []);

  useImperativeHandle(ref, () => ({
    ripple: () => controllerRef.current?.ripple()
  }), []);

  return (
    <div
      ref={containerRef}
      className={`relative isolate h-full min-h-[240px] w-full overflow-hidden ${className}`}
      style={{ backgroundColor, ...style }}
    >
      {children && (
        <div className="relative z-10 h-full w-full pointer-events-auto">
          {children}
        </div>
      )}
    </div>
  );
});

BinaryOrbits.displayName = 'BinaryOrbits';

export { BinaryOrbits };
export default BinaryOrbits;
