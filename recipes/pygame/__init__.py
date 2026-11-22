# Νεότερο pygame για το Android build.
# Το python-for-android έχει ακόμα το pygame 2.1.0 (2021), που δεν χτίζεται πια.
# Εδώ παίρνουμε το pygame 2.6.1 από το PyPI (έχει έτοιμα τα αρχεία C, δεν θέλει Cython).
from os.path import join

from pythonforandroid.recipes.pygame import Pygame2Recipe
from pythonforandroid.toolchain import current_directory

SIMD = "src_c/simd_blitters_sse2.c src_c/simd_blitters_avx2.c "


class Pygame261Recipe(Pygame2Recipe):
    version = '2.6.1'
    url = 'https://files.pythonhosted.org/packages/source/p/pygame/pygame-{version}.tar.gz'
    sha256sum = '56fb02ead529cee00d415c3e007f75e0780c655909aaa8e8bf616ee09c9feb1f'

    def prebuild_arch(self, arch):
        super().prebuild_arch(arch)
        # Το Setup.Android του pygame 2.6.1 ξεχνάει τα simd_blitters στο module "surface",
        # οπότε στο tablet το "import pygame" σκάει (undefined symbol) -> μαύρη οθόνη.
        with current_directory(self.get_build_dir(arch.arch)):
            setup = open("Setup").read()
            fixed = setup.replace("surface src_c/surface.c", "surface " + SIMD + "src_c/surface.c")
            if "simd_blitters_sse2.c" not in fixed:
                raise RuntimeError("Δεν βρέθηκε η γραμμή surface στο Setup του pygame")
            open("Setup", "w").write(fixed)


recipe = Pygame261Recipe()
