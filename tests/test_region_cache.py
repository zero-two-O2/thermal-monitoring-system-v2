"""
Region cache tests.

These are hardware-light: the HALCON region tuples are built by the
production code itself, so the assertions focus on alignment with the
store ordering, enabled/disabled handling, rebuild invalidation, and
agreement between mask pixel counts and real HALCON regions.
"""

from __future__ import annotations

import halcon as ha

from conftest import make_config
from roi.geometry import CircleROI, EllipseROI, PolygonROI, Rectangle1ROI, Rectangle2ROI
from roi_engine.masks import MaskCache
from roi_engine.region_cache import RegionCache
from roi_engine.store.factory import build_store
from roi_engine.types import ALL_SHAPES, ROIShape


def _geometry_batch() -> list:
    geoms: list = []
    for i in range(3):
        geoms.append(Rectangle1ROI(20 + i * 100, 20, 60 + i * 100, 80))
    geoms.append(CircleROI(200, 300, 25))
    geoms.append(CircleROI(400, 500, 40))
    geoms.append(EllipseROI(120, 300, 0.5, 30, 12))
    geoms.append(Rectangle2ROI(250, 250, -0.3, 40, 15))
    geoms.append(
        PolygonROI(((100, 300), (130, 300), (140, 330), (120, 350), (95, 340)))
    )
    return geoms


def _all_type_configs(enabled_ids: set[str] | None = None) -> list:
    enabled_ids = enabled_ids or set()
    return [
        make_config(f"g{i}", geom, enabled=f"g{i}" in enabled_ids)
        for i, geom in enumerate(_geometry_batch())
    ]


def test_regions_before_image_have_area() -> None:
    """Regions must be valid before any image exists (clip guard works)."""
    configs = _all_type_configs({f"g{i}" for i in range(8)})
    store = build_store("cam_1", "pos_1", configs)
    cache = RegionCache()
    cache.rebuild(store)
    for shape in ALL_SHAPES:
        regions = cache.regions(shape)
        assert regions is not None
        areas = ha.area_center(regions)[0]
        assert len(areas) == store.store_for(shape).enabled_count()
        assert all(a > 0 for a in areas)


def test_batch_counts_match_enabled() -> None:
    """Region tuple sizes equal the enabled counts per type."""
    configs = _all_type_configs({f"g{i}" for i in range(8)})
    store = build_store("cam_1", "pos_1", configs)
    cache = RegionCache()
    cache.rebuild(store)
    for shape in ALL_SHAPES:
        regions = cache.regions(shape)
        assert regions is not None
        assert len(ha.area_center(regions)[0]) == (
            store.store_for(shape).enabled_count()
        )
        assert cache.region_count(shape) == store.store_for(shape).enabled_count()


def test_disabled_only_type_is_none() -> None:
    """A type with zero enabled ROIs yields None and zero count."""
    configs = _all_type_configs({"g0"})
    store = build_store("cam_1", "pos_1", configs)
    cache = RegionCache()
    cache.rebuild(store)
    assert cache.regions(ROIShape.CIRCLE) is None
    assert cache.region_count(ROIShape.CIRCLE) == 0
    assert cache.regions(ROIShape.RECTANGLE1) is not None
    assert cache.region_count(ROIShape.RECTANGLE1) == 1


def test_needs_rebuild_only_on_generation_change() -> None:
    """Same store stays cached; a new generation invalidates."""
    configs = _all_type_configs({f"g{i}" for i in range(8)})
    store1 = build_store("cam_1", "pos_1", configs)
    cache = RegionCache()
    cache.rebuild(store1)
    assert not cache.needs_rebuild(store1)
    store2 = build_store("cam_1", "pos_1", configs)
    assert not cache.needs_rebuild(store2)
    configs_new = configs
    store3 = build_store("cam_1", "pos_1", configs_new, generation=2)
    assert cache.needs_rebuild(store3)
    cache.rebuild(store3)
    assert not cache.needs_rebuild(store3)


def test_clear_resets_to_empty() -> None:
    """Clear() returns to the pre-first-rebuild state."""
    configs = _all_type_configs({f"g{i}" for i in range(8)})
    store = build_store("cam_1", "pos_1", configs)
    cache = RegionCache()
    cache.rebuild(store)
    cache.clear()
    assert cache.needs_rebuild(store)
    for shape in ALL_SHAPES:
        assert cache.regions(shape) is None


def test_polygon_alignment_matches_direct_generation() -> None:
    """Polygon regions align with the enabled store order."""
    geoms = [
        PolygonROI(((10, 10), (40, 10), (40, 40), (10, 40))),
        PolygonROI(((50, 50), (90, 50), (90, 90), (50, 90))),
        PolygonROI(((110, 110), (130, 110), (140, 130), (120, 140))),
    ]
    configs = [
        make_config("p2", geoms[2], enabled=True),
        make_config("p0", geoms[0], enabled=True),
        make_config("p1", geoms[1], enabled=True),
    ]
    store = build_store("cam_1", "pos_1", configs)
    cache = RegionCache()
    cache.rebuild(store)
    regions = cache.regions(ROIShape.POLYGON)
    assert regions is not None
    areas = ha.area_center(regions)[0]
    for j, cfg in enumerate(configs):
        geom = cfg.geometry
        expected = ha.gen_region_polygon_filled(
            [float(v) for v in geom.rows], [float(v) for v in geom.cols]
        )
        assert areas[j] == ha.area_center(expected)[0][0], (
            f"index {j} ({cfg.roi_id}): cached {areas[j]} vs direct "
            f"{ha.area_center(expected)[0][0]}"
        )


