import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw, ImageChops, ImageFilter, ImageStat


SCRIPT = Path(__file__).parents[1] / "scripts" / "puzzle_compositor.py"
SPEC = importlib.util.spec_from_file_location("puzzle_compositor", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PuzzleCompositorTests(unittest.TestCase):
    def test_standard_cut_is_the_cli_default_and_a_unique_partition(self):
        parser = MODULE.build_parser()
        args = parser.parse_args(['input.png', 'output.png', '--manifest', 'output.json'])
        self.assertEqual(args.cut_style, 'standard')
        self.assertEqual(args.missing_count, 3)
        self.assertEqual(args.seam_width, 2)
        self.assertEqual(args.piece_content_policy, 'recognizable')
        self.assertFalse(args.preserve_existing_seams)
        preserved = parser.parse_args([
            'input.png', 'output.png', '--manifest', 'output.json',
            '--preserve-existing-seams',
        ])
        self.assertTrue(preserved.preserve_existing_seams)
        self.assertEqual(
            __import__('inspect').signature(MODULE.masks_and_signatures).parameters['cut_style'].default,
            'standard',
        )
        help_text = parser.format_help()
        self.assertIn('default: standard', help_text)
        self.assertIn('default: 3', help_text)

        masks, signatures, _, _ = MODULE.masks_and_signatures(
            (193, 129), 4, 6, 17, .18, cut_style='standard'
        )
        counts = [0] * (193 * 129)
        for mask in masks.values():
            for i, value in enumerate(mask.tobytes()):
                counts[i] += value // 255
        self.assertEqual(set(counts), {1})
        for row in range(4):
            for col in range(5):
                self.assertEqual(
                    signatures[(row, col)]['east'],
                    -signatures[(row, col + 1)]['west'],
                )

    def test_standard_and_organic_are_distinct_cut_languages(self):
        args = ((320, 240), 6, 8, 3, .18)
        standard, _, _, _ = MODULE.masks_and_signatures(*args, cut_style='standard')
        organic, _, _, _ = MODULE.masks_and_signatures(*args, cut_style='organic')
        self.assertNotEqual(standard[(2, 3)].tobytes(), organic[(2, 3)].tobytes())

    def test_standard_cut_is_seeded_complete_and_not_ruled_by_grid_axes(self):
        size, rows, cols = (401, 281), 7, 10
        first, _, xs, ys = MODULE.masks_and_signatures(
            size, rows, cols, 17, .20, cut_style='standard'
        )
        repeated, _, _, _ = MODULE.masks_and_signatures(
            size, rows, cols, 17, .20, cut_style='standard'
        )
        changed, _, _, _ = MODULE.masks_and_signatures(
            size, rows, cols, 18, .20, cut_style='standard'
        )
        self.assertEqual(
            [mask.tobytes() for mask in first.values()],
            [mask.tobytes() for mask in repeated.values()],
        )
        self.assertNotEqual(
            [mask.tobytes() for mask in first.values()],
            [mask.tobytes() for mask in changed.values()],
        )

        width, height = size
        owners = [0] * (width * height)
        counts = [0] * (width * height)
        for owner, mask in enumerate(first.values(), 1):
            for index, value in enumerate(mask.tobytes()):
                if value:
                    owners[index] = owner
                    counts[index] += 1
        self.assertEqual(set(counts), {1})

        vertical_cuts = [
            x for y in range(height) for x in range(1, width)
            if owners[y * width + x - 1] != owners[y * width + x]
        ]
        horizontal_cuts = [
            y for y in range(1, height) for x in range(width)
            if owners[(y - 1) * width + x] != owners[y * width + x]
        ]
        on_ruler_axis = (
            sum(x in xs[1:-1] for x in vertical_cuts)
            + sum(y in ys[1:-1] for y in horizontal_cuts)
        )
        axis_share = on_ruler_axis / (len(vertical_cuts) + len(horizontal_cuts))
        self.assertLess(axis_share, .35)

    def test_manifest_revision_names_the_actual_cut_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(Path(tmp), cut_style='organic')
            result = MODULE.compose(**args)
            self.assertEqual(result['compositor_revision'], '0.6-organic')
            self.assertTrue(MODULE.audit_manifest(args['manifest_path'])['passed'])

    def test_standard_manifest_records_shared_path_geometry_v5(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(Path(tmp), cut_style='standard')
            result = MODULE.compose(**args)
            self.assertEqual(result['compositor_revision'], '1.5-standard-bounded')
            self.assertEqual(result['grid']['geometry_version'], 5)
            self.assertEqual(result['shape_policy'], 'mixed')
            self.assertTrue(result['checks']['all_selected_shapes_recognizable'])
            self.assertTrue(all('content_profile' in pair for pair in result['pairs']))
            self.assertTrue(MODULE.audit_manifest(args['manifest_path'])['passed'])

    def test_standard_v5_has_a_broader_natural_throat_than_v4(self):
        args = ((480, 320), 6, 9, 31, .20)
        old, signs, xs, _ = MODULE.masks_and_signatures(
            *args, cut_style='standard', geometry_version=4
        )
        new, new_signs, new_xs, _ = MODULE.masks_and_signatures(
            *args, cut_style='standard', geometry_version=5
        )
        self.assertEqual(signs, new_signs)
        cell = next(
            (r, c) for (r, c), edges in signs.items()
            if c < 8 and edges['east'] == MODULE.TAB
        )
        r, c = cell
        x_old = xs[c + 1]
        x_new = new_xs[c + 1]
        old_throat = sum(1 for y in range(320) if old[cell].getpixel((x_old, y)))
        new_throat = sum(1 for y in range(320) if new[cell].getpixel((x_new, y)))
        self.assertGreater(new_throat, old_throat * 1.25)

    def test_organic_cut_is_a_complete_unique_connected_partition(self):
        # Catches independently perturbed edges, uncovered pixels and detached tabs.
        self.assertIn('cut_style', __import__('inspect').signature(MODULE.masks_and_signatures).parameters)
        for seed in (1, 17, 42):
            masks, signs, _, _ = MODULE.masks_and_signatures((193,129), 4,6,seed,.18,cut_style='organic')
            counts = [0] * (193*129)
            for (r,c), mask in masks.items():
                for i, value in enumerate(mask.tobytes()):
                    counts[i] += value // 255
                crop = mask.crop(mask.getbbox())
                pixels = crop.load()
                start = next((x,y) for y in range(crop.height) for x in range(crop.width) if pixels[x,y])
                seen, todo = {start}, [start]
                while todo:
                    x,y = todo.pop()
                    for nx,ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                        if 0 <= nx < crop.width and 0 <= ny < crop.height and pixels[nx,ny] and (nx,ny) not in seen:
                            seen.add((nx,ny)); todo.append((nx,ny))
                self.assertEqual(len(seen), crop.histogram()[255])
                if c < 5:
                    self.assertEqual(signs[(r,c)]['east'], -signs[(r,c+1)]['west'])
            self.assertEqual(set(counts), {1})

    def test_organic_cuts_vary_without_changing_with_repeated_seed(self):
        self.assertIn('cut_style', __import__('inspect').signature(MODULE.masks_and_signatures).parameters)
        args = ((320,240),6,8,3,.18)
        organic, _, _, _ = MODULE.masks_and_signatures(*args,cut_style='organic')
        repeat, _, _, _ = MODULE.masks_and_signatures(*args,cut_style='organic')
        classic, _, _, _ = MODULE.masks_and_signatures(*args)
        self.assertEqual(organic[(2,3)].tobytes(), repeat[(2,3)].tobytes())
        self.assertNotEqual(organic[(2,3)].tobytes(), classic[(2,3)].tobytes())
        self.assertGreater(len({m.crop(m.getbbox()).size for m in organic.values()}), 10)

    def test_geometry_revision_preserves_the_previous_cut(self):
        self.assertIn('geometry_version', __import__('inspect').signature(MODULE.masks_and_signatures).parameters)
        args=((320,240),6,8,3,.18)
        old,_,_,_=MODULE.masks_and_signatures(*args,cut_style='organic',geometry_version=1)
        new,_,_,_=MODULE.masks_and_signatures(*args,cut_style='organic',geometry_version=2)
        self.assertNotEqual(old[(2,3)].tobytes(),new[(2,3)].tobytes())

    def test_cli_exposes_an_explicit_material_preset(self):
        parser = MODULE.build_parser()
        args = parser.parse_args(['input.png', 'output.png', '--manifest', 'output.json'])
        self.assertEqual(args.material_preset, 'graphite-matte')
        self.assertIn('deep-charcoal', parser.format_help())
        self.assertIn('ivory-board', parser.format_help())

    def test_full_surface_seams_are_readable_without_becoming_bright_ink(self):
        masks,_,_,_=MODULE.masks_and_signatures((193,129),4,6,17,.18)
        black=Image.new('RGB',(193,129),(8,8,8))
        result=MODULE.add_puzzle_seams(
            black,masks.values(),1,material_preset='deep-charcoal'
        )
        seam = Image.new('L', black.size, 0)
        for mask in masks.values():
            seam = ImageChops.lighter(seam, MODULE.mask_boundary(mask, 1))
        seam_mean = ImageStat.Stat(result.convert('L'), seam).mean[0]
        # Deep charcoal relief must remain source-relative. It should survive
        # fit view as a shallow cut, never as a pale graphite grid.
        self.assertGreater(seam_mean, 12)
        self.assertLess(seam_mean, 21)
        self.assertLessEqual(result.convert('L').getextrema()[1], 27)
        lower_right = ImageChops.subtract(seam, MODULE.shift_mask(seam, -1, -1))
        upper_left = ImageChops.subtract(seam, MODULE.shift_mask(seam, 1, 1))
        lower_only = ImageChops.subtract(lower_right, upper_left)
        return_mean = ImageStat.Stat(result.convert('L'), lower_only).mean[0]
        # With per-piece shoulder ownership, this sample mixes the graphite
        # return with the neighbouring piece's cut face.  It must stay visibly
        # separated from the black stock while remaining far below white ink.
        self.assertGreater(return_mean, 8)
        self.assertLess(return_mean, 22)

        light=Image.new('RGB',(193,129),(225,225,225))
        rendered=MODULE.add_puzzle_seams(
            light,masks.values(),1,material_preset='ivory-board'
        )
        rendered_luma = rendered.convert('L')
        self.assertLess(rendered_luma.getextrema()[0], 211)
        # A physical ivory-board lip may briefly catch more light than the
        # untouched L225 paper.  Keep that specular thread narrow and
        # source-relative instead of clipping it back into a flat gray rule.
        self.assertLessEqual(rendered_luma.getextrema()[1], 242)
        pixels = list(rendered_luma.tobytes())
        self.assertLess(sum(value > 238 for value in pixels) / len(pixels), .005)

    def test_production_label_path_preserves_relief_without_enumerating_every_mask(self):
        masks, _, _, _ = MODULE.masks_and_signatures(
            (193, 129), 4, 6, 17, .18, cut_style='standard'
        )
        self.assertIsInstance(masks, MODULE.LabelMaskMap)
        self.assertEqual(len(masks._cache), 0)

        class NeverEnumerate:
            def __iter__(self):
                raise AssertionError('fast label rendering must not enumerate all masks')

        base = Image.new('RGB', (193, 129), (120, 120, 120))
        fast = MODULE.add_puzzle_seams(
            base, NeverEnumerate(), 2,
            material_preset='graphite-matte', relief_seed=17,
            owner_labels=masks.labels,
        ).convert('RGB')
        self.assertEqual(len(masks._cache), 0)

        slow = MODULE.add_puzzle_seams(
            base, masks.values(), 2,
            material_preset='graphite-matte', relief_seed=17,
        ).convert('RGB')
        difference = ImageChops.difference(slow, fast)
        self.assertLess(max(ImageStat.Stat(difference).mean), .25)

    def test_deep_charcoal_cut_is_continuously_legible_without_bright_ink(self):
        masks, _, _, _ = MODULE.masks_and_signatures(
            (193, 129), 4, 6, 17, .18, cut_style='standard'
        )
        base = Image.new('RGB', (193, 129), (8, 8, 8))
        rendered = MODULE.add_puzzle_seams(
            base, masks.values(), 1,
            material_preset='deep-charcoal', relief_seed=17,
        ).convert('L')
        seam = Image.new('L', base.size, 0)
        for mask in masks.values():
            seam = ImageChops.lighter(seam, MODULE.mask_boundary(mask, 1))
        cut_values = [
            value for value, alpha in zip(rendered.tobytes(), seam.tobytes()) if alpha
        ]
        legible_share = sum(value >= 11 for value in cut_values) / len(cut_values)
        bright_ink_share = sum(value > 27 for value in cut_values) / len(cut_values)
        self.assertLessEqual(bright_ink_share, .01)
        # The remaining values are the physically valid black cut channel;
        # do not misclassify that dark half of the relief as an invisible seam.
        self.assertGreaterEqual(legible_share, .60)
        self.assertGreaterEqual(sorted(cut_values)[len(cut_values) * 9 // 10], 19)

    def test_deep_charcoal_midtones_have_a_real_cut_channel(self):
        masks, _, _, _ = MODULE.masks_and_signatures(
            (193, 129), 4, 6, 17, .22, cut_style='standard'
        )
        base = Image.new('RGB', (193, 129), (180, 180, 180))
        rendered = MODULE.add_puzzle_seams(
            base, masks.values(), 1,
            material_preset='deep-charcoal', relief_seed=17,
        ).convert('L')
        seam = Image.new('L', base.size, 0)
        for mask in masks.values():
            seam = ImageChops.lighter(seam, MODULE.mask_boundary(mask, 1))
        cut_values = sorted(
            value for value, alpha in zip(rendered.tobytes(), seam.tobytes()) if alpha
        )
        # A midtone charcoal passage must reveal a recessed channel while
        # remaining a source-relative press cut, not a black vector rule.
        # Roughly 20--35 levels below the source retains the drawing texture.
        lower_quartile = cut_values[len(cut_values) // 4]
        self.assertGreaterEqual(lower_quartile, 145)
        self.assertLessEqual(lower_quartile, 160)

    def test_shared_cut_has_opposing_piece_shoulders_not_one_flat_stroke(self):
        left = Image.new('L', (100, 80), 0)
        right = Image.new('L', (100, 80), 0)
        ImageDraw.Draw(left).rectangle((0, 0, 49, 79), fill=255)
        ImageDraw.Draw(right).rectangle((50, 0, 99, 79), fill=255)
        base = Image.new('RGB', (100, 80), (120, 120, 120))
        rendered = MODULE.add_puzzle_seams(
            base, [left, right], 1,
            material_preset='graphite-matte', relief_seed=3,
        ).convert('L')
        dark_owner_edge = rendered.getpixel((49, 40))
        light_owner_edge = rendered.getpixel((50, 40))
        self.assertGreaterEqual(light_owner_edge, dark_owner_edge + 24)
        self.assertGreaterEqual(light_owner_edge, 134)

    def test_deep_charcoal_shoulder_lifts_local_tone_around_a_narrow_cut(self):
        left = Image.new('L', (100, 80), 0)
        right = Image.new('L', (100, 80), 0)
        ImageDraw.Draw(left).rectangle((0, 0, 49, 79), fill=255)
        ImageDraw.Draw(right).rectangle((50, 0, 99, 79), fill=255)
        base = Image.new('RGB', (100, 80), (200, 200, 200))
        rendered = MODULE.add_puzzle_seams(
            base, [left, right], 1,
            material_preset='deep-charcoal',
            relief_seed=3,
        ).convert('L')
        # A graphite shoulder is a local lift, not fixed gray ink: on a light
        # charcoal passage it must remain brighter than the source. The strong
        # channel belongs only to the adjacent central cut pixel.
        self.assertGreaterEqual(rendered.getpixel((51, 40)), 208)
        self.assertGreater(rendered.getpixel((48, 40)), rendered.getpixel((49, 40)) + 18)

    def test_opposing_shoulders_survive_fit_view_as_two_pixel_bands(self):
        left = Image.new('L', (100, 80), 0)
        right = Image.new('L', (100, 80), 0)
        ImageDraw.Draw(left).rectangle((0, 0, 49, 79), fill=255)
        ImageDraw.Draw(right).rectangle((50, 0, 99, 79), fill=255)
        base = Image.new('RGB', (100, 80), (120, 120, 120))
        rendered = MODULE.add_puzzle_seams(
            base, [left, right], 1,
            material_preset='graphite-matte', relief_seed=3,
        ).convert('L')
        # A one-pixel treatment collapses into a drawn rule when the complete
        # board is fitted on screen.  Both neighbouring piece shoulders need a
        # restrained two-pixel footprint while staying inside the cut band.
        self.assertLessEqual(rendered.getpixel((48, 40)), 117)
        self.assertGreaterEqual(rendered.getpixel((51, 40)), 127)
        self.assertGreaterEqual(
            rendered.getpixel((51, 40)), rendered.getpixel((48, 40)) + 6
        )

    def test_ivory_seam_reads_as_a_pressed_ramp_not_one_dark_line(self):
        left = Image.new('L', (100, 80), 0)
        right = Image.new('L', (100, 80), 0)
        ImageDraw.Draw(left).rectangle((0, 0, 49, 79), fill=255)
        ImageDraw.Draw(right).rectangle((50, 0, 99, 79), fill=255)
        base = Image.new('RGB', (100, 80), (225, 225, 225))
        rendered = MODULE.add_puzzle_seams(
            base, [left, right], 1,
            material_preset='ivory-board', relief_seed=3,
        ).convert('L')
        shadow_shoulder = rendered.getpixel((48, 40))
        pressed_channel = rendered.getpixel((49, 40))
        lit_lip = rendered.getpixel((50, 40))
        outer_return = rendered.getpixel((51, 40))
        self.assertLessEqual(shadow_shoulder, 219)
        self.assertGreaterEqual(pressed_channel, 195)
        self.assertLessEqual(pressed_channel, 207)
        self.assertGreaterEqual(lit_lip, 232)
        self.assertLessEqual(lit_lip, 238)
        self.assertGreaterEqual(outer_return, 230)
        self.assertLessEqual(outer_return, lit_lip)

    def test_dark_relief_is_source_relative_not_gray_ink(self):
        left = Image.new('L', (100, 80), 0)
        right = Image.new('L', (100, 80), 0)
        ImageDraw.Draw(left).rectangle((0, 0, 49, 79), fill=255)
        ImageDraw.Draw(right).rectangle((50, 0, 99, 79), fill=255)
        base = Image.new('RGB', (100, 80), (8, 8, 8))
        rendered = MODULE.add_puzzle_seams(
            base, [left, right], 1,
            material_preset='deep-charcoal', relief_seed=3,
        ).convert('L')
        cross_section = [rendered.getpixel((x, 40)) for x in range(45, 56)]
        self.assertEqual(cross_section[0], 8)
        self.assertEqual(cross_section[-1], 8)
        self.assertGreaterEqual(max(cross_section), 19)
        self.assertLessEqual(max(cross_section), 27)
        self.assertLessEqual(rendered.getpixel((49, 40)), 8)

    def test_dark_charcoal_shoulder_tapers_instead_of_drawing_a_wide_outline(self):
        left = Image.new('L', (100, 80), 0)
        right = Image.new('L', (100, 80), 0)
        ImageDraw.Draw(left).rectangle((0, 0, 49, 79), fill=255)
        ImageDraw.Draw(right).rectangle((50, 0, 99, 79), fill=255)
        rendered = MODULE.add_puzzle_seams(
            Image.new('RGB', (100, 80), (8, 8, 8)), [left, right], 1,
            material_preset='deep-charcoal', relief_seed=3,
        ).convert('L')
        lit_cut_lip = rendered.getpixel((50, 40))
        outer_shoulder = rendered.getpixel((51, 40))
        far_return = rendered.getpixel((52, 40))
        self.assertGreaterEqual(outer_shoulder, 12)
        self.assertLessEqual(outer_shoulder, 17)
        self.assertGreaterEqual(lit_cut_lip, outer_shoulder + 5)
        self.assertLessEqual(lit_cut_lip, 27)
        # A third, quieter band is the material roll-off visible in the
        # physical reference. It must decay monotonically back to the artwork.
        self.assertGreater(far_return, 8)
        self.assertLess(far_return, outer_shoulder)

    def test_seam_relief_changes_only_a_narrow_cut_band(self):
        masks,_,_,_=MODULE.masks_and_signatures((193,129),4,6,17,.18)
        base = Image.new('RGB', (193,129), (121,117,110))
        rendered = MODULE.add_puzzle_seams(
            base, masks.values(), 1, material_preset='graphite-matte'
        ).convert('RGB')
        seam = Image.new('L', base.size, 0)
        for mask in masks.values():
            seam = ImageChops.lighter(seam, MODULE.mask_boundary(mask, 1))
        influence = seam.filter(ImageFilter.MaxFilter(9))
        outside = ImageChops.invert(influence)
        diff = ImageChops.difference(base, rendered)
        self.assertIsNone(Image.composite(diff, Image.new('RGB', base.size), outside).getbbox())

    def test_seam_relief_modulation_is_seeded_and_low_frequency(self):
        first = MODULE.low_frequency_seam_modulation((193,129), 23)
        repeated = MODULE.low_frequency_seam_modulation((193,129), 23)
        changed = MODULE.low_frequency_seam_modulation((193,129), 24)
        self.assertEqual(first.tobytes(), repeated.tobytes())
        self.assertNotEqual(first.tobytes(), changed.tobytes())
        self.assertGreaterEqual(first.getextrema()[0], 190)
        self.assertLessEqual(first.getextrema()[1], 255)
        high_frequency = ImageChops.difference(
            first, first.filter(ImageFilter.GaussianBlur(2))
        )
        self.assertLess(ImageStat.Stat(high_frequency).mean[0], 1.5)

    def test_protected_seams_are_softened_but_not_erased(self):
        masks,_,_,_=MODULE.masks_and_signatures((193,129),4,6,17,.18)
        base = Image.new('RGB', (193,129), (128,128,128))
        normal = MODULE.add_puzzle_seams(
            base, masks.values(), 1, material_preset='graphite-matte'
        ).convert('RGB')
        protected = MODULE.add_puzzle_seams(
            base, masks.values(), 1, protected=[(0,0,193,129)],
            material_preset='graphite-matte'
        ).convert('RGB')
        seam = Image.new('L', base.size, 0)
        for mask in masks.values():
            seam = ImageChops.lighter(seam, MODULE.mask_boundary(mask, 1))
        normal_delta = ImageStat.Stat(ImageChops.difference(base, normal).convert('L'), seam).mean[0]
        protected_delta = ImageStat.Stat(ImageChops.difference(base, protected).convert('L'), seam).mean[0]
        ratio = protected_delta / normal_delta
        self.assertGreaterEqual(ratio, .75)
        self.assertLessEqual(ratio, .90)

    def test_hole_substrate_has_quiet_fibre_and_a_darker_cut_wall(self):
        size = (120, 90)
        surface = Image.new('RGBA', size, (190,186,178,255))
        hole = Image.new('L', size, 0)
        ImageDraw.Draw(hole).ellipse((25,15,95,80), fill=255)
        rendered = MODULE.render_holes(
            surface, hole, (174,166,154), seed=11, material_preset='graphite-matte'
        ).convert('RGB')
        outside = ImageChops.invert(hole)
        self.assertIsNone(Image.composite(
            ImageChops.difference(surface.convert('RGB'), rendered),
            Image.new('RGB', size), outside
        ).getbbox())
        core = hole.filter(ImageFilter.MinFilter(15))
        wall = ImageChops.subtract(hole, hole.filter(ImageFilter.MinFilter(7)))
        core_stats = ImageStat.Stat(rendered.convert('L'), core)
        wall_stats = ImageStat.Stat(rendered.convert('L'), wall)
        self.assertGreater(core_stats.stddev[0], .8)
        self.assertLess(core_stats.stddev[0], 6.5)
        self.assertLess(wall_stats.mean[0], core_stats.mean[0] - 6)

    def test_sparse_hole_relief_allocates_only_a_bounded_patch(self):
        size = (1000, 400)
        surface = Image.new('RGBA', size, (236, 229, 221, 255))
        hole = Image.new('L', size, 0)
        ImageDraw.Draw(hole).rectangle((820, 90, 900, 170), fill=255)
        original = MODULE.make_substrate
        with mock.patch.object(MODULE, 'make_substrate', wraps=original) as substrate:
            rendered = MODULE.render_holes(
                surface, hole, (208, 188, 174), seed=9,
                material_preset='ivory-board',
            )
        allocated = substrate.call_args.args[0]
        self.assertLess(allocated[0] * allocated[1], size[0] * size[1] // 10)
        self.assertEqual(rendered.getpixel((100, 100)), surface.getpixel((100, 100)))

    def test_deep_hole_has_a_layered_four_to_six_pixel_cut_wall(self):
        size = (120, 90)
        surface = Image.new('RGBA', size, (205, 202, 195, 255))
        hole = Image.new('L', size, 0)
        ImageDraw.Draw(hole).rectangle((20, 15, 100, 75), fill=255)
        rendered = MODULE.render_holes(
            surface, hole, (190, 120, 55), seed=9,
            material_preset='deep-charcoal',
        ).convert('L')
        # Follow the left cut face toward the cavity core. The paperboard is
        # five pixels deep and its short inner cast shadow may extend the
        # visible recessed band by another few pixels.
        wall = []
        for x in range(20, 31):
            if rendered.getpixel((x, 45)) < 115:
                wall.append(x)
            else:
                break
        self.assertGreaterEqual(len(wall), 4)
        self.assertLessEqual(len(wall), 9)

    def test_hole_relief_has_inset_polarity_not_a_raised_tile_halo(self):
        size = (120, 90)
        surface = Image.new('RGBA', size, (205, 202, 195, 255))
        hole = Image.new('L', size, 0)
        ImageDraw.Draw(hole).rectangle((20, 15, 100, 75), fill=255)
        rendered = MODULE.render_holes(
            surface, hole, (190, 120, 55), seed=9,
            material_preset='deep-charcoal',
        ).convert('L')
        upper_left_wall = [
            rendered.getpixel((x, 45)) for x in range(20, 25)
        ] + [
            rendered.getpixel((60, y)) for y in range(15, 20)
        ]
        lower_right_wall = [
            rendered.getpixel((x, 45)) for x in range(96, 101)
        ] + [
            rendered.getpixel((60, y)) for y in range(71, 76)
        ]
        # Inset paperboard reverses the polarity of a raised loose piece:
        # upper/left walls fall into shade and lower/right walls catch light.
        self.assertGreater(
            sum(lower_right_wall) / len(lower_right_wall),
            sum(upper_left_wall) / len(upper_left_wall) + 12,
        )

    def test_hole_cut_wall_remains_readable_on_dark_and_light_backings(self):
        size = (120, 90)
        hole = Image.new('L', size, 0)
        ImageDraw.Draw(hole).rectangle((20, 15, 100, 75), fill=255)
        for surface_rgb, hole_rgb in (
            ((18, 18, 18, 255), (66, 63, 58)),
            ((205, 202, 195, 255), (204, 200, 192)),
        ):
            rendered = MODULE.render_holes(
                Image.new('RGBA', size, surface_rgb), hole, hole_rgb, seed=9,
                material_preset='deep-charcoal',
            ).convert('L')
            core = rendered.getpixel((60, 45))
            left_wall = [rendered.getpixel((x, 45)) for x in range(20, 27)]
            right_wall = [rendered.getpixel((x, 45)) for x in range(94, 101)]
            # The upper/left wall exposes the full 5–6 px board thickness;
            # opposite it, the floor approaches a narrow reflected lip. This
            # asymmetric parallax is what distinguishes a cavity from a tile.
            self.assertGreaterEqual(max(left_wall) - min(left_wall), 24)
            self.assertGreaterEqual(abs(core - min(left_wall)), 24)
            self.assertLessEqual(max(abs(value - core) for value in right_wall[:-1]), 6)
            self.assertGreaterEqual(abs(right_wall[-1] - core), 2)

    def test_hole_wall_falls_off_smoothly_toward_the_quiet_substrate(self):
        size = (120, 90)
        surface = Image.new('RGBA', size, (20, 20, 20, 255))
        hole = Image.new('L', size, 0)
        ImageDraw.Draw(hole).rectangle((20, 15, 100, 75), fill=255)
        rendered = MODULE.render_holes(
            surface, hole, (66, 63, 58), seed=9,
            material_preset='deep-charcoal',
        ).convert('L')
        left_ramp = [rendered.getpixel((x, 45)) for x in range(20, 27)]
        # Ignore the one-pixel contact occlusion; the remaining wall should
        # open progressively into the backing board rather than stay flat.
        self.assertTrue(all(a <= b for a, b in zip(left_ramp[2:], left_ramp[3:])))
        self.assertGreaterEqual(left_ramp[-1] - left_ramp[2], 16)

    def test_hole_floor_has_a_directional_inset_shadow_not_a_flat_fill(self):
        size = (120, 90)
        surface = Image.new('RGBA', size, (26, 25, 24, 255))
        hole = Image.new('L', size, 0)
        ImageDraw.Draw(hole).rectangle((20, 15, 100, 75), fill=255)
        rendered = MODULE.render_holes(
            surface, hole, (88, 84, 78), seed=9,
            material_preset='graphite-matte',
        ).convert('L')
        # Once past the paperboard wall, the backing still carries a short
        # upper/left cast shadow.  A uniform centre fill reads as a gray tile.
        floor_top = sum(rendered.getpixel((x, 22)) for x in range(42, 79)) / 37
        floor_left = sum(rendered.getpixel((27, y)) for y in range(34, 58)) / 24
        floor_core = sum(rendered.getpixel((x, 45)) for x in range(48, 73)) / 25
        self.assertLess(floor_top, floor_core - 3)
        self.assertLess(floor_left, floor_core - 3)

    def test_material_presets_preserve_pair_geometry_and_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = MODULE.compose(**self.make_case(
                root/'dark', material_preset='deep-charcoal'
            ))
            second = MODULE.compose(**self.make_case(
                root/'light', material_preset='ivory-board'
            ))
            self.assertEqual(first['material_preset'], 'deep-charcoal')
            self.assertEqual(second['material_preset'], 'ivory-board')
            fields = ('cell','source_bbox','edges','mask_sha256','content_sha256')
            self.assertEqual(
                [{key: pair[key] for key in fields} for pair in first['pairs']],
                [{key: pair[key] for key in fields} for pair in second['pairs']],
            )

    def test_ivory_board_piece_is_seated_instead_of_floating(self):
        ivory = MODULE.MATERIAL_PRESETS['ivory-board']
        deep = MODULE.MATERIAL_PRESETS['deep-charcoal']
        self.assertLessEqual(max(ivory.piece_depth), 4)
        self.assertLess(ivory.piece_far_shadow, ivory.piece_near_shadow / 3)
        self.assertLess(ivory.piece_near_shadow, deep.piece_near_shadow)

    def test_ivory_hole_uses_warm_directional_depth_not_a_dark_outline(self):
        size = (120, 90)
        hole = Image.new('L', size, 0)
        ImageDraw.Draw(hole).rectangle((20, 15, 100, 75), fill=255)
        rendered = MODULE.render_holes(
            Image.new('RGBA', size, (236, 229, 221, 255)),
            hole, (208, 188, 174), seed=9, material_preset='ivory-board',
        ).convert('RGB')
        core = rendered.getpixel((60, 45))
        left_wall = [rendered.getpixel((x, 45)) for x in range(20, 27)]
        right_wall = [rendered.getpixel((x, 45)) for x in range(94, 101)]
        core_luma = sum(core) / 3
        self.assertGreater(core[0], core[1])
        self.assertGreater(core[1], core[2])
        self.assertLess(min(sum(pixel) / 3 for pixel in left_wall), core_luma - 16)
        self.assertGreater(
            sum(sum(pixel) / 3 for pixel in right_wall) / len(right_wall),
            sum(sum(pixel) / 3 for pixel in left_wall) / len(left_wall) + 8,
        )
        self.assertGreater(min(min(pixel) for pixel in left_wall), 95)

    def test_ivory_piece_has_no_fixed_dark_halo_on_the_lit_edge(self):
        canvas = Image.new('RGBA', (100, 90), (236, 229, 221, 255))
        piece = Image.new('RGBA', (50, 50), (0, 0, 0, 0))
        ImageDraw.Draw(piece).rectangle((8, 8, 39, 35), fill=(224, 216, 206, 255))
        rendered = MODULE.place_lifted_piece(
            canvas, piece, 20, 15, (208, 188, 174),
            material_preset='ivory-board',
        )
        # The upper-left exterior remains clean paper; depth is carried by the
        # translated warm core and its lower-right contact shadow.
        self.assertEqual(rendered.getpixel((27, 22)), canvas.getpixel((27, 22)))
        sidewall = rendered.getpixel((48, 52))[:3]
        self.assertGreater(min(sidewall), 145)
        self.assertLess(sum(sidewall) / 3, 220)

    def test_rotated_piece_alpha_has_a_compact_clean_die_cut_edge(self):
        piece = Image.new('RGBA', (6, 1), (40, 38, 35, 0))
        piece.putalpha(Image.new('L', (6, 1)))
        piece.putalpha(Image.frombytes('L', (6, 1), bytes((12, 36, 80, 170, 219, 250))))
        cleaned = MODULE.tighten_die_cut_alpha(piece).getchannel('A')
        values = list(cleaned.getdata())
        self.assertEqual(values[:2], [0, 0])
        self.assertEqual(values[-2:], [255, 255])
        self.assertGreater(values[3], values[2])
        self.assertLess(values[3], 255)

    def test_lifted_piece_keeps_its_interior_exact_and_has_directional_depth(self):
        canvas = Image.new('RGBA', (100,80), (182,178,170,255))
        piece = Image.new('RGBA', (40,40), (0,0,0,0))
        ImageDraw.Draw(piece).rectangle((8,8,31,31), fill=(64,58,52,255))
        rendered = MODULE.place_lifted_piece(
            canvas, piece, 20, 15, (150,142,132), material_preset='graphite-matte'
        )
        # The central printed face stays exact. Only the narrow die-cut rim is
        # allowed to receive the physical bevel.
        for y in range(11,29):
            for x in range(11,29):
                self.assertEqual(rendered.getpixel((20+x,15+y))[:3], piece.getpixel((x,y))[:3])
        upper_left = sum(rendered.getpixel((26,21))[:3])
        lower_right = sum(rendered.getpixel((53,48))[:3])
        self.assertLess(lower_right, upper_left)

        deep = MODULE.place_lifted_piece(
            canvas, piece, 20, 15, (150,142,132), material_preset='deep-charcoal'
        )
        # A three-pixel lower cut wall must remain visibly denser than the soft
        # ambient shadow, otherwise a dark source piece reads like a flat decal.
        self.assertLess(sum(deep.getpixel((40,49))[:3]) / 3, 130)

    def test_deep_charcoal_piece_has_a_continuous_four_to_six_pixel_sidewall(self):
        canvas = Image.new('RGBA', (100, 90), (230, 230, 230, 255))
        piece = Image.new('RGBA', (50, 50), (0, 0, 0, 0))
        ImageDraw.Draw(piece).rectangle((8, 8, 39, 35), fill=(64, 58, 52, 255))
        rendered = MODULE.place_lifted_piece(
            canvas, piece, 20, 15, (190, 120, 55),
            material_preset='deep-charcoal',
        )

        for y in range(11, 33):
            for x in range(11, 37):
                self.assertEqual(
                    rendered.getpixel((20 + x, 15 + y))[:3],
                    piece.getpixel((x, y))[:3],
                )

        face_bottom = 15 + 35
        sample_x = 20 + 28
        wall_rows = []
        for y in range(face_bottom + 1, face_bottom + 8):
            red, green, blue = rendered.getpixel((sample_x, y))[:3]
            if red - green >= 20 and green - blue >= 20:
                wall_rows.append(y)
        self.assertEqual(
            wall_rows,
            list(range(face_bottom + 1, face_bottom + 1 + len(wall_rows))),
        )
        self.assertGreaterEqual(len(wall_rows), 4)
        self.assertLessEqual(len(wall_rows), 6)

    def test_lifted_piece_sidewall_has_layered_depth_not_one_flat_strip(self):
        canvas = Image.new('RGBA', (100, 90), (230, 230, 230, 255))
        piece = Image.new('RGBA', (50, 50), (0, 0, 0, 0))
        ImageDraw.Draw(piece).rectangle((8, 8, 39, 35), fill=(64, 58, 52, 255))
        rendered = MODULE.place_lifted_piece(
            canvas, piece, 20, 15, (190, 120, 55),
            material_preset='deep-charcoal',
        ).convert('L')
        face_bottom = 15 + 35
        sample_x = 20 + 28
        near_wall = rendered.getpixel((sample_x, face_bottom + 1))
        far_wall = rendered.getpixel((sample_x, face_bottom + 5))
        # Upper-left illumination leaves the near lip brighter and lets the
        # exposed paper core fall off through several tonal layers.
        self.assertGreater(near_wall, far_wall + 8)

    def test_dark_loose_piece_exposes_a_readable_paperboard_edge(self):
        canvas = Image.new('RGBA', (100, 90), (8, 8, 8, 255))
        piece = Image.new('RGBA', (50, 50), (0, 0, 0, 0))
        ImageDraw.Draw(piece).rectangle((8, 8, 39, 35), fill=(18, 17, 16, 255))
        rendered = MODULE.place_lifted_piece(
            canvas, piece, 20, 15, (66, 63, 58),
            material_preset='deep-charcoal',
        ).convert('L')
        edge_value = rendered.getpixel((20 + 28, 15 + 39))
        self.assertGreaterEqual(edge_value, 55)
        self.assertLess(edge_value, 130)

    def test_designed_placements_preserve_order_scale_and_audit(self):
        self.assertIn('manual_placements', __import__('inspect').signature(MODULE.compose).parameters)
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(Path(tmp), cut_style='organic', missing_count=1,
                manual_cells=[(1,1)], manual_placements=[(.73,.74,-7)], max_rotation=12)
            result = MODULE.compose(**args)
            pair = result['pairs'][0]
            self.assertEqual(pair['rotation_degrees'], -7)
            self.assertLessEqual(abs(pair['destination_center'][0] - 234), 1)
            self.assertLessEqual(abs(pair['destination_center'][1] - 178), 1)
            self.assertEqual(result['grid']['cut_style'], 'organic')
            self.assertTrue(MODULE.audit_manifest(args['manifest_path'])['passed'])

    def test_existing_seams_can_be_preserved_while_pairs_stay_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(
                Path(tmp), preserve_existing_seams=True,
            )
            result = MODULE.compose(**args)
            self.assertTrue(result['preserve_existing_seams'])
            with Image.open(args['input_path']) as source, Image.open(result['assembled_output']) as assembled:
                self.assertIsNone(
                    ImageChops.difference(source.convert('RGBA'), assembled.convert('RGBA')).getbbox()
                )
            self.assertTrue(MODULE.audit_manifest(args['manifest_path'])['passed'])

    def test_invalid_designed_placements_never_write_outputs(self):
        self.assertIn('manual_placements', __import__('inspect').signature(MODULE.compose).parameters)
        cases = [[(.5,.5,0)], [(0,0,0),(.8,.8,0)], [(float('nan'),.5,0),(.8,.8,0)],
                 [(.5,.5,30),(.8,.8,0)], [(.75,.75,0),(.75,.75,0)]]
        for placements in cases:
            with self.subTest(placements=placements), tempfile.TemporaryDirectory() as tmp:
                args = self.make_case(Path(tmp), cut_style='organic', manual_cells=[(1,1),(1,4)],
                    manual_placements=placements, max_rotation=12)
                with self.assertRaises(ValueError):
                    MODULE.compose(**args)
                self.assertFalse(args['output_path'].exists())
                self.assertFalse(args['pieces_dir'].exists())

    def make_case(self, root, **changes):
        root.mkdir(parents=True, exist_ok=True)
        source = root / 'input.png'
        Image.new('RGB', (320, 240), '#8a8175').save(source)
        args = dict(input_path=source, output_path=root/'out.png', manifest_path=root/'out.json',
            rows=6, cols=8, missing_count=2, seed=3, protected_norm=[], manual_cells=[],
            knob_ratio=0.19, seam_width=1, max_rotation=0, hole_color=(128,120,112),
            pieces_dir=root/'pieces', content_policy='any')
        args.update(changes)
        return args

    def test_zero_rotation_is_not_forced_to_two_degrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = MODULE.compose(**self.make_case(Path(tmp)))
            self.assertTrue(all(p['rotation_degrees'] == 0 for p in result['pairs']))

    def test_default_mixed_shape_policy_rejects_monotone_manual_piece(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(
                Path(tmp), missing_count=1, manual_cells=[(2, 4)]
            )
            with self.assertRaisesRegex(ValueError, 'mixed tab/socket'):
                MODULE.compose(**args)

    def test_any_shape_policy_can_explicitly_allow_monotone_piece(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(
                Path(tmp), missing_count=1, manual_cells=[(2, 4)],
                shape_policy='any',
            )
            result = MODULE.compose(**args)
            self.assertFalse(
                result['pairs'][0]['shape_profile']['recognizable_mixed_shape']
            )
            self.assertTrue(MODULE.audit_manifest(args['manifest_path'])['passed'])

    def test_recognizable_content_policy_rejects_a_flat_manual_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, signatures, _, _ = MODULE.masks_and_signatures(
                (320, 240), 6, 8, 3, .19, cut_style='standard'
            )
            cell = next(
                key for key, edges in signatures.items()
                if MODULE.is_readable_standard_piece(edges)
            )
            args = self.make_case(
                Path(tmp), missing_count=1, manual_cells=[cell],
                content_policy='recognizable',
            )
            with self.assertRaisesRegex(ValueError, 'recognizable source detail'):
                MODULE.compose(**args)

    def test_content_profile_is_recorded_and_independently_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(Path(tmp))
            result = MODULE.compose(**args)
            self.assertIn('luma_stddev', result['pairs'][0]['content_profile'])
            result['pairs'][0]['content_profile']['luma_stddev'] = 999
            args['manifest_path'].write_text(json.dumps(result), encoding='utf-8')
            audit = MODULE.audit_manifest(args['manifest_path'])
            self.assertFalse(audit['passed'])
            self.assertTrue(any('content profile' in error for error in audit['errors']))

    def test_assembled_proof_is_saved_and_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(Path(tmp))
            result = MODULE.compose(**args)
            proof = Path(result['assembled_output'])
            self.assertTrue(proof.exists())
            self.assertTrue(MODULE.audit_manifest(args['manifest_path'])['passed'])
            with Image.open(proof) as opened:
                altered = opened.copy()
            altered.putpixel((2, 2), (255, 0, 255, 255))
            altered.save(proof)
            audit = MODULE.audit_manifest(args['manifest_path'])
            self.assertFalse(audit['passed'])
            self.assertTrue(any('assembled proof' in error for error in audit['errors']))

    def test_audit_detects_tampered_piece_pixels_not_only_claimed_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(Path(tmp))
            result = MODULE.compose(**args)
            self.assertTrue(MODULE.audit_manifest(args['manifest_path'])['passed'])
            asset = Path(result['pairs'][0]['piece_asset'])
            with Image.open(asset) as im:
                altered = im.copy()
            altered.putpixel((altered.width//2, altered.height//2), (255,0,255,255))
            altered.save(asset)
            audit = MODULE.audit_manifest(args['manifest_path'])
            self.assertFalse(audit['passed'])
            self.assertTrue(any('content' in e for e in audit['errors']))

    def test_audit_rejects_duplicate_cells_and_protected_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(Path(tmp))
            result = MODULE.compose(**args)
            result['pairs'][1]['cell'] = result['pairs'][0]['cell']
            result['protected_boxes_normalized'] = [[0,0,1,1]]
            args['manifest_path'].write_text(json.dumps(result), encoding='utf-8')
            audit = MODULE.audit_manifest(args['manifest_path'])
            self.assertFalse(audit['passed'])
            self.assertTrue(any('duplicate' in e for e in audit['errors']))
            self.assertTrue(any('protected' in e for e in audit['errors']))

    def test_small_rotation_limit_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = MODULE.compose(**self.make_case(Path(tmp), max_rotation=0.5))
            self.assertTrue(all(abs(p['rotation_degrees']) <= 0.5 for p in result['pairs']))

    def test_oversized_knobs_are_rejected_before_overlapping_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(Path(tmp), knob_ratio=.30)
            with self.assertRaises(ValueError):
                MODULE.compose(**args)
            self.assertFalse(args['output_path'].exists())

    def test_rejects_path_collisions_without_damaging_source(self):
        for collision in ('output_path', 'manifest_path'):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as tmp:
                args = self.make_case(Path(tmp))
                original = args['input_path'].read_bytes()
                args[collision] = args['input_path']
                with self.assertRaises(ValueError):
                    MODULE.compose(**args)
                self.assertEqual(args['input_path'].read_bytes(), original)

    def test_invalid_protection_and_nan_rotation_rejected_before_writes(self):
        for changes in ({'protected_norm': [(0.7, 0, 0.2, 1)]}, {'max_rotation': float('nan')},
                        {'rows': 500}, {'manual_cells': [(1,1)]}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                args = self.make_case(Path(tmp), **changes)
                with self.assertRaises(ValueError):
                    MODULE.compose(**args)
                self.assertFalse(args['output_path'].exists())
                self.assertFalse(args['pieces_dir'].exists())

    def test_every_canvas_pixel_belongs_to_exactly_one_cell(self):
        for ratio in (.08,.17,.22):
            for seed in (1,17,42):
                with self.subTest(ratio=ratio, seed=seed):
                    masks, _, _, _ = MODULE.masks_and_signatures((193, 129), 4, 6, seed, ratio)
                    counts = [0] * (193*129)
                    for mask in masks.values():
                        for i, value in enumerate(mask.tobytes()):
                            counts[i] += value // 255
                    self.assertEqual(set(counts), {1})

    def test_source_piece_pixels_and_alpha_can_be_independently_reconstructed(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_case(Path(tmp))
            im = Image.new('RGB', (320,240))
            im.putdata([(x % 256, y % 256, (x+y)%256) for y in range(240) for x in range(320)])
            im.save(args['input_path'])
            result = MODULE.compose(**args)
            for pair in result['pairs']:
                asset = Path(pair['piece_asset'])
                if not asset.is_absolute():
                    asset = args['manifest_path'].parent / asset
                with Image.open(asset) as piece:
                    crop = im.crop(pair['source_bbox'])
                    diff = ImageChops.difference(piece.convert('RGB'), crop)
                    self.assertIsNone(diff.getbbox())
                    self.assertEqual(piece.getchannel('A').getextrema(), (0,255))

    def test_adjacent_edges_are_complementary(self):
        _, signatures, _, _ = MODULE.masks_and_signatures((640, 360), 6, 10, 7, 0.19)
        for row in range(6):
            for col in range(9):
                self.assertEqual(signatures[(row, col)]["east"], -signatures[(row, col + 1)]["west"])
        for row in range(5):
            for col in range(10):
                self.assertEqual(signatures[(row, col)]["south"], -signatures[(row + 1, col)]["north"])

    def test_compose_emits_unique_exact_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = Image.new("RGB", (640, 360), "#EEE7DB")
            draw = ImageDraw.Draw(source)
            draw.rectangle((250, 70, 390, 290), fill="#242424")
            draw.ellipse((285, 110, 355, 180), fill="#777777")
            input_path = root / "input.png"
            output_path = root / "output.png"
            manifest_path = root / "output.json"
            pieces_dir = root / "pieces"
            source.save(input_path)

            manifest = MODULE.compose(
                input_path=input_path,
                output_path=output_path,
                manifest_path=manifest_path,
                rows=6,
                cols=10,
                missing_count=3,
                seed=9,
                protected_norm=[(0.35, 0.15, 0.65, 0.85)],
                manual_cells=[],
                knob_ratio=0.19,
                seam_width=1,
                max_rotation=8,
                hole_color=(216, 208, 196),
                pieces_dir=pieces_dir,
                content_policy='any',
            )

            self.assertTrue(output_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertEqual(len(manifest["pairs"]), 3)
            self.assertTrue(all(manifest["checks"].values()))
            self.assertEqual(len({p["pair_id"] for p in manifest["pairs"]}), 3)
            self.assertEqual(len({tuple(p["cell"]) for p in manifest["pairs"]}), 3)
            self.assertTrue(all(not p["mirrored"] for p in manifest["pairs"]))
            self.assertTrue(all(Path(p["piece_asset"]).exists() for p in manifest["pairs"]))
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["schema"], "black-dust-puzzle/v3")
            self.assertTrue(Path(loaded["assembled_output"]).exists())


if __name__ == "__main__":
    unittest.main()
