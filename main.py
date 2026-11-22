"""
Εκκίνηση της Ναυμαχίας.

Αν κάτι πάει στραβά στο ξεκίνημα, αντί να κλείσει σιωπηλά (όπως κάνει το Android),
δείχνει το λάθος στην οθόνη – για να ξέρουμε τι να διορθώσουμε.
Το ίδιο το παιχνίδι είναι στο naumaxia.py.
"""
import os
import sys
import traceback

try:
    import faulthandler
    faulthandler.enable()          # αν σκάσει κάτι σε C, γράφεται στο logcat
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def save_log(text):
    """Γράφει το λάθος και σε αρχείο, όπου γίνεται."""
    places = [HERE, os.path.expanduser("~")]
    if os.environ.get("ANDROID_PRIVATE"):
        places.insert(0, os.environ["ANDROID_PRIVATE"])
    for d in places:
        try:
            with open(os.path.join(d, "naumaxia-crash.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            return
        except OSError:
            pass


def toast(text):
    """Μήνυμα Android (αν δεν φορτώνει καν το pygame)."""
    try:
        from jnius import autoclass
        from android.runnable import run_on_ui_thread  # noqa: F401
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Toast = autoclass("android.widget.Toast")
        String = autoclass("java.lang.String")
        act = PythonActivity.mActivity

        @run_on_ui_thread
        def show():
            Toast.makeText(act, String(text[-600:]), Toast.LENGTH_LONG).show()
        show()
    except Exception:
        pass


def error_screen(text):
    """Δείχνει το λάθος στην οθόνη μέχρι να πατήσεις «πίσω»."""
    import pygame
    if not pygame.get_init():
        pygame.init()
    surf = pygame.display.get_surface()
    if surf is None:
        try:
            surf = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        except Exception:
            surf = pygame.display.set_mode((1200, 720))
    w, h = surf.get_size()
    size = max(14, h // 40)
    font = None
    for name in ("DejaVuSans.ttf",):
        p = os.path.join(HERE, "fonts", name)
        if os.path.exists(p):
            try:
                font = pygame.font.Font(p, size)
            except Exception:
                font = None
    if font is None:
        font = pygame.font.Font(None, size + 6)

    lines = ["ΝΑΥΜΑΧΙΑ – λάθος στο ξεκίνημα", "Βγάλε φωτογραφία αυτή την οθόνη και στείλ' τη.", ""]
    for raw in text.splitlines():
        raw = raw.replace("\t", "    ")
        while raw:
            n = len(raw)
            while n > 1 and font.size(raw[:n])[0] > w - 30:
                n -= 1
            lines.append(raw[:n])
            raw = raw[n:]
    lines = lines[:3] + lines[3:][-(h // (size + 6) - 4):]

    back = getattr(pygame, "K_AC_BACK", None)
    clock = pygame.time.Clock()
    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return
            if e.type == pygame.KEYDOWN and (e.key == back or e.key == pygame.K_ESCAPE):
                return
        surf.fill((40, 8, 8))
        y = 12
        for i, line in enumerate(lines):
            col = (255, 200, 80) if i < 2 else (240, 240, 240)
            surf.blit(font.render(line, True, col), (15, y))
            y += size + 6
        pygame.display.flip()
        clock.tick(10)


def main():
    try:
        sys.path.insert(0, HERE)
        import naumaxia
        naumaxia.Game().run()
    except SystemExit:
        raise
    except BaseException:
        text = traceback.format_exc()
        print(text, flush=True)    # φαίνεται και στο logcat
        save_log(text)
        try:
            error_screen(text)
        except BaseException:
            toast(text)
            import time
            time.sleep(15)


if __name__ == "__main__":
    main()
