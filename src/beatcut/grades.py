"""Colour grades as ffmpeg filter chains.

``dark`` and ``dark-vivid`` come from the author's gym edits: lower exposure, crushed highlights,
cool shadows, a vignette and light grain. ``dark-vivid`` keeps more colour, because the muted look
felt lifeless after the opening.
"""
from __future__ import annotations

_DARK = ("eq=brightness=-0.05:contrast=1.28:saturation={sat}:gamma=0.72,"
         "curves=all='0/0 0.30/0.10 0.65/0.36 1/0.72',"
         "colorbalance=rs=-0.03:bs=0.05:rm=-0.02:bm=0.02,"
         "vignette=angle=PI/3,noise=alls=4:allf=t")

GRADES: dict[str, str] = {
    "none": "",
    "dark": _DARK.format(sat=0.58),
    "dark-vivid": _DARK.format(sat=1.2),
    "cinematic": ("eq=brightness=-0.06:contrast=1.25:saturation=0.80:gamma=0.78,"
                  "curves=all='0/0 0.30/0.13 0.65/0.42 1/0.78',"
                  "colorbalance=rs=-0.04:bs=0.07:rm=-0.02:bm=0.03,"
                  "vignette=angle=PI/3.2,noise=alls=7:allf=t"),
    "mono": "hue=s=0,eq=contrast=1.35:gamma=0.85,vignette=angle=PI/3.5,noise=alls=6:allf=t",
    "warm": "eq=contrast=1.1:saturation=1.1,colorbalance=rs=0.05:gs=0.01:bs=-0.05:rh=0.04:bh=-0.04",
}

DESCRIPTIONS: dict[str, str] = {
    "none": "No grade.",
    "dark": "Muted, dark and cool, with crushed highlights, vignette and grain.",
    "dark-vivid": "Same dark curve, with stronger colour.",
    "cinematic": "Slightly lifted dark look that keeps the reds.",
    "mono": "High-contrast black and white with grain.",
    "warm": "Gentle warm shift for daylight and lifestyle shots.",
}


def grade_filter(name: str) -> str:
    """Return the filter chain for ``name``; an unknown name raises ``KeyError`` with the choices."""
    if name.startswith("custom:"):
        return name[len("custom:"):]
    try:
        return GRADES[name]
    except KeyError:
        raise KeyError(f"unknown grade {name!r}; choose one of {', '.join(GRADES)} or 'custom:<filters>'") \
            from None
