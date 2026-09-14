from trace_grabber.analytics import territory_svg, Territory

def test_svg_is_wellformed_and_labelled():
    svg = territory_svg(Territory(30.0, 30.0, 40.0))
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert svg.count("<rect") >= 3          # three third-bands (plus optional goal boxes)
    for label in ("30%", "40%"):
        assert label in svg

def test_svg_dark_variant_differs():
    t = Territory(33.3, 33.3, 33.4)
    assert territory_svg(t, dark=True) != territory_svg(t, dark=False)
