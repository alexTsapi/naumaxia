"""
ΝΑΥΜΑΧΙΑ – 2 παίκτες, ο καθένας από τον υπολογιστή του

Εγκατάσταση:   pip install pygame
Εκκίνηση:      python main.py   (ή python naumaxia.py)

- Παίκτης 1: "Δημιουργία παιχνιδιού"  -> βλέπει την IP του στην οθόνη
- Παίκτης 2: "Σύνδεση σε παιχνίδι"    -> γράφει την IP του Παίκτη 1
- "Παιχνίδι με υπολογιστή"            -> για να παίξεις μόνος σου

Ειδικές δυνάμεις (όσο το πλοίο σου δεν έχει βυθιστεί):
  ✈  Αεροπλανοφόρο -> Αεροπορική επιδρομή: 3 βόμβες στη σειρά (2 φορές)
  ◉  Υποβρύχιο     -> Σόναρ: εντοπίζει πλοία σε περιοχή 3x3 (2 φορές)
  ✚  Θωρηκτό       -> Ομοβροντία: 5 βολές σε σχήμα σταυρού (1 φορά)

Πλήκτρα: 1-4 = όπλο, R = περιστροφή, Enter = chat, M = ήχος, F11 = πλήρης οθόνη
Σε tablet: πάτα μία φορά για να σημαδέψεις και ξανά για να ρίξεις.
Ο server κρατάει τους στόλους και ελέγχει τους κανόνες – δεν γίνεται κλεψιά.
"""
import json
import math
import os
import queue
import random
import socket
import sys
import threading
import time
from array import array

import pygame

PORT = 50555
SIZE = 10
# (τύπος, όνομα, μήκος) – η σειρά είναι και η σειρά τοποθέτησης
KINDS = [
    ("carrier", "Αεροπλανοφόρο", 5),
    ("battleship", "Θωρηκτό", 4),
    ("cruiser", "Καταδρομικό", 3),
    ("sub", "Υποβρύχιο", 3),
    ("destroyer", "Αντιτορπιλικό", 2),
]
SHIPS = [k[2] for k in KINDS]
KIND_LEN = {k[0]: k[2] for k in KINDS}

# όπλο -> (index πλοίου που το έχει, φορές)
POWERS = {"air": (0, 2), "sonar": (3, 2), "salvo": (1, 1)}
WEAPONS = [
    ("shot", "Κανόνι", "απλή βολή"),
    ("air", "Αεροπορική επιδρομή", "3 βόμβες • πάτα ξανά: γύρισμα"),
    ("sonar", "Σόναρ", "εντοπίζει πλοία σε 3×3"),
    ("salvo", "Ομοβροντία", "5 βολές σε σταυρό"),
]
WEAPON_NAME = {w[0]: w[1] for w in WEAPONS}

CELL = 38
GRID_PX = SIZE * CELL
W, H = 1200, 720                      # εικονική ανάλυση – κλιμακώνεται στο παράθυρο
OWN_X, ENEMY_X, GRID_Y = 70, 750, 130
MID_X, MID_W = 470, 260
BOTTOM_Y, BOTTOM_H = 530, 175
LETTERS = "ΑΒΓΔΕΖΗΘΙΚ"
CONFIG = os.path.join(os.path.expanduser("~"), ".naumaxia.json")
SHELL_MS = 750

# Χρώματα
BG = (8, 20, 38)
PANEL = (14, 34, 60)
PANEL_EDGE = (40, 90, 140)
GRIDLINE = (60, 130, 190)
TEXT = (235, 240, 245)
DIM = (150, 180, 205)
ACCENT = (255, 190, 60)
GOOD = (90, 210, 120)
BAD = (240, 90, 80)
SONAR = (90, 255, 170)
MISS = (215, 232, 245)
FIRE_COLS = [(255, 220, 90), (255, 150, 40), (235, 70, 40)]

MOUSE = (0, 0)   # θέση ποντικιού σε εικονικές συντεταγμένες
IS_ANDROID = "ANDROID_ARGUMENT" in os.environ or hasattr(sys, "getandroidapilevel")


def android_display(size):
    """Οθόνη για tablet: η κλιμάκωση γίνεται από την κάρτα γραφικών (SCALED),
    που στο Android είναι πιο αξιόπιστο από το set_mode((0, 0))."""
    try:
        return pygame.display.set_mode(size, pygame.SCALED | pygame.FULLSCREEN)
    except pygame.error:
        return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)


def hide_android_splash():
    """Βγάζει την εικόνα εκκίνησης του Android (αλλιώς μένει από πάνω και φαίνεται μαύρο)."""
    if not IS_ANDROID:
        return
    try:
        from android import loadingscreen
        loadingscreen.hide_loading_screen()
    except Exception:
        try:
            from jnius import autoclass
            autoclass("org.kivy.android.PythonActivity").mActivity.removeLoadingScreen()
        except Exception:
            pass
TOUCH = IS_ANDROID   # σε tablet: πρώτο πάτημα = σημάδι, δεύτερο = φωτιά
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ================================================================ κοινά

def send(sock, obj):
    if sock is None:
        return
    try:
        sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))
    except OSError:
        pass


def reader(sock, q, tag=None):
    buf = b""
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    msg = json.loads(line.decode("utf-8"))
                    q.put((tag, msg) if tag is not None else msg)
    except (OSError, ValueError):
        pass
    closed = {"t": "_closed"}
    q.put((tag, closed) if tag is not None else closed)


def ship_cells(r, c, n, horiz):
    return [(r, c + k) if horiz else (r + k, c) for k in range(n)]


def is_horiz(cells):
    return len({r for r, _ in cells}) == 1


