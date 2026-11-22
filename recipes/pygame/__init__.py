# Νεότερο pygame για το Android build.
# Το python-for-android έχει ακόμα το pygame 2.1.0 (2021), που δεν χτίζεται πια.
# Εδώ παίρνουμε το pygame 2.6.1 από το PyPI (έχει έτοιμα τα αρχεία C, δεν θέλει Cython).
from pythonforandroid.recipes.pygame import Pygame2Recipe


class Pygame261Recipe(Pygame2Recipe):
    version = '2.6.1'
    url = 'https://files.pythonhosted.org/packages/source/p/pygame/pygame-{version}.tar.gz'
    sha256sum = '56fb02ead529cee00d415c3e007f75e0780c655909aaa8e8bf616ee09c9feb1f'


recipe = Pygame261Recipe()
