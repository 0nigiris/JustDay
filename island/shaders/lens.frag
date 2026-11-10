#version 440
// Линза «жидкого стекла»: под карточкой видны обои, но по краю они загибаются внутрь,
// как свет в толще воды, и чуть расходятся по цветам. Обои берём картинкой, потому что
// Wayland не отдаёт нам то, что под окном, а размытие KWin плоское и линзы не умеет.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 size;      // карточка, px
    vec2 origin;    // её левый верхний угол на экране, px
    vec4 img;       // где лежат обои на экране: x, y, w, h (с учётом обрезки)
    float radius;
    float bezel;    // ширина загиба у края, px
    float wobble;   // «рябь» при движении, 0..1
    float time;
};
layout(binding = 1) uniform sampler2D wallTex;

float sdBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

vec3 tap(vec2 px) { return texture(wallTex, (px - img.xy) / img.zw).rgb; }

void main() {
    vec2 p = qt_TexCoord0 * size;
    vec2 c = p - size * 0.5;
    float d = sdBox(c, size * 0.5, radius);
    // Нормаль края — по градиенту расстояния.
    vec2 e = vec2(0.5, 0.0);
    vec2 n = normalize(vec2(sdBox(c + e.xy, size * 0.5, radius) - sdBox(c - e.xy, size * 0.5, radius),
                            sdBox(c + e.yx, size * 0.5, radius) - sdBox(c - e.yx, size * 0.5, radius)) + 1e-5);
    float t = clamp(1.0 + d / bezel, 0.0, 1.0);          // 0 в середине, 1 на самом краю
    float bend = t * t * t;
    // Середина слегка увеличена, край тянет картинку снаружи внутрь.
    vec2 q = c * 0.94 - n * bend * bezel * 1.6;
    q += vec2(sin(p.y * 0.09 + time * 6.0), cos(p.x * 0.05 + time * 5.0)) * wobble * 3.0;
    vec2 s = origin + size * 0.5 + q;
    // Мягкое размытие: 12 точек по кругу и центр. Чётче не надо — значки должны читаться.
    vec3 col = tap(s) * 0.2;
    for (int i = 0; i < 12; i++) {
        float a = float(i) * 0.5236;
        float r = (i % 2 == 0) ? 9.0 : 5.0;
        col += tap(s + vec2(cos(a), sin(a)) * r) * (0.8 / 12.0);
    }
    // Радуга по самой кромке.
    vec2 ca = n * bend * 2.5;
    col.r = mix(col.r, tap(s + ca).r, bend);
    col.b = mix(col.b, tap(s - ca).b, bend);
    // Чтобы значки читались на любых обоях: притемнить и подсушить пёстрое.
    float l = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(vec3(l), col, 0.85);
    col = col * 0.62 + 0.03;
    float a = clamp(0.5 - d, 0.0, 1.0);
    fragColor = vec4(col, 1.0) * a * qt_Opacity;
}