def pattern(w, r, c, horiz=True):
    """Ποια κουτάκια επηρεάζει κάθε όπλο."""
    if w == "air":
        if horiz:
            c0 = min(max(c - 1, 0), SIZE - 3)
            return [(r, c0 + k) for k in range(3)]
        r0 = min(max(r - 1, 0), SIZE - 3)
        return [(r0 + k, c) for k in range(3)]
    if w == "salvo":
        cells = [(r, c), (r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
    elif w == "sonar":
        cells = [(r + dr, c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)]
    else:
        cells = [(r, c)]
    return [(a, b) for a, b in cells if 0 <= a < SIZE and 0 <= b < SIZE]


def valid_fleet(ships):
    if [len(s) for s in ships] != SHIPS:
        return False
    seen = set()
    for s in ships:
        if not all(isinstance(r, int) and isinstance(c, int) and 0 <= r < SIZE and 0 <= c < SIZE for r, c in s):
            return False
        rows = {r for r, _ in s}
        cols = {c for _, c in s}
        if len(rows) == 1:
            line = sorted(c for _, c in s)
        elif len(cols) == 1:
            line = sorted(r for r, _ in s)
        else:
            return False
        if line != list(range(line[0], line[0] + len(s))):
            return False
        if seen & set(s):
            return False
        seen |= set(s)
    return True


def random_fleet():
    ships, occ = [], set()
    for n in SHIPS:
        while True:
            h = random.random() < 0.5
            r = random.randrange(SIZE if h else SIZE - n + 1)
            c = random.randrange(SIZE - n + 1 if h else SIZE)
            cells = ship_cells(r, c, n, h)
            if not occ & set(cells):
                ships.append(cells)
                occ |= set(cells)
                break
    return ships


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except OSError:
        pass


# ================================================================ server

class Server(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("", PORT))
        self.srv.listen(2)

    def stop(self):
        try:
            self.srv.close()
        except OSError:
            pass

    def run(self):
        try:
            self.serve()
        except OSError:
            pass
        finally:
            self.stop()

    def serve(self):
        conns = []
        while len(conns) < 2:
            c, _ = self.srv.accept()
            conns.append(c)
            if len(conns) == 1:
                send(c, {"t": "wait"})
        q = queue.Queue()
        for i, c in enumerate(conns):
            threading.Thread(target=reader, args=(c, q, i), daemon=True).start()
        names = [None, None]

        def new_round():
            for c in conns:
                send(c, {"t": "place"})
            return {"fleets": [None, None], "hits": [set(), set()], "shots": [set(), set()],
                    "sunk": [set(), set()], "uses": [{k: v[1] for k, v in POWERS.items()} for _ in range(2)],
                    "turn": None, "over": False, "rematch": set()}

        st = new_round()
        while True:
            i, m = q.get()
            o = 1 - i
            t = m.get("t")

            if t == "_closed":
                send(conns[o], {"t": "left"})
                break

            if t == "hello":
                names[i] = str(m.get("name", "")).strip()[:16] or f"Παίκτης {i + 1}"
                if all(names):
                    for k in (0, 1):
                        send(conns[k], {"t": "names", "opp": names[1 - k]})

            elif t == "chat":
                text = str(m.get("text", "")).strip()[:120]
                if text:
                    for k in (0, 1):
                        send(conns[k], {"t": "chat", "from": names[i] or "?", "mine": k == i, "text": text})

            elif t == "place" and st["fleets"][i] is None:
                try:
                    ships = [[tuple(x) for x in s] for s in m.get("ships", [])]
                except TypeError:
                    ships = []
                if not valid_fleet(ships):
                    send(conns[i], {"t": "place"})
                    continue
                st["fleets"][i] = ships
                if all(st["fleets"]):
                    st["turn"] = random.randint(0, 1)
                    for k in (0, 1):
                        send(conns[k], {"t": "start", "your_turn": k == st["turn"]})
                else:
                    send(conns[i], {"t": "wait_place"})

            elif t == "fire" and st["turn"] == i:
                r, c, w = m.get("r"), m.get("c"), m.get("weapon", "shot")
                horiz = bool(m.get("horiz", True))
                if not (isinstance(r, int) and isinstance(c, int) and 0 <= r < SIZE and 0 <= c < SIZE):
                    continue
                if w != "shot":
                    if w not in POWERS or st["uses"][i][w] <= 0 or POWERS[w][0] in st["sunk"][i]:
                        continue

                if w == "sonar":
                    st["uses"][i][w] -= 1
                    found = [[a, b, any((a, b) in s for s in st["fleets"][o])] for a, b in pattern("sonar", r, c)]
                    send(conns[i], {"t": "sonar", "mine": True, "r": r, "c": c, "cells": found})
                    send(conns[o], {"t": "sonar", "mine": False, "r": r, "c": c})
                else:
                    new = [x for x in pattern(w, r, c, horiz) if x not in st["shots"][i]]
                    if not new:
                        continue
                    if w != "shot":
                        st["uses"][i][w] -= 1
                    results = []
                    for cell in new:
                        st["shots"][i].add(cell)
                        idx = next((k for k, s in enumerate(st["fleets"][o]) if cell in s), None)
                        sunk = None
                        if idx is not None:
                            st["hits"][o].add(cell)
                            ship = st["fleets"][o][idx]
                            if all(x in st["hits"][o] for x in ship):
                                sunk = ship
                                st["sunk"][o].add(idx)
                        results.append({"r": cell[0], "c": cell[1], "hit": idx is not None,
                                        "sunk": sunk, "sunk_idx": idx if sunk else None})
                    res = {"t": "attack", "weapon": w, "r": r, "c": c, "horiz": horiz, "results": results}
                    send(conns[i], dict(res, mine=True))
                    send(conns[o], dict(res, mine=False))
                    if len(st["hits"][o]) == sum(SHIPS):
                        st["turn"], st["over"] = None, True
                        send(conns[i], {"t": "over", "win": True, "enemy": st["fleets"][o]})
                        send(conns[o], {"t": "over", "win": False, "enemy": st["fleets"][i]})
                        continue
                st["turn"] = o
                for k in (0, 1):
                    send(conns[k], {"t": "turn", "your_turn": k == st["turn"]})

            elif t == "rematch" and st["over"]:
                st["rematch"].add(i)
                if len(st["rematch"]) == 2:
                    st = new_round()
                else:
                    send(conns[o], {"t": "rematch_req"})

        for c in conns:
            try:
                c.close()
            except OSError:
                pass


# ================================================================ υπολογιστής (bot)

class Bot(threading.Thread):
    """Παίζει σαν δεύτερος παίκτης – συνδέεται στον server όπως κάθε άλλος."""

    def __init__(self):
        super().__init__(daemon=True)

    @staticmethod
    def choose(tried, open_hits):
        def ok(x):
            return 0 <= x[0] < SIZE and 0 <= x[1] < SIZE and x not in tried

        if open_hits:
            cands = []
            if len(open_hits) >= 2:
                rows = {r for r, _ in open_hits}
                cols = {c for _, c in open_hits}
                if len(rows) == 1:
                    r = next(iter(rows))
                    cs = sorted(cols)
                    cands = [(r, cs[0] - 1), (r, cs[-1] + 1)]
                elif len(cols) == 1:
                    c = next(iter(cols))
                    rs = sorted(rows)
                    cands = [(rs[0] - 1, c), (rs[-1] + 1, c)]
                cands = [x for x in cands if ok(x)]
            if not cands:
                for (r, c) in open_hits:
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        if ok((r + dr, c + dc)):
                            cands.append((r + dr, c + dc))
            if cands:
                return random.choice(cands)
        pool = [(r, c) for r in range(SIZE) for c in range(SIZE) if (r + c) % 2 == 0 and (r, c) not in tried]
        if not pool:
            pool = [(r, c) for r in range(SIZE) for c in range(SIZE) if (r, c) not in tried]
        return random.choice(pool)

    def decide(self, S):
        tried = S["tried"]

        def can(w):
            return S["uses"][w] > 0 and POWERS[w][0] not in S["lost"]

        def fresh(cells):
            return [x for x in cells if x not in tried]

        if S["open_hits"]:
            r, c = self.choose(tried, S["open_hits"])
            if can("salvo") and random.random() < 0.4 and len(fresh(pattern("salvo", r, c))) >= 3:
                return "salvo", r, c, True
            return "shot", r, c, True
        S["suspects"] = [x for x in S["suspects"] if x not in tried]
        if S["suspects"]:
            r, c = S["suspects"][0]
            return "shot", r, c, True
        if can("sonar") and random.random() < 0.45:
            best = max(((a, b) for a in range(1, SIZE - 1) for b in range(1, SIZE - 1)),
                       key=lambda x: len(fresh(pattern("sonar", *x))) + random.random())
            if len(fresh(pattern("sonar", *best))) >= 6:
                return "sonar", best[0], best[1], True
        if can("air") and random.random() < 0.3:
            h = random.random() < 0.5
            r, c = self.choose(tried, [])
            if len(fresh(pattern("air", r, c, h))) >= 2:
                return "air", r, c, h
        r, c = self.choose(tried, [])
        return "shot", r, c, True

    def run(self):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
            s.settimeout(None)
        except OSError:
            return
        q = queue.Queue()
        threading.Thread(target=reader, args=(s, q), daemon=True).start()
        send(s, {"t": "hello", "name": "Υπολογιστής"})

        def fresh_state():
            return {"tried": set(), "open_hits": [], "suspects": [], "lost": set(),
                    "uses": {k: v[1] for k, v in POWERS.items()}}
        S = fresh_state()
        while True:
            m = q.get()
            t = m.get("t")
            if t in ("_closed", "left"):
                break
            if t == "place":
                S = fresh_state()
                time.sleep(0.6)
                send(s, {"t": "place", "ships": random_fleet()})
            elif t in ("start", "turn") and m.get("your_turn"):
                time.sleep(random.uniform(1.2, 1.8))
                w, r, c, h = self.decide(S)
                if w in POWERS:
                    S["uses"][w] -= 1
                send(s, {"t": "fire", "weapon": w, "r": r, "c": c, "horiz": h})
            elif t == "attack":
                for res in m["results"]:
                    cell = (res["r"], res["c"])
                    if m["mine"]:
                        S["tried"].add(cell)
                        if res["hit"]:
                            S["open_hits"].append(cell)
                        if res.get("sunk"):
                            sunk = {tuple(x) for x in res["sunk"]}
                            S["open_hits"] = [x for x in S["open_hits"] if x not in sunk]
                    elif res.get("sunk"):
                        S["lost"].add(res["sunk_idx"])
            elif t == "sonar" and m.get("mine"):
                for a, b, found in m["cells"]:
                    if found and (a, b) not in S["tried"] and (a, b) not in S["suspects"]:
                        S["suspects"].append((a, b))
            elif t == "over":
                time.sleep(2.5)
                send(s, {"t": "rematch"})
        try:
            s.close()
        except OSError:
            pass


# ================================================================ ήχοι (παράγονται με κώδικα)

class LP:
    """Απλό χαμηλοπερατό φίλτρο."""
    __slots__ = ("a", "y")

    def __init__(self, a):
        self.a, self.y = a, 0.0

    def __call__(self, x):
        self.y += self.a * (x - self.y)
        return self.y


class Sounds:
    def __init__(self, progress=None):
        self.on = True
        self.s = {}
        self.progress = progress
        try:
            if pygame.mixer.get_init():
                pygame.mixer.set_num_channels(32)
                self.s = self.build()
        except Exception as e:  # χωρίς κάρτα ήχου το παιχνίδι παίζει κανονικά
            print("Ήχοι απενεργοποιημένοι:", e)
            self.s = {}

    @staticmethod
    def set_pan(ch, pan, vol=1.0):
        pan = max(-1.0, min(1.0, pan))
        ch.set_volume(vol * min(1.0, 1 - pan), vol * min(1.0, 1 + pan))

    def play(self, name, pan=0.0, vol=1.0):
        if not self.on or name not in self.s:
            return None
        ch = self.s[name].play()
        if ch:
            self.set_pan(ch, pan, vol)
        return ch

    def build(self):
        freq, _, chs = pygame.mixer.get_init()
        TP = 2 * math.pi
        rnd = random.uniform

        def gen(dur, fn):
            return [fn(i / freq) for i in range(int(dur * freq))]

        def reverb(x, mix=0.3, fb=0.5, tail=0.6):
            n = len(x) + int(tail * freq)
            y = x + [0.0] * (n - len(x))
            out = list(y)
            for d in (0.0297, 0.0371, 0.0411, 0.0437):
                D = int(d * freq)
                buf = [0.0] * n
                for i in range(D, n):
                    v = y[i - D] + fb * buf[i - D]
                    buf[i] = v
                    out[i] += mix * 0.25 * v
            return out

        def snd(x, vol=0.9):
            peak = max(1e-6, max(abs(v) for v in x))
            k = vol / peak * 32767
            n = len(x)
            fade = max(1, min(n // 4, int(0.03 * freq)))
            a = array("h")
            for i, v in enumerate(x):
                if i > n - fade:
                    v *= (n - i) / fade
                s = int(v * k)
                a.append(s)
                if chs == 2:
                    a.append(s)
            done[0] += 1
            if self.progress:
                self.progress(done[0], 11)
            return pygame.mixer.Sound(buffer=a.tobytes())

        done = [0]
        S = {}

        # κανόνι: βαθύ "μπουμ" με κρότο και αντήχηση
        lp1, lp2 = LP(0.12), LP(0.5)

        def cannon(t):
            n = rnd(-1, 1)
            return (math.sin(TP * (45 + 30 * math.exp(-t * 12)) * t) * math.exp(-t * 7)
                    + lp1(n) * 3.0 * math.exp(-t * 6) + lp2(n) * 0.8 * math.exp(-t * 35))
        S["cannon"] = snd(reverb(gen(0.7, cannon), 0.35), 0.75)

        # σφύριγμα οβίδας που πέφτει (ο τόνος κατεβαίνει όσο πλησιάζει)
        def whistle_fn(f0, k, dur):
            st = {"ph": 0.0}
            air = LP(0.3)

            def f(t):
                fr = f0 * math.exp(-t * k) + 12 * math.sin(TP * 7 * t)
                st["ph"] += TP * fr / freq
                amp = 0.15 + 0.85 * min(1.0, t / (dur * 0.8))
                return math.sin(st["ph"]) * amp * 0.6 + air(rnd(-1, 1)) * 0.25 * amp
            return f
        S["whistle"] = snd(gen(SHELL_MS / 1000, whistle_fn(1700, 1.5, SHELL_MS / 1000)), 0.4)
        S["bombfall"] = snd(gen(0.35, whistle_fn(1300, 2.2, 0.35)), 0.35)

        # έκρηξη: κρότος + σώμα + βαθύ μπουμπουνητό
        la, lb, lc = LP(0.08), LP(0.015), LP(0.45)

        def boom(t):
            n = rnd(-1, 1)
            return (lc(n) * 1.6 * math.exp(-t * 28) + la(n) * 4.0 * math.exp(-t * 3.2)
                    + lb(n) * 14 * math.exp(-t * 1.4) + math.sin(TP * 36 * t) * math.exp(-t * 4) * 1.1)
        S["boom"] = snd(reverb(gen(1.4, boom), 0.3, 0.5, 0.8), 0.95)

        # πλατσούρισμα στο νερό + γουργουρητό φυσαλίδων
        f1, f2, f3 = LP(0.55), LP(0.06), LP(0.25)

        def splash(t):
            n = rnd(-1, 1)
            bp = f1(n) - f2(n)
            env = min(1.0, t / 0.012) * math.exp(-t * 6.5)
            gurgle = math.sin(TP * (420 + 260 * math.sin(TP * 9 * t) + 150 * math.sin(TP * 23 * t)) * t) * 0.18 * math.exp(-t * 3.5)
            return bp * 1.7 * env + f3(n) * 0.6 * math.exp(-t * 2.2) + gurgle + math.sin(TP * 80 * t) * math.exp(-t * 18) * 0.6
        S["splash"] = snd(reverb(gen(1.1, splash), 0.25), 0.75)

        # βύθιση: μεγάλη έκρηξη + μέταλλο που "βογκάει" + φυσαλίδες
        sa, sb, sl = LP(0.05), LP(0.012), LP(0.1)
        sg = {"ph": 0.0}

        def sink(t):
            n = rnd(-1, 1)
            expl = sa(n) * 4 * math.exp(-t * 2.2) + sb(n) * 14 * math.exp(-t * 0.9) + math.sin(TP * 32 * t) * math.exp(-t * 2.5)
            fr = 95 * math.exp(-t * 0.35) + 5 * math.sin(TP * 2.3 * t)
            sg["ph"] += TP * fr / freq
            saw = sl(2 * ((sg["ph"] / TP) % 1) - 1)
            tt = max(0.0, t - 0.3)
            groan = saw * 1.2 * min(1.0, tt / 0.4) * math.exp(-tt * 0.9)
            bub = math.sin(TP * (300 + 200 * math.sin(TP * 13 * t)) * t) * 0.12 * math.exp(-t * 0.8) * (0.5 + 0.5 * math.sin(TP * 5 * t))
            return expl + groan + bub
        S["sink"] = snd(reverb(gen(2.6, sink), 0.3, 0.5, 0.8), 0.95)

        # σόναρ: το κλασικό "πινγκ" με ηχώ
        def sonar(t):
            v = 0.0
            for d, a in ((0.0, 1.0), (0.55, 0.35), (1.1, 0.13)):
                tt = t - d
                if tt >= 0:
                    v += math.sin(TP * 1180 * tt) * math.exp(-tt * 6) * a * min(1.0, tt / 0.004)
            return v
        S["sonar"] = snd(reverb(gen(1.8, sonar), 0.45, 0.6, 1.0), 0.5)

        # αεροπλάνα που περνάνε (πλησιάζουν και απομακρύνονται)
        pl = {"ph": 0.0}
        pn, pt = LP(0.22), LP(0.15)

        def plane(t):
            x = t / 2.3
            env = math.exp(-((x - 0.45) / 0.25) ** 2)
            fr = 150 * (1 + 0.2 * math.tanh((0.45 - x) * 7))
            pl["ph"] += TP * fr / freq
            tone = pt(2 * ((pl["ph"] / TP) % 1) - 1)
            return (pn(rnd(-1, 1)) * 3 + tone * 0.7) * env
        S["plane"] = snd(gen(2.3, plane), 0.7)

        def tune(notes, nd):
            def f(t):
                k = min(int(t / nd), len(notes) - 1)
                tt = t - k * nd
                fr = notes[k]
                return (math.sin(TP * fr * t) + 0.3 * math.sin(TP * 2 * fr * t)) * math.exp(-tt * 4)
            return f
        S["win"] = snd(reverb(gen(1.0, tune([523, 659, 784, 1047], 0.15)), 0.2), 0.5)
        S["lose"] = snd(reverb(gen(1.3, tune([392, 330, 262, 196], 0.25)), 0.2), 0.5)
        S["click"] = snd(gen(0.07, lambda t: math.sin(TP * 900 * t) * math.exp(-t * 45)), 0.3)
        return S


# ================================================================ γραφικά: πλοία & αεροπλάνα

def _jet(s, x, y, k):
    col = (210, 215, 220)
    pygame.draw.line(s, col, (x - k, y), (x + k, y), 2)
    pygame.draw.polygon(s, col, [(x + k * 0.1, y), (x - k * 0.35, y - k * 0.8),
                                 (x - k * 0.15, y), (x - k * 0.35, y + k * 0.8)])


def draw_ship(kind, c):
    """Σχεδιάζει το πλοίο οριζόντια, με την πλώρη δεξιά."""
    L, h = KIND_LEN[kind] * c, c
    s = pygame.Surface((L, h), pygame.SRCALPHA)
    m = max(2, c // 10)
    cy = h / 2
    lw = max(1, c // 16)

    if kind == "sub":
        body = pygame.Rect(m, int(h * 0.3), L - 2 * m, int(h * 0.4))
        pygame.draw.polygon(s, (40, 46, 55), [(m + 2, cy), (m + c * 0.35, h * 0.16), (m + c * 0.45, cy)])
        pygame.draw.polygon(s, (40, 46, 55), [(m + 2, cy), (m + c * 0.35, h * 0.84), (m + c * 0.45, cy)])
        pygame.draw.ellipse(s, (52, 60, 70), body)
        pygame.draw.ellipse(s, (25, 30, 38), body, 2)
        pygame.draw.line(s, (85, 95, 108), (m + c * 0.3, cy), (L - m - c * 0.3, cy), 1)
        tw = pygame.Rect(int(L * 0.45), int(h * 0.37), int(L * 0.13), int(h * 0.26))
        pygame.draw.rect(s, (72, 82, 95), tw, border_radius=max(2, c // 8))
        pygame.draw.rect(s, (25, 30, 38), tw, 1, border_radius=max(2, c // 8))
        pygame.draw.circle(s, (150, 160, 170), (tw.centerx + 2, tw.centery), max(1, c // 14))
        return s

    if kind == "carrier":
        top, bot = h * 0.12, h * 0.88
    elif kind == "destroyer":
        top, bot = h * 0.27, h * 0.73
    else:
        top, bot = h * 0.21, h * 0.79
    hull = [(m, top + 2), (L * 0.82, top), (L - m, cy), (L * 0.82, bot), (m, bot - 2)]
    inner = [(m + 4, top + 4), (L * 0.81, top + 3), (L - m - 7, cy), (L * 0.81, bot - 3), (m + 4, bot - 4)]
    pygame.draw.polygon(s, (105, 115, 128), hull)
    pygame.draw.polygon(s, (45, 52, 62), hull, 2)

    if kind == "carrier":
        pygame.draw.polygon(s, (68, 72, 78), inner)
        x = m + 8
        while x < L * 0.85:
            pygame.draw.line(s, (230, 230, 230), (x, cy), (min(x + c * 0.3, L * 0.85), cy), 1)
            x += c * 0.55
        pygame.draw.line(s, (240, 200, 80), (m + 6, bot - 6), (L * 0.55, top + 5), 1)
        isl = pygame.Rect(int(L * 0.62), int(top + 1), int(L * 0.12), int(h * 0.2))
        pygame.draw.rect(s, (160, 168, 178), isl, border_radius=2)
        pygame.draw.rect(s, (45, 52, 62), isl, 1, border_radius=2)
        pygame.draw.circle(s, (60, 60, 66), (isl.centerx, isl.centery), max(1, c // 12))
        for px in (0.14, 0.27, 0.40):
            _jet(s, L * px, cy + h * 0.2, c * 0.22)
        _jet(s, L * 0.5, cy - h * 0.2, c * 0.22)
        return s

    pygame.draw.polygon(s, (160, 168, 178), inner)
    pygame.draw.line(s, (130, 138, 148), (m + 6, cy), (L * 0.8, cy), 1)

    def turret(x, d):
        r = h * 0.15
        for off in (-r * 0.35, r * 0.35):
            pygame.draw.line(s, (35, 38, 44), (x, cy + off), (x + d * h * 0.42, cy + off), lw)
        pygame.draw.circle(s, (88, 96, 108), (x, cy), r)
        pygame.draw.circle(s, (35, 38, 44), (x, cy), r, 1)

    def bridge(x, w, hh=0.36):
        r = pygame.Rect(0, 0, w, h * hh)
        r.center = (x, cy)
        pygame.draw.rect(s, (205, 210, 215), r, border_radius=3)
        pygame.draw.rect(s, (70, 76, 86), r, 1, border_radius=3)
        pygame.draw.line(s, (40, 70, 110), (r.right - 3, r.top + 3), (r.right - 3, r.bottom - 3), 2)

    def funnel(x, w):
        r = pygame.Rect(0, 0, w, h * 0.22)
        r.center = (x, cy)
        pygame.draw.ellipse(s, (60, 60, 66), r)
        pygame.draw.ellipse(s, (22, 22, 26), r.inflate(-w * 0.4, -h * 0.1))

    if kind == "battleship":
        turret(L * 0.13, -1)
        turret(L * 0.27, -1)
        funnel(L * 0.38, L * 0.07)
        bridge(L * 0.48, L * 0.14)
        turret(L * 0.65, 1)
        turret(L * 0.78, 1)
    elif kind == "cruiser":
        turret(L * 0.17, -1)
        funnel(L * 0.36, L * 0.09)
        bridge(L * 0.5, L * 0.2)
        turret(L * 0.74, 1)
    else:
        funnel(L * 0.33, L * 0.12)
        bridge(L * 0.54, L * 0.18, 0.3)
        turret(L * 0.79, 1)
    return s


_cache = {}


def ship_sprite(kind, c, horiz=True, tint=None):
    key = ("ship", kind, c, horiz, tint)
    if key not in _cache:
        if not horiz:
            surf = pygame.transform.rotate(ship_sprite(kind, c, True, tint), -90)
        elif tint:
            surf = ship_sprite(kind, c, True, None).copy()
            surf.fill(tint, special_flags=pygame.BLEND_RGBA_MULT)
        else:
            surf = draw_ship(kind, c)
        _cache[key] = surf
    return _cache[key]


def plane_sprite(sz, angle=0, shadow=False):
    """Μαχητικό αεροσκάφος από πάνω, με τη μύτη δεξιά."""
    key = ("plane", sz, int(angle), shadow)
    if key in _cache:
        return _cache[key]
    if angle:
        surf = pygame.transform.rotate(plane_sprite(sz, 0, shadow), angle)
    else:
        surf = pygame.Surface((sz, sz), pygame.SRCALPHA)
        c = sz / 2
        col = (0, 0, 0, 80) if shadow else (178, 186, 196)
        edge = (60, 66, 76)
        fus = [(sz * 0.97, c), (sz * 0.78, c - sz * 0.06), (sz * 0.12, c - sz * 0.05), (sz * 0.03, c),
               (sz * 0.12, c + sz * 0.05), (sz * 0.78, c + sz * 0.06)]
        wings = [(sz * 0.62, c - sz * 0.04), (sz * 0.36, c - sz * 0.46), (sz * 0.27, c - sz * 0.46),
                 (sz * 0.38, c), (sz * 0.27, c + sz * 0.46), (sz * 0.36, c + sz * 0.46), (sz * 0.62, c + sz * 0.04)]
        tail = [(sz * 0.22, c), (sz * 0.07, c - sz * 0.2), (sz * 0.01, c - sz * 0.2), (sz * 0.09, c),
                (sz * 0.01, c + sz * 0.2), (sz * 0.07, c + sz * 0.2)]
        for poly in (wings, tail, fus):
            pygame.draw.polygon(surf, col, poly)
            if not shadow:
                pygame.draw.polygon(surf, edge, poly, 1)
        if not shadow:
            pygame.draw.ellipse(surf, (60, 140, 220), (sz * 0.66, c - sz * 0.035, sz * 0.15, sz * 0.07))
            pygame.draw.circle(surf, (255, 170, 60), (int(sz * 0.04), int(c)), max(2, sz // 18))
    _cache[key] = surf
    return surf


def make_water():
    s = pygame.Surface((GRID_PX, GRID_PX))
    for y in range(GRID_PX):
        k = y / GRID_PX
        pygame.draw.line(s, (int(20 + 6 * k), int(86 - 18 * k), int(142 - 24 * k)), (0, y), (GRID_PX, y))
    shade = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
    shade.fill((255, 255, 255, 9))
    for r in range(SIZE):
        for c in range(SIZE):
            if (r + c) % 2:
                s.blit(shade, (c * CELL, r * CELL))
    for k in range(1, SIZE):
        pygame.draw.line(s, (55, 120, 180), (k * CELL, 0), (k * CELL, GRID_PX), 1)
        pygame.draw.line(s, (55, 120, 180), (0, k * CELL), (GRID_PX, k * CELL), 1)
    return s


# ================================================================ UI

def make_font(size, bold=False):
    """Χρησιμοποιεί τη γραμματοσειρά του φακέλου fonts/ (έχει ελληνικά και στο Android)."""
    path = os.path.join(BASE_DIR, "fonts", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    if os.path.exists(path):
        return pygame.font.Font(path, max(8, int(size * 0.88)))
    return pygame.font.SysFont("segoeui,arial,dejavusans,helvetica", size, bold=bold)


def fit(text, font, width):
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "…")[0] > width:
        text = text[:-1]
    return text + "…"


class Button:
    def __init__(self, rect, text):
        self.rect = pygame.Rect(rect)
        self.text = text

    def draw(self, surf, font, enabled=True):
        hover = enabled and self.rect.collidepoint(MOUSE)
        col = ACCENT if hover else (36, 104, 165)
        if not enabled:
            col = (50, 60, 76)
        pygame.draw.rect(surf, (4, 10, 20), self.rect.move(0, 4), border_radius=12)
        pygame.draw.rect(surf, col, self.rect, border_radius=12)
        pygame.draw.rect(surf, (255, 255, 255) if hover else GRIDLINE, self.rect, 2, border_radius=12)
        txt = font.render(self.text, True, BG if hover else (TEXT if enabled else DIM))
        surf.blit(txt, txt.get_rect(center=self.rect.center))

    def hit(self, pos):
        return pos is not None and self.rect.collidepoint(pos)


class Game:
    def __init__(self):
        pygame.mixer.pre_init(22050, -16, 2, 1024 if IS_ANDROID else 512)
        pygame.init()
        if IS_ANDROID:
            android_display((W, H))
            self.win_size = pygame.display.get_surface().get_size()
            self.fullscreen = True
            pygame.key.stop_text_input()   # το πληκτρολόγιο ανοίγει μόνο όταν χρειάζεται
        else:
            info = pygame.display.Info()
            sw, sh = info.current_w, info.current_h
            if sw <= 0 or sh <= 0:
                sw, sh = W, H + 90
            sc = max(0.6, min(sw * 0.96 / W, (sh - 90) / H))
            self.win_size = (int(W * sc), int(H * sc))
            self.fullscreen = False
            pygame.display.set_mode(self.win_size, pygame.RESIZABLE)
        pygame.display.set_caption("Ναυμαχία")
        self.screen = pygame.Surface((W, H))
        self.view = pygame.Rect(0, 0, *self.win_size)
        self.clock = pygame.time.Clock()
        self.f_huge = make_font(84, True)
        self.f_title = make_font(42, True)
        self.f_big = make_font(30, True)
        self.f_bold = make_font(20, True)
        self.f = make_font(20)
        self.f_small = make_font(16)
        self.f_sb = make_font(15, True)
        self.f_tiny = make_font(13)

        # οθόνη φόρτωσης όσο φτιάχνονται οι ήχοι
        self.loading("Φόρτωση…", 0)
        hide_android_splash()
        self.snd = Sounds(progress=lambda k, n: self.loading("Φόρτωση ήχων…", k / n))

        self.cfg = load_config()
        self.name = self.cfg.get("name", "Παίκτης")
        self.ip_text = self.cfg.get("ip", "")
        self.state = "menu"
        self.sock = None
        self.server = None
        self.vs_cpu = False
        self.q = queue.Queue()
        self.info = ""
        self.my_ip = lan_ip()
        self.water = make_water()
        self.overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        self.chat = []
        self.chat_active = False
        self.chat_text = ""
        self.opp_name = "Αντίπαλος"

        cx = W // 2
        self.b_host = Button((cx - 210, 300, 420, 58), "Δημιουργία παιχνιδιού")
        self.b_join = Button((cx - 210, 370, 420, 58), "Σύνδεση σε παιχνίδι")
        self.b_cpu = Button((cx - 210, 440, 420, 58), "Παιχνίδι με υπολογιστή")
        self.b_go = Button((cx - 210, 380, 200, 56), "Σύνδεση")
        self.b_back = Button((cx + 10, 380, 200, 56), "Πίσω")
        self.b_random = Button((ENEMY_X, BOTTOM_Y, 120, 50), "Τυχαία")
        self.b_undo = Button((ENEMY_X + 130, BOTTOM_Y, 120, 50), "Αναίρεση")
        self.b_clear = Button((ENEMY_X + 260, BOTTOM_Y, 120, 50), "Καθαρισμός")
        self.b_rotate = Button((ENEMY_X, BOTTOM_Y + 62, 185, 50), "Περιστροφή ↻")
        self.b_ready = Button((ENEMY_X + 195, BOTTOM_Y + 62, 185, 50), "Έτοιμος!")
        self.name_box = pygame.Rect(W // 2 - 180, 222, 360, 50)
        self.ip_box = pygame.Rect(W // 2 - 210, 265, 420, 64)
        self.chat_box = pygame.Rect(MID_X + 10, BOTTOM_Y + BOTTOM_H - 36, MID_W - 20, 28)
        self.sound_box = pygame.Rect(MID_X + 14, GRID_Y + GRID_PX - 26, MID_W - 28, 24)
        self.b_rematch = Button((cx - 210, 410, 200, 56), "Ρεβάνς")
        self.b_menu = Button((cx + 10, 410, 200, 56), "Μενού")
        self.b_menu_c = Button((cx - 100, 420, 200, 56), "Μενού")
        self.reset_round()

    # ------------------------------------------------ παράθυρο / κλιμάκωση
    def loading(self, text, frac):
        self.screen.fill(BG)
        self.text(text, self.f_big, TEXT, center=(W // 2, H // 2 - 20))
        bar = pygame.Rect(W // 2 - 200, H // 2 + 25, 400, 16)
        pygame.draw.rect(self.screen, PANEL_EDGE, bar, 2, border_radius=8)
        if frac > 0:
            pygame.draw.rect(self.screen, ACCENT, (bar.x + 3, bar.y + 3, int((bar.w - 6) * min(1, frac)), bar.h - 6),
                             border_radius=6)
        self.present()
        pygame.event.pump()

    def present(self):
        win = pygame.display.get_surface()
        ww, wh = win.get_size()
        sc = min(ww / W, wh / H)
        vw, vh = int(W * sc), int(H * sc)
        self.view = pygame.Rect((ww - vw) // 2, (wh - vh) // 2, vw, vh)
        win.fill((0, 0, 0))
        if (vw, vh) == (W, H):
            win.blit(self.screen, self.view)
        else:
            win.blit(pygame.transform.smoothscale(self.screen, (vw, vh)), self.view)
        pygame.display.flip()

    def map_pos(self, p):
        v = self.view
        if v.w == 0 or v.h == 0:
            return p
        return int((p[0] - v.x) * W / v.w), int((p[1] - v.y) * H / v.h)

    @staticmethod
    def keyboard(on):
        """Πληκτρολόγιο οθόνης στο Android (στον υπολογιστή δεν χρειάζεται)."""
        if IS_ANDROID:
            if on:
                pygame.key.start_text_input()
            else:
                pygame.key.stop_text_input()

    def toggle_fullscreen(self):
        if IS_ANDROID:
            return
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            pygame.display.set_mode(self.win_size, pygame.RESIZABLE)

    # ------------------------------------------------ κατάσταση
    def reset_round(self):
        self.placed = []
        self.horiz = True
        self.incoming = {}          # (r,c) -> True/False   βολές αντιπάλου σε μένα
        self.shots = {}             # (r,c) -> hit/miss/sunk   δικές μου βολές
        self.enemy_sunk = []        # [(idx, cells)]
        self.my_sunk_idx = set()
        self.my_turn = False
        self.win = None
        self.enemy_fleet = None
        self.effects = []
        self.rings = []
        self.projectiles = []
        self.planes = []
        self.timeline = []
        self.particles = []
        self.banner = None
        self.rematch_sent = False
        self.pending_over = None
        self.my_shots = self.my_hits = self.opp_shots = self.opp_hits = 0
        self.weapon = "shot"
        self.air_horiz = True
        self.uses = {k: v[1] for k, v in POWERS.items()}
        self.sonar_marks = set()
        self.sonar_empty = set()
        self.sonar_scan = None
        self.aim_cell = None

    def busy(self):
        return bool(self.projectiles or self.planes or self.timeline)

    def show_banner(self, text, color):
        self.banner = (text, color, pygame.time.get_ticks())

    def add_chat(self, who, text, mine=False):
        self.chat.append((who, text, mine))
        self.chat = self.chat[-40:]

    @staticmethod
    def pan(x):
        return (x / W * 2 - 1) * 0.85

    # ------------------------------------------------ δίκτυο
    def connect(self, ip):
        try:
            s = socket.create_connection((ip, PORT), timeout=5)
            s.settimeout(None)
        except OSError as e:
            self.info = f"Αποτυχία σύνδεσης: {e}"
            return False
        self.sock = s
        self.q = queue.Queue()
        threading.Thread(target=reader, args=(s, self.q), daemon=True).start()
        send(s, {"t": "hello", "name": self.name.strip() or "Παίκτης"})
        self.cfg["name"] = self.name
        if ip not in ("127.0.0.1", "localhost"):
            self.cfg["ip"] = ip
        save_config(self.cfg)
        self.chat = []
        self.opp_name = "Αντίπαλος"
        self.state = "waiting"
        return True

    def host(self, vs_cpu=False):
        try:
            self.server = Server()
        except OSError as e:
            self.info = f"Δεν άνοιξε ο server (πόρτα {PORT}): {e}"
            return
        self.server.start()
        self.vs_cpu = vs_cpu
        if self.connect("127.0.0.1") and vs_cpu:
            Bot().start()

    def back_to_menu(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        if self.server:
            self.server.stop()
            self.server = None
        self.reset_round()
        self.chat_active = False
        self.state = "menu"
        self.info = ""

    def handle(self, m):
        t = m.get("t")
        if t == "wait":
            self.state = "waiting"
        elif t == "names":
            self.opp_name = m.get("opp", "Αντίπαλος")
        elif t == "place":
            self.reset_round()
            self.state = "placing"
        elif t == "wait_place":
            self.state = "wait_place"
        elif t == "start":
            self.state = "playing"
            self.my_turn = m["your_turn"]
            self.show_banner("Ξεκινάς εσύ!" if self.my_turn else f"Ξεκινάει: {self.opp_name}", ACCENT)
        elif t == "turn":
            self.my_turn = m["your_turn"]
        elif t == "attack":
            self.on_attack(m)
        elif t == "sonar":
            self.on_sonar(m)
        elif t == "over":
            self.pending_over = m
        elif t == "chat":
            self.add_chat("Εσύ" if m.get("mine") else m.get("from", "?"), m.get("text", ""), m.get("mine"))
            if not m.get("mine"):
                self.snd.play("click")
        elif t == "rematch_req":
            self.show_banner(f"{self.opp_name}: θέλει ρεβάνς!", ACCENT)
        elif t in ("left", "_closed"):
            if self.state != "menu":
                self.state = "disconnected"

    # ------------------------------------------------ όπλα & εφέ
    def cell_center(self, x0, cell):
        return x0 + cell[1] * CELL + CELL // 2, GRID_Y + cell[0] * CELL + CELL // 2

    def gun_source(self, mine, prefer=None):
        if mine:
            alive = [k for k in range(len(self.placed)) if k not in self.my_sunk_idx]
            if prefer is not None and prefer in alive:
                k = prefer
            elif alive:
                k = random.choice(alive)
            else:
                return OWN_X + GRID_PX // 2, GRID_Y + GRID_PX // 2
            return self.cell_center(OWN_X, random.choice(self.placed[k]))
        return ENEMY_X + GRID_PX // 2 + random.randint(-80, 80), GRID_Y + GRID_PX // 3 + random.randint(-60, 60)

    def launch(self, src, dst, t0, dur, res, mine, arc=170, whistle=True, cannon=True, kind="shell"):
        self.projectiles.append({"src": src, "dst": dst, "t0": t0, "dur": dur, "res": res, "mine": mine,
                                 "arc": arc, "whistle": whistle, "cannon": cannon, "kind": kind,
                                 "started": False, "chan": None})

    def on_attack(self, m):
        mine, w = m["mine"], m["weapon"]
        now = pygame.time.get_ticks()
        x0 = ENEMY_X if mine else OWN_X
        if mine and w in POWERS:
            self.uses[w] -= 1
        if w != "shot":
            self.show_banner(f"{WEAPON_NAME[w]}!" if mine else f"{self.opp_name}: {WEAPON_NAME[w]}!",
                             ACCENT if mine else BAD)
        results = m["results"]
        if w == "shot":
            res = results[0]
            self.launch(self.gun_source(mine), self.cell_center(x0, (res["r"], res["c"])), now, SHELL_MS, res, mine)
        elif w == "salvo":
            for k, res in enumerate(results):
                src = self.gun_source(mine, prefer=1)
                self.launch(src, self.cell_center(x0, (res["r"], res["c"])), now + k * 120, SHELL_MS, res, mine)
        elif w == "air":
            self.air_strike(m, mine, now)

    def air_strike(self, m, mine, now):
        cells = pattern("air", m["r"], m["c"], m["horiz"])
        x0 = ENEMY_X if mine else OWN_X
        centers = [self.cell_center(x0, c) for c in cells]
        d = 1 if mine else -1
        first, last = (centers[0], centers[-1]) if d == 1 else (centers[-1], centers[0])
        if m["horiz"]:
            p0 = (first[0] - d * 4 * CELL, first[1])
            p1 = (last[0] + d * 4 * CELL, last[1])
        else:
            p0 = (first[0], first[1] - d * 4 * CELL)
            p1 = (last[0], last[1] + d * 4 * CELL)
        t0, dur = now + 200, 2000
        self.planes.append({"p0": p0, "p1": p1, "t0": t0, "dur": dur, "chan": None, "started": False})
        total = math.dist(p0, p1)
        by_cell = {(r["r"], r["c"]): r for r in m["results"]}
        for cell, cc in zip(cells, centers):
            res = by_cell.get(cell)
            if res:
                tdrop = t0 + dur * math.dist(p0, cc) / total - 250
                self.launch((cc[0], cc[1] - 60), cc, tdrop, 350, res, mine, arc=0,
                            whistle=False, cannon=False, kind="bomb")

    def on_sonar(self, m):
        mine = m["mine"]
        now = pygame.time.get_ticks()
        x0 = ENEMY_X if mine else OWN_X
        cx, cy = self.cell_center(x0, (m["r"], m["c"]))
        if mine:
            self.uses["sonar"] -= 1
            self.show_banner("Σόναρ!", SONAR)
        else:
            self.show_banner(f"{self.opp_name}: σε εντοπίζει με σόναρ!", BAD)
        self.sonar_scan = {"x0": x0, "cells": pattern("sonar", m["r"], m["c"]), "t0": now, "dur": 1700,
                           "center": (cx, cy)}
        for k in range(3):
            self.rings.append((cx, cy, now + k * 450, SONAR, 1100, CELL * 2.3))
        self.snd.play("sonar", self.pan(cx))

        def reveal():
            if mine:
                for a, b, found in m["cells"]:
                    if (a, b) not in self.shots:
                        (self.sonar_marks if found else self.sonar_empty).add((a, b))
                n = sum(1 for _, _, f in m["cells"] if f)
                self.show_banner(f"Σόναρ: {n} επαφές!" if n else "Σόναρ: καμία επαφή", SONAR)
            self.sonar_scan = None
        self.timeline.append([now + 1700, reveal])

    def apply_result(self, res, mine):
        cell = (res["r"], res["c"])
        hit = res["hit"]
        sunk = [tuple(x) for x in res["sunk"]] if res.get("sunk") else None
        idx = res.get("sunk_idx")
        if mine:
            x0 = ENEMY_X
            self.my_shots += 1
            self.shots[cell] = "hit" if hit else "miss"
            self.sonar_marks.discard(cell)
            self.sonar_empty.discard(cell)
            if hit:
                self.my_hits += 1
            if sunk:
                for x in sunk:
                    self.shots[x] = "sunk"
                    self.sonar_marks.discard(x)
                self.enemy_sunk.append((idx, sunk))
                self.show_banner(f"Βύθισες το {KINDS[idx][1]}!", GOOD)
        else:
            x0 = OWN_X
            self.opp_shots += 1
            self.incoming[cell] = hit
            if hit:
                self.opp_hits += 1
            if sunk:
                self.my_sunk_idx.add(idx)
                pw = next((k for k, v in POWERS.items() if v[0] == idx), None)
                lost = f" Έχασες: {WEAPON_NAME[pw]}" if pw else ""
                self.show_banner(f"Βυθίστηκε το {KINDS[idx][1]} σου!{lost}", BAD)
                if self.weapon in POWERS and POWERS[self.weapon][0] == idx:
                    self.weapon = "shot"
        cx, cy = self.cell_center(x0, cell)
        pan = self.pan(cx)
        if sunk:
            for x in sunk:
                self.explode(*self.cell_center(x0, x), big=True)
            self.snd.play("sink", pan)
        elif hit:
            self.explode(cx, cy)
            self.snd.play("boom", pan)
        else:
            self.splash(cx, cy)
            self.snd.play("splash", pan)

    def spawn(self, x, y, vx, vy, life, size, color, kind, grow=0.0):
        if len(self.particles) < 1200:
            self.particles.append([x, y, vx, vy, life, life, size, color, kind, grow])

    def explode(self, x, y, big=False):
        for _ in range(34 if big else 26):
            a = random.uniform(0, 2 * math.pi)
            sp = random.uniform(50, 230 if big else 180)
            self.spawn(x, y, math.cos(a) * sp, math.sin(a) * sp - 70, random.uniform(0.35, 0.85),
                       random.uniform(2, 4.5), random.choice(FIRE_COLS), "spark")
        for _ in range(8 if big else 5):
            self.spawn(x + random.uniform(-6, 6), y + random.uniform(-6, 6), random.uniform(-15, 15),
                       random.uniform(-45, -15), random.uniform(1.0, 2.0), random.uniform(6, 10),
                       (70, 70, 75), "smoke", 10)
        self.effects.append((x, y, pygame.time.get_ticks(), True))

    def splash(self, x, y):
        for _ in range(22):
            self.spawn(x + random.uniform(-4, 4), y, random.uniform(-70, 70), random.uniform(-260, -120),
                       random.uniform(0.45, 0.8), random.uniform(2, 3.5),
                       random.choice([(200, 230, 255), (150, 200, 240), (255, 255, 255)]), "drop")
        self.effects.append((x, y, pygame.time.get_ticks(), False))

    def proj_pos(self, pr, p):
        (x0, y0), (x1, y1) = pr["src"], pr["dst"]
        return x0 + (x1 - x0) * p, y0 + (y1 - y0) * p - math.sin(math.pi * p) * pr["arc"]

    @staticmethod
    def plane_pos(pl, p):
        (x0, y0), (x1, y1) = pl["p0"], pl["p1"]
        return x0 + (x1 - x0) * p, y0 + (y1 - y0) * p

    def update(self, dt):
        now = pygame.time.get_ticks()

        for ev in self.timeline[:]:
            if now >= ev[0]:
                self.timeline.remove(ev)
                ev[1]()

        for pl in self.planes[:]:
            if not pl["started"] and now >= pl["t0"]:
                pl["started"] = True
                pl["chan"] = self.snd.play("plane", self.pan(pl["p0"][0]))
            if pl["started"]:
                p = (now - pl["t0"]) / pl["dur"]
                if pl["chan"]:
                    Sounds.set_pan(pl["chan"], self.pan(self.plane_pos(pl, min(1, p))[0]))
                if p >= 1:
                    self.planes.remove(pl)

        for pr in self.projectiles[:]:
            if not pr["started"] and now >= pr["t0"]:
                pr["started"] = True
                sx = pr["src"][0]
                if pr["cannon"]:
                    self.snd.play("cannon", self.pan(sx), 0.9)
                    for _ in range(12):
                        a = random.uniform(0, 2 * math.pi)
                        self.spawn(pr["src"][0], pr["src"][1], math.cos(a) * 70, math.sin(a) * 70 - 30, 0.25, 3,
                                   random.choice(FIRE_COLS), "spark")
                    self.spawn(pr["src"][0], pr["src"][1], 10, -20, 1.2, 6, (90, 90, 95), "smoke", 12)
                if pr["whistle"]:
                    pr["chan"] = self.snd.play("whistle", self.pan(sx), 0.8)
                if pr["kind"] == "bomb":
                    pr["chan"] = self.snd.play("bombfall", self.pan(pr["dst"][0]), 0.8)
            if pr["started"]:
                p = (now - pr["t0"]) / pr["dur"]
                if pr["chan"]:
                    Sounds.set_pan(pr["chan"], self.pan(self.proj_pos(pr, min(1, p))[0]), 0.8)
                if p >= 1:
                    self.projectiles.remove(pr)
                    if pr["res"]:
                        self.apply_result(pr["res"], pr["mine"])

        if self.pending_over and not self.busy():
            m, self.pending_over = self.pending_over, None
            self.state = "over"
            self.banner = None
            self.win = m["win"]
            self.enemy_fleet = [[tuple(x) for x in s] for s in m.get("enemy", [])]
            self.snd.play("win" if self.win else "lose")

        for p in self.particles:
            p[4] -= dt
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            if p[8] == "spark":
                p[3] += 300 * dt
            elif p[8] == "drop":
                p[3] += 520 * dt
            else:
                p[6] += p[9] * dt
                p[2] *= 1 - 0.6 * dt
        self.particles = [p for p in self.particles if p[4] > 0]

        if self.state in ("playing", "over"):
            sources = [(ENEMY_X, c, 2.2 if k == "hit" else 0.8) for c, k in self.shots.items() if k != "miss"]
            sources += [(OWN_X, c, 2.2) for c, h in self.incoming.items() if h]
            for x0, cell, rate in sources:
                if random.random() < rate * dt:
                    cx, cy = self.cell_center(x0, cell)
                    g = random.randint(45, 75)
                    self.spawn(cx + random.uniform(-4, 4), cy - 4, random.uniform(8, 24), random.uniform(-45, -28),
                               random.uniform(1.5, 2.6), random.uniform(3, 5), (g, g, g + 5), "smoke", 8)

    # ------------------------------------------------ βοηθητικά
    def cell_at(self, pos, x0):
        if pos is None:
            return None
        x, y = pos
        if x < x0 or y < GRID_Y:
            return None
        c, r = (x - x0) // CELL, (y - GRID_Y) // CELL
        if 0 <= r < SIZE and 0 <= c < SIZE:
            return int(r), int(c)
        return None

    def can_place(self, cells):
        occ = {c for s in self.placed for c in s}
        return all(0 <= r < SIZE and 0 <= c < SIZE and (r, c) not in occ for r, c in cells)

    def preview_cells(self, pos=None):
        if len(self.placed) >= len(SHIPS):
            return None
        cell = self.cell_at(pos or MOUSE, OWN_X)
        if not cell:
            return None
        return ship_cells(*cell, SHIPS[len(self.placed)], self.horiz)

    def weapon_state(self, w):
        """(διαθέσιμο, κείμενο)"""
        desc = next(x[2] for x in WEAPONS if x[0] == w)
        if w == "shot":
            return True, desc
        idx = POWERS[w][0]
        if idx in self.my_sunk_idx:
            return False, f"το {KINDS[idx][1]} βυθίστηκε"
        if self.uses[w] <= 0:
            return False, "εξαντλήθηκε"
        if w == "air":
            desc = ("↔ " if self.air_horiz else "↕ ") + desc
        return True, f"×{self.uses[w]} • {desc}"

    def weapon_rects(self):
        return [(w[0], pygame.Rect(MID_X + 14, GRID_Y + 96 + k * 50, MID_W - 28, 44)) for k, w in enumerate(WEAPONS)]

    def select_weapon(self, w):
        if self.weapon_state(w)[0]:
            if w == "air" and self.weapon == "air":
                self.air_horiz = not self.air_horiz   # δεύτερο πάτημα = γύρισμα
            self.weapon = w
            self.snd.play("click")

    def target_cells(self, cell):
        return pattern(self.weapon, cell[0], cell[1], self.air_horiz)

    # ------------------------------------------------ events
    def on_event(self, e):
        st = self.state
        pos = self.map_pos(e.pos) if e.type == pygame.MOUSEBUTTONDOWN else None
        click = e.type == pygame.MOUSEBUTTONDOWN and e.button == 1

        if e.type == pygame.VIDEORESIZE and not self.fullscreen:
            self.win_size = e.size
            return
        if e.type == pygame.KEYDOWN and e.key == pygame.K_F11:
            self.toggle_fullscreen()
            return
        back = getattr(pygame, "K_AC_BACK", None)
        if e.type == pygame.KEYDOWN and back is not None and e.key == back:   # κουμπί "πίσω" του Android
            if self.chat_active:
                self.chat_active = False
                self.keyboard(False)
            elif st == "join":
                self.keyboard(False)
                self.state = "menu"
            elif st == "menu":
                pygame.quit()
                sys.exit()
            return
        if click and st in ("placing", "wait_place", "playing", "over") and self.chat_box.collidepoint(pos):
            self.chat_active = True
            self.chat_text = ""
            self.keyboard(True)
            return

        if e.type == pygame.TEXTINPUT:
            if st == "menu" and len(self.name) < 16:
                self.name += e.text
            elif st == "join":
                ch = "".join(x for x in e.text.lower() if x in "0123456789.abcdefghijklmnopqrstuvwxyz-")
                self.ip_text = (self.ip_text + ch)[:40]
            elif self.chat_active and len(self.chat_text) < 100:
                self.chat_text += e.text
            return

        if e.type == pygame.KEYDOWN:
            if self.chat_active:
                if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if self.chat_text.strip():
                        send(self.sock, {"t": "chat", "text": self.chat_text})
                    self.chat_text = ""
                    self.chat_active = False
                    self.keyboard(False)
                elif e.key == pygame.K_BACKSPACE:
                    self.chat_text = self.chat_text[:-1]
                elif e.key == pygame.K_ESCAPE:
                    self.chat_active = False
                    self.keyboard(False)
                return
            if e.key == pygame.K_ESCAPE and self.fullscreen:
                self.toggle_fullscreen()
                return
            if st == "menu" and e.key == pygame.K_BACKSPACE:
                self.name = self.name[:-1]
                return
            if st == "menu" and e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.keyboard(False)
                return
            if st == "join":
                if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.ip_text:
                    self.keyboard(False)
                    self.connect(self.ip_text.strip())
                elif e.key == pygame.K_BACKSPACE:
                    self.ip_text = self.ip_text[:-1]
                elif e.key == pygame.K_ESCAPE:
                    self.state = "menu"
                return
            if st in ("placing", "wait_place", "playing", "over"):
                if e.key == pygame.K_RETURN:
                    self.chat_active = True
                    self.chat_text = ""
                    return
                if e.key == pygame.K_m:
                    self.snd.on = not self.snd.on
                    return
            if st == "placing":
                if e.key == pygame.K_r:
                    self.horiz = not self.horiz
                elif e.key == pygame.K_SPACE:
                    self.placed = random_fleet()
            if st == "playing":
                keys = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_4: 3,
                        pygame.K_KP1: 0, pygame.K_KP2: 1, pygame.K_KP3: 2, pygame.K_KP4: 3}
                if e.key in keys:
                    self.select_weapon(WEAPONS[keys[e.key]][0])
                elif e.key == pygame.K_r:
                    self.air_horiz = not self.air_horiz

        if st == "menu" and click:
            if self.name_box.collidepoint(pos):
                self.keyboard(True)
                return
            self.keyboard(False)
            if self.b_host.hit(pos):
                self.info = ""
                self.host()
            elif self.b_join.hit(pos):
                self.info = ""
                self.state = "join"
                self.keyboard(True)
            elif self.b_cpu.hit(pos):
                self.info = ""
                self.host(vs_cpu=True)

        elif st == "join" and click:
            if self.ip_box.collidepoint(pos):
                self.keyboard(True)
            elif self.b_go.hit(pos) and self.ip_text:
                self.keyboard(False)
                self.connect(self.ip_text.strip())
            elif self.b_back.hit(pos):
                self.keyboard(False)
                self.state = "menu"

        elif st == "placing":
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 3:
                self.horiz = not self.horiz
            elif e.type == pygame.MOUSEWHEEL:
                self.horiz = not self.horiz
            elif click:
                if self.b_random.hit(pos):
                    self.placed = random_fleet()
                elif self.b_rotate.hit(pos):
                    self.horiz = not self.horiz
                elif self.b_undo.hit(pos):
                    self.placed = self.placed[:-1]
                elif self.b_clear.hit(pos):
                    self.placed = []
                elif self.b_ready.hit(pos) and len(self.placed) == len(SHIPS):
                    send(self.sock, {"t": "place", "ships": self.placed})
                    self.state = "wait_place"
                else:
                    cells = self.preview_cells(pos)
                    if cells and self.can_place(cells):
                        self.placed.append(cells)
                        self.snd.play("click")

        elif st == "playing":
            if (e.type == pygame.MOUSEBUTTONDOWN and e.button == 3) or e.type == pygame.MOUSEWHEEL:
                self.air_horiz = not self.air_horiz
            elif click:
                if self.sound_box.collidepoint(pos):
                    self.snd.on = not self.snd.on
                    return
                for w, rect in self.weapon_rects():
                    if rect.collidepoint(pos):
                        self.select_weapon(w)
                        return
                if self.my_turn and not self.busy():
                    cell = self.cell_at(pos, ENEMY_X)
                    if cell:
                        if not self.weapon_state(self.weapon)[0]:
                            self.weapon = "shot"
                        if TOUCH and cell != self.aim_cell:   # πρώτο πάτημα: σημάδι
                            self.aim_cell = cell
                            self.snd.play("click")
                            return
                        cells = self.target_cells(cell)
                        if self.weapon != "sonar" and not [x for x in cells if x not in self.shots]:
                            return
                        send(self.sock, {"t": "fire", "weapon": self.weapon, "r": cell[0], "c": cell[1],
                                         "horiz": self.air_horiz})
                        self.my_turn = False
                        self.weapon = "shot"
                        self.aim_cell = None

        elif st == "over" and click:
            if self.b_rematch.hit(pos) and not self.rematch_sent:
                send(self.sock, {"t": "rematch"})
                self.rematch_sent = True
            elif self.b_menu.hit(pos):
                self.back_to_menu()

        elif st in ("waiting", "disconnected") and click:
            if self.b_menu_c.hit(pos):
                self.back_to_menu()

    # ------------------------------------------------ σχεδίαση: βασικά
    def text(self, text, font, color, center=None, topleft=None):
        t = font.render(text, True, color)
        if center:
            self.screen.blit(t, t.get_rect(center=center))
        else:
            self.screen.blit(t, topleft)

    def panel(self, rect, title=None):
        rect = pygame.Rect(rect)
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=14)
        pygame.draw.rect(self.screen, PANEL_EDGE, rect, 1, border_radius=14)
        if title:
            self.text(title, self.f_bold, TEXT, topleft=(rect.x + 14, rect.y + 8))
        return rect

    def draw_sea_scene(self, y0=590):
        s = self.screen
        t = pygame.time.get_ticks() / 1000
        pygame.draw.rect(s, (14, 52, 92), (0, y0, W, H - y0))
        for k in range(4):
            yy = y0 + 18 + k * 30
            pts = [(x, yy + 4 * math.sin(x / 45 + t * (1.6 + k * 0.3) + k)) for x in range(0, W + 20, 20)]
            pygame.draw.lines(s, (40 + k * 8, 100 + k * 10, 160 + k * 8), False, pts, 2)
        x1 = (t * 60) % (W + 400) - 300
        s.blit(ship_sprite("carrier", 48), (x1, y0 + 18 + 3 * math.sin(t * 2)))
        x2 = W - ((t * 90 + 500) % (W + 300))
        s.blit(pygame.transform.flip(ship_sprite("destroyer", 44), True, False), (x2, y0 + 72 + 3 * math.sin(t * 2.4 + 1)))
        x3 = (t * 35 + 700) % (W + 300) - 200
        s.blit(ship_sprite("sub", 36), (x3, y0 + 100 + 2 * math.sin(t * 1.7)))
        xp = (t * 220) % (W + 600) - 300
        s.blit(plane_sprite(40, 0, True), (xp + 20, y0 - 50))
        s.blit(plane_sprite(40), (xp, y0 - 80))

    def draw_grid(self, x0, label):
        s = self.screen
        self.text(fit(label, self.f_bold, GRID_PX), self.f_bold, TEXT, topleft=(x0, GRID_Y - 62))
        for i in range(SIZE):
            self.text(LETTERS[i], self.f_small, DIM, center=(x0 + i * CELL + CELL // 2, GRID_Y - 14))
            self.text(str(i + 1), self.f_small, DIM, center=(x0 - 18, GRID_Y + i * CELL + CELL // 2))
        s.blit(self.water, (x0, GRID_Y))
        t = pygame.time.get_ticks() / 1000
        s.set_clip(pygame.Rect(x0, GRID_Y, GRID_PX, GRID_PX))
        for r in range(SIZE):
            for j in range(2):
                x = x0 + (t * 16 + j * 190 + r * 57) % (GRID_PX + 30) - 15
                y = GRID_Y + r * CELL + 12 + j * 14 + 3 * math.sin(t * 1.4 + r + j)
                pygame.draw.arc(s, (80, 150, 210), (x, y, 16, 8), 0.3, 2.8, 2)
        s.set_clip(None)
        pygame.draw.rect(s, GRIDLINE, (x0 - 2, GRID_Y - 2, GRID_PX + 4, GRID_PX + 4), 2, border_radius=3)

    def blit_ship(self, x0, idx, cells, tint=None):
        kind = KINDS[idx][0]
        rmin = min(r for r, _ in cells)
        cmin = min(c for _, c in cells)
        self.screen.blit(ship_sprite(kind, CELL, is_horiz(cells), tint), (x0 + cmin * CELL, GRID_Y + rmin * CELL))

    def draw_fire(self, x0, cell, strength=1.0, scorch=True):
        cx, cy = self.cell_center(x0, cell)
        t = pygame.time.get_ticks() / 90
        if scorch:
            pygame.draw.circle(self.screen, (35, 22, 18), (cx, cy), int(CELL * 0.3))
        for k in range(3):
            fl = math.sin(t * 1.7 + k * 2.1 + cell[0] * 3 + cell[1] * 5)
            r = (5 + 2.5 * fl) * strength + (2 - k) * 2.5
            ox = 3 * math.sin(t * 0.9 + k * 2)
            oy = -3 * k - 2 * fl
            pygame.draw.circle(self.screen, FIRE_COLS[2 - k], (cx + ox * 0.5, cy + oy), max(2, int(r)))

    def draw_miss(self, x0, cell):
        cx, cy = self.cell_center(x0, cell)
        pygame.draw.circle(self.screen, (170, 205, 235), (cx, cy), 10, 1)
        pygame.draw.circle(self.screen, MISS, (cx, cy), 5)

    def shade_cells(self, x0, cells, rgba):
        hl = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        hl.fill(rgba)
        for r, c in cells:
            self.screen.blit(hl, (x0 + c * CELL, GRID_Y + r * CELL))

    # ------------------------------------------------ σχεδίαση: ταμπλό
    def draw_own_board(self):
        self.draw_grid(OWN_X, f"Ο στόλος σου – {self.name}")
        for idx, cells in enumerate(self.placed):
            self.blit_ship(OWN_X, idx, cells, (110, 80, 80, 255) if idx in self.my_sunk_idx else None)
        sunk_cells = {c for k in self.my_sunk_idx for c in self.placed[k]} if self.placed else set()
        for cell, hit in self.incoming.items():
            if hit:
                self.draw_fire(OWN_X, cell, 0.6 if cell in sunk_cells else 1.0, scorch=False)
            else:
                self.draw_miss(OWN_X, cell)
        self.draw_scan(OWN_X)

    def draw_scan(self, x0):
        sc = self.sonar_scan
        if not sc or sc["x0"] != x0:
            return
        now = pygame.time.get_ticks()
        p = (now - sc["t0"]) / sc["dur"]
        a = int(40 + 30 * math.sin(now / 90))
        self.shade_cells(x0, sc["cells"], (90, 255, 170, a))
        cx, cy = sc["center"]
        ang = p * 2 * math.pi * 1.5
        self.screen.set_clip(pygame.Rect(x0, GRID_Y, GRID_PX, GRID_PX))
        for k in range(8):
            aa = ang - k * 0.06
            col = (90, 255, 170) if k == 0 else (40, 140 - k * 10, 100 - k * 8)
            pygame.draw.line(self.screen, col, (cx, cy), (cx + math.cos(aa) * CELL * 1.6, cy + math.sin(aa) * CELL * 1.6), 2)
        self.screen.set_clip(None)

    def draw_enemy_board(self, reveal=None):
        self.draw_grid(ENEMY_X, f"Νερά του αντιπάλου – {self.opp_name}")
        sunk_idx = {i for i, _ in self.enemy_sunk}
        if reveal:
            for idx, cells in enumerate(reveal):
                if idx not in sunk_idx:
                    self.blit_ship(ENEMY_X, idx, cells, (255, 255, 255, 150))
        for idx, cells in self.enemy_sunk:
            self.blit_ship(ENEMY_X, idx, cells, (150, 90, 90, 255))
        t = pygame.time.get_ticks()
        for cell in self.sonar_empty:
            cx, cy = self.cell_center(ENEMY_X, cell)
            pygame.draw.circle(self.screen, (60, 150, 120), (cx, cy), 3)
        for cell in self.sonar_marks:
            cx, cy = self.cell_center(ENEMY_X, cell)
            rr = 10 + 3 * math.sin(t / 160 + cell[0] + cell[1])
            pygame.draw.circle(self.screen, SONAR, (cx, cy), int(rr), 2)
            pygame.draw.circle(self.screen, SONAR, (cx, cy), 4)
        for cell, kind in self.shots.items():
            if kind == "miss":
                self.draw_miss(ENEMY_X, cell)
            else:
                self.draw_fire(ENEMY_X, cell, 0.6 if kind == "sunk" else 1.0, scorch=kind == "hit")
        self.draw_scan(ENEMY_X)
        if self.state == "playing" and self.my_turn and not self.busy():
            cell = self.aim_cell if TOUCH else self.cell_at(MOUSE, ENEMY_X)
            if cell:
                cells = self.target_cells(cell)
                if self.weapon == "sonar":
                    self.shade_cells(ENEMY_X, cells, (90, 255, 170, 55))
                    col = SONAR
                else:
                    self.shade_cells(ENEMY_X, [x for x in cells if x not in self.shots], (255, 170, 60, 70))
                    col = ACCENT
                for (r, c) in cells:
                    pygame.draw.rect(self.screen, col, (ENEMY_X + c * CELL + 1, GRID_Y + r * CELL + 1, CELL - 2, CELL - 2), 1, border_radius=4)
                cx, cy = self.cell_center(ENEMY_X, cell)
                pulse = 2 * math.sin(t / 120)
                pygame.draw.circle(self.screen, col, (cx, cy), int(9 + pulse), 2)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    pygame.draw.line(self.screen, col, (cx + dx * 5, cy + dy * 5), (cx + dx * 15, cy + dy * 15), 2)

    def draw_fx(self):
        s = self.screen
        now = pygame.time.get_ticks()
        self.overlay.fill((0, 0, 0, 0))
        for p in self.particles:
            if p[8] == "smoke":
                a = int(120 * (p[4] / p[5]))
                pygame.draw.circle(self.overlay, p[7] + (a,), (int(p[0]), int(p[1])), int(p[6]))
        for pr in self.projectiles:
            if not pr["started"] or pr["kind"] != "shell":
                continue
            pp = min(1.0, (now - pr["t0"]) / pr["dur"])
            for k in range(1, 7):
                q = pp - k * 0.03
                if q > 0:
                    x, y = self.proj_pos(pr, q)
                    pygame.draw.circle(self.overlay, (200, 200, 210, 140 - k * 18), (int(x), int(y)), 5 - k // 2)
        s.blit(self.overlay, (0, 0))

        for p in self.particles:
            if p[8] != "smoke":
                r = max(1, int(p[6] * (0.4 + 0.6 * p[4] / p[5])))
                pygame.draw.circle(s, p[7], (int(p[0]), int(p[1])), r)

        for pr in self.projectiles:
            if not pr["started"]:
                continue
            pp = min(1.0, (now - pr["t0"]) / pr["dur"])
            x, y = self.proj_pos(pr, pp)
            if pr["kind"] == "bomb":
                sz = 9 - 5 * pp
                pygame.draw.ellipse(s, (30, 30, 34), (x - sz / 2, y - sz, sz, sz * 2))
                pygame.draw.ellipse(s, (0, 0, 0), (pr["dst"][0] - 6 * pp, pr["dst"][1] - 3 * pp, 12 * pp, 6 * pp))
            else:
                scale = 1 + 0.5 * math.sin(math.pi * pp)
                pygame.draw.circle(s, (25, 25, 28), (int(x), int(y)), int(5 * scale))
                pygame.draw.circle(s, (180, 180, 190), (int(x) - 2, int(y) - 2), 2)

        for pl in self.planes:
            if not pl["started"]:
                continue
            p = min(1.0, (now - pl["t0"]) / pl["dur"])
            (x0, y0), (x1, y1) = pl["p0"], pl["p1"]
            ang = -math.degrees(math.atan2(y1 - y0, x1 - x0))
            ux, uy = (x1 - x0), (y1 - y0)
            L = math.hypot(ux, uy) or 1
            ux, uy = ux / L, uy / L
            px, py = -uy, ux
            lx, ly = self.plane_pos(pl, p)
            for off, back, sz in ((0, 0, 62), (-34, 36, 50), (34, 36, 50)):
                x = lx + px * off - ux * back
                y = ly + py * off - uy * back
                sh = plane_sprite(sz, round(ang), True)
                s.blit(sh, sh.get_rect(center=(x + 14, y + 22)))
                spr = plane_sprite(sz, round(ang))
                s.blit(spr, spr.get_rect(center=(x, y)))

        alive = []
        for (x, y, t0, hit) in self.effects:
            age = now - t0
            if age < 600:
                p = age / 600
                col = (255, 150, 60) if hit else (200, 230, 255)
                pygame.draw.circle(s, col, (int(x), int(y)), int(8 + p * 30), max(1, int(4 * (1 - p)) + 1))
                alive.append((x, y, t0, hit))
        self.effects = alive

        rings = []
        for (x, y, t0, col, dur, maxr) in self.rings:
            age = now - t0
            if age < 0:
                rings.append((x, y, t0, col, dur, maxr))
            elif age < dur:
                p = age / dur
                c2 = tuple(int(v * (1 - p) + 20 * p) for v in col)
                pygame.draw.circle(s, c2, (int(x), int(y)), int(6 + p * maxr), 2)
                rings.append((x, y, t0, col, dur, maxr))
        self.rings = rings

    def draw_banner(self):
        if not self.banner:
            return
        text, color, t0 = self.banner
        age = pygame.time.get_ticks() - t0
        if age > 2000:
            self.banner = None
            return
        scale = min(1.0, age / 150)
        t = self.f_big.render(text, True, color)
        if scale < 1:
            t = pygame.transform.smoothscale(t, (max(1, int(t.get_width() * scale)), max(1, int(t.get_height() * scale))))
        box = t.get_rect(center=(W // 2, 84)).inflate(44, 16)
        pygame.draw.rect(self.screen, (5, 14, 28), box, border_radius=14)
        pygame.draw.rect(self.screen, color, box, 2, border_radius=14)
        self.screen.blit(t, t.get_rect(center=box.center))

    # ------------------------------------------------ σχεδίαση: πάνελ
    def weapon_icon(self, w, center, enabled):
        s = self.screen
        cx, cy = center
        col = TEXT if enabled else DIM
        if w == "shot":
            pygame.draw.circle(s, (30, 30, 34), (cx, cy), 9)
            pygame.draw.circle(s, (170, 170, 180), (cx - 3, cy - 3), 3)
        elif w == "air":
            spr = plane_sprite(34)
            if not enabled:
                spr = spr.copy()
                spr.fill((120, 120, 120, 150), special_flags=pygame.BLEND_RGBA_MULT)
            s.blit(spr, spr.get_rect(center=center))
        elif w == "sonar":
            c = SONAR if enabled else DIM
            pygame.draw.circle(s, c, (cx, cy), 3)
            for r in (7, 12):
                pygame.draw.circle(s, c, (cx, cy), r, 1)
        else:
            c = (255, 150, 60) if enabled else DIM
            for dx, dy in ((0, 0), (9, 0), (-9, 0), (0, 9), (0, -9)):
                pygame.draw.circle(s, c, (cx + dx, cy + dy), 4)
        return col

    def draw_mid_panel(self):
        r = self.panel((MID_X, GRID_Y, MID_W, GRID_PX))
        cx = r.centerx
        t = pygame.time.get_ticks()
        # δείκτης σειράς
        box = pygame.Rect(r.x + 14, r.y + 12, r.w - 28, 72)
        mine = self.my_turn
        col = GOOD if mine else BAD
        glow = 40 + int(25 * math.sin(t / 250))
        pygame.draw.rect(self.screen, (col[0] // 4 + glow // 3, col[1] // 4 + glow // 3, col[2] // 4 + glow // 3), box, border_radius=12)
        pygame.draw.rect(self.screen, col, box, 2, border_radius=12)
        self.text("ΠΑΙΖΕΙΣ ΕΣΥ" if mine else "ΠΑΙΖΕΙ", self.f_bold, col, center=(cx, box.y + 17))
        sub = "διάλεξε όπλο και στόχο"
        if mine and TOUCH and self.aim_cell:
            sub = "πάτα ξανά τον στόχο: ΦΩΤΙΑ!"
        self.text(sub if mine else fit(self.opp_name, self.f_small, box.w - 20),
                  self.f_tiny if mine else self.f_small, TEXT, center=(cx, box.y + 38))
        ay = box.y + 58
        d = 1 if mine else -1
        ox = int(6 * math.sin(t / 150)) * d
        pts = [(cx - 26 * d + ox, ay - 3), (cx + 12 * d + ox, ay - 3), (cx + 12 * d + ox, ay - 7),
               (cx + 26 * d + ox, ay), (cx + 12 * d + ox, ay + 7), (cx + 12 * d + ox, ay + 3), (cx - 26 * d + ox, ay + 3)]
        pygame.draw.polygon(self.screen, col, pts)

        # όπλα
        for k, (w, rect) in enumerate(self.weapon_rects()):
            ok, sub = self.weapon_state(w)
            sel = self.weapon == w
            hover = ok and rect.collidepoint(MOUSE)
            bg = (40, 72, 110) if sel else ((26, 54, 88) if hover else (18, 42, 72))
            if not ok:
                bg = (20, 28, 40)
            pygame.draw.rect(self.screen, bg, rect, border_radius=10)
            pygame.draw.rect(self.screen, ACCENT if sel else PANEL_EDGE, rect, 2 if sel else 1, border_radius=10)
            tc = self.weapon_icon(w, (rect.x + 24, rect.centery), ok)
            self.text(f"{k + 1}  {WEAPON_NAME[w]}", self.f_sb, ACCENT if sel else tc, topleft=(rect.x + 46, rect.y + 5))
            self.text(fit(sub, self.f_tiny, rect.w - 54), self.f_tiny, DIM if ok else (110, 120, 135), topleft=(rect.x + 46, rect.y + 24))

        # σκορ & στατιστικά
        y = GRID_Y + 96 + 4 * 50 + 8
        self.text(f"Βυθισμένα  {len(self.enemy_sunk)} – {len(self.my_sunk_idx)}", self.f_bold, TEXT, center=(cx, y + 8))
        cell = self.aim_cell if TOUCH else self.cell_at(MOUSE, ENEMY_X)
        if cell and self.state == "playing" and self.my_turn:
            self.text(f"Στόχος: {LETTERS[cell[1]]}{cell[0] + 1}", self.f_bold, ACCENT, center=(cx, y + 34))
        else:
            acc = lambda s, h: f"{round(100 * h / s)}%" if s else "–"
            self.text(f"Ευστοχία: εσύ {acc(self.my_shots, self.my_hits)}  •  αντ. {acc(self.opp_shots, self.opp_hits)}",
                      self.f_tiny, DIM, center=(cx, y + 32))
        if TOUCH:
            hint = f"Ήχος: {'ναι' if self.snd.on else 'όχι'} (πάτα για αλλαγή)"
        else:
            hint = f"M: ήχος {'ναι' if self.snd.on else 'όχι'}  •  F11: πλήρης οθόνη"
        self.text(hint, self.f_tiny, DIM, center=self.sound_box.center)

    def draw_fleet_panel(self, x, title, enemy):
        r = self.panel((x, BOTTOM_Y, GRID_PX, BOTTOM_H), title)
        y = r.y + 40
        sunk_idx = {i for i, _ in self.enemy_sunk} if enemy else self.my_sunk_idx
        power_of = {v[0]: k for k, v in POWERS.items()}
        for idx, (kind, name, n) in enumerate(KINDS):
            sunk = idx in sunk_idx
            spr = ship_sprite(kind, 17, True, (110, 80, 80, 255) if sunk else None)
            self.screen.blit(spr, (r.x + 16, y + 2))
            self.text(name, self.f_small, DIM if sunk else TEXT, topleft=(r.x + 108, y))
            if idx in power_of:
                if power_of[idx] == "air":
                    self.screen.blit(plane_sprite(22), (r.x + 233, y - 1))
                else:
                    self.weapon_icon(power_of[idx], (r.x + 244, y + 10), not sunk)
            if enemy:
                label, col = ("ΒΥΘΙΣΤΗΚΕ", BAD) if sunk else ("σε δράση", DIM)
                self.text(label, self.f_tiny, col, topleft=(r.x + 272, y + 2))
            else:
                hits = sum(1 for c in self.placed[idx] if self.incoming.get(c)) if idx < len(self.placed) else 0
                for k in range(n):
                    col = BAD if k < hits else GOOD
                    pygame.draw.rect(self.screen, col, (r.x + 266 + k * 21, y + 4, 15, 13), border_radius=3)
            y += 26

    def draw_chat(self):
        r = self.panel((MID_X, BOTTOM_Y, MID_W, BOTTOM_H), "Chat")
        y = r.y + 36
        for who, text, mine in self.chat[-5:]:
            name = self.f_tiny.render(f"{who}:", True, ACCENT if mine else GOOD)
            self.screen.blit(name, (r.x + 12, y))
            msg = fit(text, self.f_tiny, r.w - 30 - name.get_width())
            self.text(msg, self.f_tiny, TEXT, topleft=(r.x + 16 + name.get_width(), y))
            y += 20
        box = pygame.Rect(r.x + 10, r.bottom - 36, r.w - 20, 28)
        pygame.draw.rect(self.screen, (8, 22, 40), box, border_radius=8)
        pygame.draw.rect(self.screen, ACCENT if self.chat_active else PANEL_EDGE, box, 1, border_radius=8)
        if self.chat_active:
            cursor = "|" if (pygame.time.get_ticks() // 450) % 2 else ""
            shown = self.chat_text
            while shown and self.f_small.size(shown + "|")[0] > box.w - 14:
                shown = shown[1:]
            self.text(shown + cursor, self.f_small, TEXT, topleft=(box.x + 7, box.y + 4))
        else:
            self.text("Πάτα εδώ για μήνυμα" if TOUCH else "Enter = γράψε μήνυμα", self.f_tiny, DIM, center=box.center)

    # ------------------------------------------------ σχεδίαση: οθόνες
    def draw_header(self):
        self.text("ΝΑΥΜΑΧΙΑ", self.f_title, TEXT, center=(W // 2, 34))

    def draw_menu(self):
        s = self.screen
        t = pygame.time.get_ticks() / 1000
        self.text("ΝΑΥΜΑΧΙΑ", self.f_huge, (20, 50, 90), center=(W // 2 + 4, 104))
        self.text("ΝΑΥΜΑΧΙΑ", self.f_huge, TEXT, center=(W // 2, 100))
        self.text("2 παίκτες • αεροπλάνα, σόναρ, ομοβροντίες", self.f, DIM, center=(W // 2, 160))
        self.text("Το όνομά σου (πάτα για αλλαγή):" if TOUCH else "Το όνομά σου:", self.f_small, DIM, center=(W // 2, 205))
        box = self.name_box
        pygame.draw.rect(s, (12, 36, 64), box, border_radius=10)
        pygame.draw.rect(s, ACCENT, box, 2, border_radius=10)
        cursor = "|" if int(t * 2) % 2 else ""
        self.text(self.name + cursor, self.f_big, TEXT, center=box.center)
        self.b_host.draw(s, self.f_bold)
        self.b_join.draw(s, self.f_bold)
        self.b_cpu.draw(s, self.f_bold)
        self.text(f"Η IP σου: {self.my_ip}" + ("" if TOUCH else "   •   F11: πλήρης οθόνη"), self.f_small, DIM, center=(W // 2, 530))
        if self.info:
            self.text(self.info, self.f_small, BAD, center=(W // 2, 560))
        self.draw_sea_scene()

    def draw_join(self):
        s = self.screen
        self.draw_header()
        self.text("Γράψε την IP του άλλου παίκτη:", self.f, TEXT, center=(W // 2, 230))
        box = self.ip_box
        pygame.draw.rect(s, (12, 36, 64), box, border_radius=10)
        pygame.draw.rect(s, ACCENT, box, 2, border_radius=10)
        cursor = "|" if (pygame.time.get_ticks() // 500) % 2 else ""
        self.text(self.ip_text + cursor, self.f_big, TEXT, center=box.center)
        self.b_go.draw(s, self.f_bold, bool(self.ip_text))
        self.b_back.draw(s, self.f_bold)
        self.text("π.χ. 192.168.1.25   (για δοκιμή στον ίδιο υπολογιστή: 127.0.0.1)", self.f_small, DIM, center=(W // 2, 470))
        if self.info:
            self.text(self.info, self.f_small, BAD, center=(W // 2, 505))
        self.draw_sea_scene()

    def draw_waiting(self):
        self.draw_header()
        dots = "." * (1 + (pygame.time.get_ticks() // 400) % 3)
        self.text("Περιμένουμε αντίπαλο" + dots, self.f_title, TEXT, center=(W // 2, 230))
        if self.server and not self.vs_cpu:
            self.text("Πες στον άλλον να πατήσει «Σύνδεση» και να γράψει:", self.f, DIM, center=(W // 2, 300))
            self.text(self.my_ip, self.f_huge, ACCENT, center=(W // 2, 360))
        self.b_menu_c.rect.y = 440
        self.b_menu_c.draw(self.screen, self.f_bold)
        self.draw_sea_scene()

    def draw_placing(self):
        s = self.screen
        self.draw_header()
        self.draw_own_board()
        waiting = self.state == "wait_place"
        cells = None if waiting else self.preview_cells()
        if cells:
            ok = self.can_place(cells)
            kind = KINDS[len(self.placed)][0]
            rmin = min(r for r, _ in cells)
            cmin = min(c for _, c in cells)
            inside = [(r, c) for r, c in cells if 0 <= r < SIZE and 0 <= c < SIZE]
            self.shade_cells(OWN_X, inside, (90, 220, 120, 70) if ok else (240, 80, 70, 90))
            tint = (180, 255, 190, 190) if ok else (255, 130, 120, 170)
            s.set_clip(pygame.Rect(OWN_X, GRID_Y, GRID_PX, GRID_PX))
            s.blit(ship_sprite(kind, CELL, self.horiz, tint), (OWN_X + cmin * CELL, GRID_Y + rmin * CELL))
            s.set_clip(None)

        r = self.panel((MID_X, GRID_Y, MID_W, GRID_PX), "Οδηγίες")
        y = r.y + 46
        for line, col in (("Πάτα στο αριστερό ταμπλό", DIM), ("για να βάλεις το πλοίο.", DIM), ("", DIM),
                          ("Περιστροφή: κουμπί ή R", DIM), ("Τυχαία: κουμπί ή Space", DIM), ("", DIM),
                          ("Ειδικές δυνάμεις:", TEXT),
                          ("✈ Αεροπλανοφόρο: επιδρομή ×2", ACCENT),
                          ("◉ Υποβρύχιο: σόναρ ×2", SONAR),
                          ("✚ Θωρηκτό: ομοβροντία ×1", (255, 150, 60)),
                          ("Αν βυθιστεί το πλοίο,", DIM), ("χάνεις τη δύναμή του!", DIM)):
            self.text(line, self.f_small, col, topleft=(r.x + 16, y))
            y += 22
        dir_txt = "οριζόντια  ↔" if self.horiz else "κάθετη  ↕"
        self.text(f"Κατεύθυνση: {dir_txt}", self.f_bold, ACCENT, center=(r.centerx, r.bottom - 24))

        r = self.panel((ENEMY_X, GRID_Y, GRID_PX, GRID_PX), "Ο στόλος σου")
        y = r.y + 48
        for idx, (kind, name, n) in enumerate(KINDS):
            done = idx < len(self.placed)
            cur = idx == len(self.placed) and not waiting
            row = pygame.Rect(r.x + 10, y - 6, r.w - 20, 60)
            if cur:
                pygame.draw.rect(s, (30, 62, 100), row, border_radius=10)
                pygame.draw.rect(s, ACCENT, row, 2, border_radius=10)
            s.blit(ship_sprite(kind, 26, True, None if (done or cur) else (120, 130, 140, 160)), (r.x + 22, y + 2))
            col = GOOD if done else (ACCENT if cur else DIM)
            self.text(name, self.f_bold, col, topleft=(r.x + 170, y + 2))
            sub = "✓ τοποθετήθηκε" if done else (f"{n} θέσεις  ← τώρα" if cur else f"{n} θέσεις")
            self.text(sub, self.f_tiny, col, topleft=(r.x + 170, y + 26))
            y += 64

        if waiting:
            r = self.panel((ENEMY_X, BOTTOM_Y, GRID_PX, BOTTOM_H))
            dots = "." * (1 + (pygame.time.get_ticks() // 400) % 3)
            self.text("Έτοιμος!", self.f_big, GOOD, center=(r.centerx, r.y + 55))
            self.text(f"{self.opp_name} τοποθετεί τα πλοία{dots}", self.f, DIM, center=(r.centerx, r.y + 105))
        else:
            self.b_random.draw(s, self.f_sb)
            self.b_undo.draw(s, self.f_sb, bool(self.placed))
            self.b_clear.draw(s, self.f_sb, bool(self.placed))
            self.b_rotate.draw(s, self.f_bold, len(self.placed) < len(SHIPS))
            self.b_ready.draw(s, self.f_bold, len(self.placed) == len(SHIPS))
        self.draw_fleet_panel(OWN_X, "Κατάσταση στόλου", enemy=False)
        self.draw_chat()

    def draw_playing(self):
        self.draw_header()
        self.draw_own_board()
        self.draw_enemy_board(reveal=self.enemy_fleet if self.state == "over" else None)
        self.draw_mid_panel()
        self.draw_fleet_panel(OWN_X, "Ο στόλος σου", enemy=False)
        self.draw_fleet_panel(ENEMY_X, "Στόλος αντιπάλου", enemy=True)
        self.draw_chat()
        self.draw_fx()
        self.draw_banner()

    def draw_over(self):
        s = self.screen
        self.draw_playing()
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 140))
        s.blit(shade, (0, 0))
        box = pygame.Rect(W // 2 - 280, 190, 560, 310)
        pygame.draw.rect(s, (12, 30, 55), box, border_radius=20)
        col = GOOD if self.win else BAD
        pygame.draw.rect(s, col, box, 3, border_radius=20)
        self.text("ΝΙΚΗΣΕΣ!" if self.win else "ΗΤΤΑ…", self.f_huge, col, center=(W // 2, 255))
        sub = f"Βύθισες όλο τον στόλο του/της {self.opp_name}" if self.win else f"{self.opp_name} βύθισε τον στόλο σου"
        self.text(fit(sub, self.f, 520), self.f, TEXT, center=(W // 2, 318))
        acc = round(100 * self.my_hits / self.my_shots) if self.my_shots else 0
        self.text(f"Βολές: {self.my_shots}   •   Εύστοχες: {self.my_hits}   •   Ευστοχία: {acc}%", self.f_small, DIM, center=(W // 2, 360))
        self.b_rematch.text = "Περιμένουμε…" if self.rematch_sent else "Ρεβάνς"
        self.b_rematch.draw(s, self.f_bold, not self.rematch_sent)
        self.b_menu.draw(s, self.f_bold)
        self.draw_banner()

    def draw(self):
        self.screen.fill(BG)
        st = self.state
        if st == "menu":
            self.draw_menu()
        elif st == "join":
            self.draw_join()
        elif st == "waiting":
            self.draw_waiting()
        elif st in ("placing", "wait_place"):
            self.draw_placing()
        elif st == "playing":
            self.draw_playing()
        elif st == "over":
            self.draw_over()
        elif st == "disconnected":
            self.draw_header()
            self.text("Η σύνδεση με τον αντίπαλο χάθηκε", self.f_title, BAD, center=(W // 2, 260))
            self.b_menu_c.rect.y = 340
            self.b_menu_c.draw(self.screen, self.f_bold)
            self.draw_sea_scene()

    # ------------------------------------------------ κύριος βρόχος
    def run(self):
        global MOUSE
        while True:
            dt = self.clock.tick(60) / 1000
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.back_to_menu()
                    pygame.quit()
                    sys.exit()
                self.on_event(e)
            MOUSE = self.map_pos(pygame.mouse.get_pos())
            while not self.q.empty():
                self.handle(self.q.get())
            self.update(dt)
            self.draw()
            self.present()


if __name__ == "__main__":
    Game().run()
