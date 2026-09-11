"""Numeric real-root finder for huge-coefficient integer polynomials (balanced scaling).

Given ascending coefs c_k of poly P(y) and root bound X, evaluates balanced poly
q(z) = sum c_k X^k z^k (z = y/X in [-1,1]) with mpmath at high precision,
rounds candidate roots back to integers and EXACT-verifies on P. No float illusions:
every candidate is confirmed by exact integer evaluation.
"""
import mpmath
import sympy


def numeric_int_roots(coefs_asc, X, prec_bits=3200):
    deg = max(k for k, c in enumerate(coefs_asc) if c)
    cs = coefs_asc[:deg + 1]
    if deg == 0:
        return []
    P = sympy.Poly(list(reversed(cs)), sympy.symbols('y'), domain=sympy.QQ)
    balanced = [c * (X ** k) for k, c in enumerate(cs)]
    mpmath.mp.prec = prec_bits
    coeffs_m = [mpmath.mpf(int(b)) for b in reversed(balanced)]
    try:
        roots = mpmath.polyroots(coeffs_m, maxsteps=300, extraprec=2500, error=False)
    except Exception:
        return []
    out = []
    for z0 in roots:
        if abs(mpmath.im(z0)) > mpmath.mpf('1e-30') * max(1, abs(mpmath.re(z0))):
            continue
        yv = mpmath.re(z0) * X
        cand = int(mpmath.nint(yv))
        if abs(cand) <= X and P.eval(cand) == 0:
            out.append(cand)
    return out
