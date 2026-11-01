import { BackSide, Color, ShaderMaterial, Vector3, type Texture } from 'three'
import { NOISE_GLSL } from '../../scene/noise.glsl'
import { INK } from './palette'

export interface InkOptions {
  map: Texture | null
  /** 颜料饱和度：0 = 纯水墨，1 = 贴图原色 */
  saturation?: number
  /** 写意尾巴模式：沿 +X 方向的长度（模型单位），> 0 时启用笔触与飞白 */
  tailLength?: number
  /** 可选设色染印（如黑尾、赤尾、丹羽） */
  tint?: string
  /** 浓墨加成（0..1，如黑尾取 0.72） */
  inkBoost?: number
  /** 尾尖留白强度：白梢狐尾取 1，赤尾等通体设色取 0。 */
  tipWhite?: number
}

/** 光从左上前方来，与场景的留白方向一致 */
const LIGHT = new Vector3(-0.5, 0.85, 0.45).normalize()

// 顶点着色器共用：支持蒙皮，输出视空间法线、视线方向、世界坐标和未变形的模型坐标
const VERTEX = /* glsl */ `
  #include <common>
  #include <skinning_pars_vertex>
  varying vec2 vUv;
  varying vec3 vN;
  varying vec3 vViewDir;
  varying vec3 vWorld;
  varying vec3 vObj;
  void main() {
    vUv = uv;
    vObj = position;
    #include <beginnormal_vertex>
    #include <skinbase_vertex>
    #include <skinnormal_vertex>
    #include <defaultnormal_vertex>
    #include <begin_vertex>
    #include <skinning_vertex>
    #include <project_vertex>
    vN = normalize(transformedNormal);
    vViewDir = normalize(-mvPosition.xyz);
    #ifdef USE_INSTANCING
      vWorld = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz;
    #else
      vWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;
    #endif
  }
`

const FRAGMENT = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uHasMap;
  uniform vec3 uPaper;
  uniform vec3 uInk;
  uniform vec3 uLight;
  uniform float uSat;
  uniform float uTailLen;
  uniform vec3 uTint;
  uniform float uInkBoost;
  uniform float uTipWhite;
  varying vec2 vUv;
  varying vec3 vN;
  varying vec3 vViewDir;
  varying vec3 vWorld;
  varying vec3 vObj;
  ${NOISE_GLSL}

  void main() {
    vec3 albedo = uHasMap > 0.5 ? texture2D(uMap, vUv).rgb : vec3(0.6);
    float lum = dot(albedo, vec3(0.2126, 0.7152, 0.0722));
    vec3 N = normalize(vN);
    vec3 V = normalize(vViewDir);
    vec3 L = normalize((viewMatrix * vec4(uLight, 0.0)).xyz);
    float ndl = dot(N, L) * 0.5 + 0.5;
    float fres = 1.0 - abs(dot(N, V));

    // 用未变形的模型坐标取噪声，纹理粘在皮毛上；用世界坐标的话动起来晕染会在身上游动
    float wet = fbm(vObj.xz * 5.0 + vObj.y * 3.0);   // 大片水渍起伏
    float fiber = fbm(vObj.xy * 40.0 + vObj.z * 23.0); // 干笔颗粒

    // 颜料：贴图色相，提亮到水彩的透明感；分母设下限，避免深褐色的瞳孔、眼线被拉成亮橙色
    vec3 hue = albedo / max(max(albedo.r, max(albedo.g, albedo.b)), 0.24);
    vec3 pigment = mix(vec3(1.0), hue, uSat) * uTint;
    float ink = clamp((1.0 - smoothstep(0.02, 0.18, lum)) + uInkBoost, 0.0, 1.0);       // 深处：瞳孔、眼线、腿、耳尖、鼻 → 浓墨

    float tone = clamp((1.0 - ndl) * 0.9 + (1.0 - lum) * 0.28 + (wet - 0.5) * 0.35, 0.0, 1.0);

    float alpha = 1.0;
    if (uTailLen > 0.0) {
      // 写意尾：沿长度方向的顺毛笔触，根浓梢淡，尾梢留白并以飞白收笔
      float u = clamp(vObj.x / uTailLen, 0.0, 1.0);
      float a = atan(vObj.y, vObj.z);
      float streak = fbm(vec2(u * 2.0, a * 6.0));
      float hair = vnoise(vec2(u * 8.0, a * 36.0));
      tone = clamp(tone * 0.65 + (1.0 - u) * 0.25 + (streak - 0.5) * 0.32, 0.0, 1.0);
      ink = max(ink * (0.25 + uInkBoost * 0.65), smoothstep(0.14, 0.0, u) * 0.22 + uInkBoost * 0.68);
      if (u > 0.88 && hair < (u - 0.88) * 6.5) discard;
      // 尾尖留白：赤狐尾梢本就是白的，黑尾/染色尾则按 uInkBoost 保留浓墨尾梢
      pigment = mix(pigment, vec3(1.0), smoothstep(0.68, 0.90, u) * uTipWhite * (1.0 - uInkBoost));
    }

    // 第一遍淡彩铺底，第二遍在背光处叠一层，边界带水渍的硬边
    float wash1 = smoothstep(0.12, 0.3, tone + (fiber - 0.5) * 0.2);
    float wash2 = smoothstep(0.52, 0.58, tone + (wet - 0.5) * 0.3);
    vec3 col = uPaper * mix(vec3(1.0), pigment, 0.35 + 0.65 * wash1);
    col *= mix(vec3(1.0), vec3(0.74, 0.76, 0.8), wash2);
    // 浓墨部位与轮廓内侧的墨线
    col = mix(col, uInk, ink * 0.92);
    float rim = smoothstep(0.72, 0.95, fres + (fiber - 0.5) * 0.35);
    col = mix(col, uInk, rim * 0.65);
    // 纸面颗粒
    col *= 0.95 + 0.07 * fiber;

    gl_FragColor = vec4(col, alpha);
    #include <colorspace_fragment>
  }
