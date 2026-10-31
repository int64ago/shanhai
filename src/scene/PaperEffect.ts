import { BlendFunction, Effect } from 'postprocessing'
import { NOISE_GLSL } from './noise.glsl'

/**
 * 整幅画面的宣纸质感：纤维纹理压在所有内容上，四周微微泛黄。
 * 放在后期最末，保证 3D 物体和背景是“画在同一张纸上”。
 */
export class PaperEffect extends Effect {
  constructor() {
    super(
      'PaperEffect',
      /* glsl */ `
        ${NOISE_GLSL}
        void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
          vec2 px = uv * resolution;
          float fiber = fbm(px * vec2(0.02, 0.06)) * 0.5 + fbm(px * 0.35) * 0.5;
          vec3 c = inputColor.rgb * (0.93 + 0.1 * fiber);
          float d = distance(uv, vec2(0.5));
          c *= mix(vec3(1.0), vec3(0.92, 0.88, 0.8), smoothstep(0.4, 0.85, d));
          outputColor = vec4(c, inputColor.a);
        }
      `,
      { blendFunction: BlendFunction.NORMAL },
    )
  }
}