def test_mask_pixel_counts_match_halcon_within_two_percent() -> None:
    """Mask counts agree with real HALCON regions within 2%."""
    raw_configs = [
        make_config("c0", CircleROI(100, 120, 30), enabled=True),
        make_config("c1", CircleROI(400, 520, 45), enabled=True),
        make_config("c2", CircleROI(300, 300, 60), enabled=True),
        make_config("e0", EllipseROI(150, 200, 0.4, 40, 15), enabled=True),
        make_config("e1", EllipseROI(350, 400, -1.1, 25, 40), enabled=True),
        make_config("r2", Rectangle2ROI(200, 200, 0.6, 45, 20), enabled=True),
        make_config("r2b", Rectangle2ROI(420, 150, -0.2, 30, 10), enabled=True),
        make_config(
            "p0",
            PolygonROI(((80, 500), (140, 490), (160, 540), (120, 580), (70, 560))),
            enabled=True,
        ),
        make_config("r1", Rectangle1ROI(10, 10, 50, 90), enabled=True),
        make_config("r1b", Rectangle1ROI(60, 60, 100, 100), enabled=False),
    ]
    store = build_store("cam_1", "pos_1", raw_configs)
    masks = MaskCache()
    masks.rebuild(store, (480, 640))
    for shape in (
        ROIShape.CIRCLE,
        ROIShape.ELLIPSE,
        ROIShape.RECTANGLE2,
        ROIShape.POLYGON,
    ):
        type_store = store.store_for(shape)
        enabled_configs = [cfg for cfg in raw_configs if cfg.geometry.shape == shape and cfg.enabled]
        assert len(enabled_configs) == type_store.enabled_count()
        for i, cfg in enumerate(enabled_configs):
            mask, r0, c0 = masks.mask(shape, i)
            assert mask is not None
            assert mask.sum() > 0
            region = _geometry_to_region(shape, cfg.geometry)
            halcon_count = ha.area_center(region)[0][0]
            tolerance = 0.03 if shape is ROIShape.ELLIPSE else 0.02
            assert abs(mask.sum() - halcon_count) / halcon_count <= tolerance, (
                f"{shape} #{i}: mask {mask.sum()} vs HALCON {halcon_count}"
            )
    r1_mask, _, _ = masks.mask(ROIShape.RECTANGLE1, 0)
    assert r1_mask is None


def test_mask_disabled_index_returns_none() -> None:
    """Disabled (or out-of-range) mask indices return None."""
    configs = [
        make_config("c0", CircleROI(100, 120, 30), enabled=True),
        make_config("c1", CircleROI(400, 520, 45), enabled=False),
    ]
    store = build_store("cam_1", "pos_1", configs)
    masks = MaskCache()
    masks.rebuild(store, (480, 640))
    mask, _, _ = masks.mask(ROIShape.CIRCLE, 0)
    assert mask is not None
    mask1, r0, c0 = masks.mask(ROIShape.CIRCLE, 1)
    assert mask1 is None
    assert r0 == 0
    assert c0 == 0


def test_memory_bytes_grows_after_rebuild() -> None:
    """Memory accounting reflects generated mask/region storage."""
    configs = [
        make_config("c0", CircleROI(100, 120, 30), enabled=True),
        make_config("e0", EllipseROI(150, 200, 0.4, 40, 15), enabled=True),
        make_config(
            "p0",
            PolygonROI(((80, 500), (140, 490), (160, 540), (120, 580), (70, 560))),
            enabled=True,
        ),
    ]
    store = build_store("cam_1", "pos_1", configs)
    masks = MaskCache()
    regions = RegionCache()
    assert masks.memory_bytes() == 0
    assert regions.memory_bytes() == 0
    masks.rebuild(store, (480, 640))
    regions.rebuild(store)
    assert masks.memory_bytes() > 0
    assert regions.memory_bytes() > 0


def _geometry_to_region(shape: ROIShape, geom) -> ha.HObject:
    """Generate the real HALCON region for a geometry value."""
    if shape is ROIShape.CIRCLE:
        return ha.gen_circle(geom.row, geom.col, geom.radius)
    if shape is ROIShape.ELLIPSE:
        return ha.gen_ellipse(geom.row, geom.col, geom.phi, geom.radius1, geom.radius2)
    if shape is ROIShape.RECTANGLE2:
        return ha.gen_rectangle2(geom.row, geom.col, geom.phi, geom.length1, geom.length2)
    if shape is ROIShape.POLYGON:
        return ha.gen_region_polygon_filled(
            [float(v) for v in geom.rows], [float(v) for v in geom.cols]
        )
    if shape is ROIShape.RECTANGLE1:
        return ha.gen_rectangle1(geom.row1, geom.col1, geom.row2, geom.col2)
    raise ValueError(f"Unsupported ROI shape: {shape}")