`

export function createInkMaterial({
  map,
  saturation = 0.8,
  tailLength = 0,
  tint = '#ffffff',
  inkBoost = 0,
  tipWhite = 1,
}: InkOptions) {
  return new ShaderMaterial({
    uniforms: {
      uMap: { value: map },
      uHasMap: { value: map ? 1 : 0 },
      uPaper: { value: new Color(INK.paper) },
      uInk: { value: new Color(INK.ink) },
      uLight: { value: LIGHT },
      uSat: { value: saturation },
      uTailLen: { value: tailLength },
      uTint: { value: new Color(tint) },
      uInkBoost: { value: inkBoost },
      uTipWhite: { value: tipWhite },
    },
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
  })
}

/**
 * 外轮廓墨线（反向外壳）：沿法线外扩、只画背面。宽度随位置起伏，模拟毛笔提按。
 */
export function createOutlineMaterial(width = 0.006, depthBias = 0.0012) {
  return new ShaderMaterial({
    side: BackSide,
    uniforms: {
      uInk: { value: new Color(INK.ink) },
      uWidth: { value: width },
      uDepthBias: { value: depthBias },
    },
    vertexShader: /* glsl */ `
      #include <common>
      #include <skinning_pars_vertex>
      uniform float uWidth;
      uniform float uDepthBias;
      ${NOISE_GLSL}
      void main() {
        #include <beginnormal_vertex>
        #include <skinbase_vertex>
        #include <skinnormal_vertex>
        #include <begin_vertex>
        float press = 0.35 + 1.3 * vnoise(position.xy * 9.0 + position.z * 5.0);
        transformed += normalize(objectNormal) * uWidth * press;
        #include <skinning_vertex>
        #include <project_vertex>
        // 轻微深度后退，防止 AI 网格表面的浅凹凸（胸毛、吻部）被自身背面穿出黑斑
        gl_Position.z += uDepthBias * gl_Position.w;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uInk;
      void main() {
        gl_FragColor = vec4(uInk, 1.0);
        #include <colorspace_fragment>
      }
    `,
  })
}
