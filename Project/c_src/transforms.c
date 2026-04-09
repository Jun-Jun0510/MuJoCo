/*
 * transforms.c
 * Clarke / Park 変換および逆変換 (C言語版)
 *
 * Python 版 (transforms.py) と数値一致することを確認するための参照実装。
 * 将来の STM32 マイコン実装を見据え、float32 で記述。
 *
 * ビルド & 実行:
 *   cc -O2 -Wall -o transforms_test transforms.c -lm
 *   ./transforms_test
 */

#include <stdio.h>
#include <math.h>

/* --- 定数 --- */
#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif
#define SQRT3       1.7320508075688772f
#define INV_SQRT3   0.5773502691896258f   /* 1/√3    */
#define HALF_SQRT3  0.8660254037844386f   /* √3/2   */

/* 出力を複数値返すための構造体 */
typedef struct { float alpha; float beta;  } AB_t;
typedef struct { float d;     float q;     } DQ_t;
typedef struct { float a;     float b;     float c; } ABC_t;

/* -----------------------------------------------------------------------
 * Clarke 変換: abc → αβ  (振幅不変形)
 *   iα = (2/3) * (ia - 0.5*ib - 0.5*ic)
 *   iβ = (1/√3) * (ib - ic)
 * ----------------------------------------------------------------------- */
AB_t clarke(float ia, float ib, float ic)
{
    AB_t out;
    out.alpha = (2.0f / 3.0f) * (ia - 0.5f * ib - 0.5f * ic);
    out.beta  = INV_SQRT3 * (ib - ic);
    return out;
}

/* -----------------------------------------------------------------------
 * 逆Clarke 変換: αβ → abc
 *   ia =  iα
 *   ib = -0.5*iα + (√3/2)*iβ
 *   ic = -0.5*iα - (√3/2)*iβ
 * ----------------------------------------------------------------------- */
ABC_t inv_clarke(float i_alpha, float i_beta)
{
    ABC_t out;
    out.a =  i_alpha;
    out.b = -0.5f * i_alpha + HALF_SQRT3 * i_beta;
    out.c = -0.5f * i_alpha - HALF_SQRT3 * i_beta;
    return out;
}

/* -----------------------------------------------------------------------
 * Park 変換: αβ → dq
 *   id =  iα*cosθe + iβ*sinθe
 *   iq = -iα*sinθe + iβ*cosθe
 * ----------------------------------------------------------------------- */
DQ_t park(float i_alpha, float i_beta, float theta_e)
{
    DQ_t out;
    float c = cosf(theta_e);
    float s = sinf(theta_e);
    out.d =  i_alpha * c + i_beta * s;
    out.q = -i_alpha * s + i_beta * c;
    return out;
}

/* -----------------------------------------------------------------------
 * 逆Park 変換: dq → αβ
 *   iα = id*cosθe - iq*sinθe
 *   iβ = id*sinθe + iq*cosθe
 * ----------------------------------------------------------------------- */
AB_t inv_park(float i_d, float i_q, float theta_e)
{
    AB_t out;
    float c = cosf(theta_e);
    float s = sinf(theta_e);
    out.alpha = i_d * c - i_q * s;
    out.beta  = i_d * s + i_q * c;
    return out;
}

/* =======================================================================
 * 単体動作確認 (Python 側 transforms.py と数値比較)
 * ======================================================================= */
int main(void)
{
    const float Im      = 10.0f;
    const float f       = 50.0f;
    const float omega_e = 2.0f * (float)M_PI * f;
    const float t       = 0.003f;
    const float theta_e = omega_e * t;

    /* 3相平衡電流 */
    float ia = Im * cosf(omega_e * t);
    float ib = Im * cosf(omega_e * t - 2.0f * (float)M_PI / 3.0f);
    float ic = Im * cosf(omega_e * t - 4.0f * (float)M_PI / 3.0f);

    /* 1) Clarke */
    AB_t  ab1 = clarke(ia, ib, ic);
    /* 2) Park */
    DQ_t  dq  = park(ab1.alpha, ab1.beta, theta_e);
    /* 3) 逆Park */
    AB_t  ab2 = inv_park(dq.d, dq.q, theta_e);
    /* 4) 逆Clarke */
    ABC_t abc = inv_clarke(ab2.alpha, ab2.beta);

    printf("=== Input (abc) ===\n");
    printf("  ia = %+.6f, ib = %+.6f, ic = %+.6f\n", ia, ib, ic);
    printf("=== alpha-beta ===\n");
    printf("  i_alpha = %+.6f, i_beta = %+.6f\n", ab1.alpha, ab1.beta);
    printf("=== dq  (theta_e = %.4f rad) ===\n", theta_e);
    printf("  i_d = %+.6f, i_q = %+.6f\n", dq.d, dq.q);
    printf("=== Round-trip (inv_park -> inv_clarke) ===\n");
    printf("  ia' = %+.6f, ib' = %+.6f, ic' = %+.6f\n", abc.a, abc.b, abc.c);
    printf("=== Round-trip error ===\n");
    printf("  |dia| = %.2e\n", fabsf(ia - abc.a));
    printf("  |dib| = %.2e\n", fabsf(ib - abc.b));
    printf("  |dic| = %.2e\n", fabsf(ic - abc.c));

    float mag = sqrtf(dq.d * dq.d + dq.q * dq.q);
    printf("\n  sqrt(id^2+iq^2) = %.6f  (expected Im = %.6f)\n", mag, Im);

    return 0;
}
