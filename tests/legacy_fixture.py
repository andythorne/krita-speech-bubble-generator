"""Synthetic original-plugin SVG, in Krita's saved representation."""


NORTH_PATH = (
    "M117 10L123 0L129 10"
    "C207.667 10 247 23.6667 247 51"
    "C247 78.3333 205.667 92 123 92"
    "C41 92 0 78.3333 0 51"
    "C0 23.6667 39 10 117 10Z"
)


def legacy_corner_path(horizontal=1, vertical=-1, length=20):
    """Original 240-by-100 bounding box, including its quadratic corner cutout."""
    segments = (
        ("M", ((120, 0),)),
        ("Q", ((168, 0), (204, 10))),
        ("L", ((240 + length, -length),)),
        ("L", ((216, 15),)),
        ("Q", ((240, 30), (240, 50))),
        ("Q", ((240, 100), (120, 100))),
        ("Q", ((0, 100), (0, 50))),
        ("Q", ((0, 0), (120, 0))),
    )
    result = []
    for command, points in segments:
        result.append(command)
        result.append(" ".join("{} {}".format(
            x if horizontal > 0 else 240 - x,
            y if vertical < 0 else 100 - y) for x, y in points))
    return "".join(result) + "Z"


def legacy_svg(path=NORTH_PATH, extra="", transform="matrix(0.36 0 0 0.36 20 160)",
               text_transform="matrix(0.36 0 0 0.36 11.36 154.96)"):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg"><defs/>'
        '<path id="shape0" transform="' + transform + '" fill="#ffffff" '
        'stroke="#112233" stroke-width="3" stroke-linejoin="round" d="' + path + '"/>'
        '<text id="shape1" transform="' + text_transform + '" fill="#334455" '
        'x="147" y="57" text-anchor="middle" '
        'style="font-family: Sans Serif;font-size: 14;">First &amp; second</text>'
        '<text id="shape2" transform="' + text_transform + '" fill="#334455" '
        'x="147" y="71" text-anchor="middle" '
        'style="font-family: Sans Serif;font-size: 14;">A '
        '<tspan style="font-weight: 700;">bold</tspan> word</text>'
        + extra + '</svg>'
    )
