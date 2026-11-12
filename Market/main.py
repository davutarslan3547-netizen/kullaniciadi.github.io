# -*- coding: utf-8 -*-
"""
Bakkal Kasa - Bluetooth barkod okuyucu (HID/klavye modu) + Firebase + Kivy
Yatay ekran, sepet, ürün çıkarma, yeni ürün ekleme.

Firebase yapısı (varsayılan):
  urunler/
     8690000000001: { "ad": "Süt 1L", "fiyat": 32.5 }
Alan adları esnek: ad/isim/name  ve  fiyat/price  de kabul edilir.
Kök seviyede (urunler olmadan) kayıtlıysa o da denenir.
"""
import json
import socket
import ssl
import threading
import urllib.error
import urllib.request

import certifi
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

# ----------------------------------------------------------------- AYARLAR
DB_URL = "https://barkod-7fa6d-default-rtdb.firebaseio.com"
PRODUCTS_NODE = "urunler"
REMOVE_ONCE = True   # True: "ÜRÜN ÇIKAR" tek okutma için geçerli, sonra satışa döner
HTTP_TIMEOUT = 8

# ------------------------------------------------------------------ RENKLER
BG = (0.07, 0.08, 0.11, 1)
PANEL = (0.13, 0.15, 0.20, 1)
ROW = (0.17, 0.19, 0.25, 1)
GREEN = (0.15, 0.65, 0.35, 1)
RED = (0.80, 0.22, 0.22, 1)
BLUE = (0.18, 0.45, 0.85, 1)
GRAY = (0.30, 0.33, 0.40, 1)
ORANGE = (0.90, 0.55, 0.10, 1)
WHITE = (1, 1, 1, 1)
MUTED = (0.70, 0.74, 0.80, 1)

SSL_CTX = ssl.create_default_context(cafile=certifi.where())


# ------------------------------------------------------------ YARDIMCILAR
def tl(x):
    """1234.5 -> '1.234,50 TL'"""
    s = "{:,.2f}".format(x)
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s + " TL"


def safe_key(code):
    for ch in ".$#[]/":
        code = code.replace(ch, "_")
    return code.strip()


def http(method, path, data=None):
    url = "{}/{}.json".format(DB_URL, path)
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=SSL_CTX) as r:
        txt = r.read().decode("utf-8")
    return json.loads(txt) if txt else None


def err_text(e):
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403):
            return "Firebase hatası"
        return "Sunucu hatası ({})".format(e.code)
    if isinstance(e, (urllib.error.URLError, socket.timeout, TimeoutError, OSError)):
        return "İnternet bağlantısı yok"
    return "Hata: {}".format(e)


def to_float(v):
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace(",", ".").strip())


def parse_product(raw):
    if not isinstance(raw, dict):
        return None
    ad = None
    for k in ("ad", "isim", "name", "urun", "urun_adi"):
        if raw.get(k):
            ad = str(raw[k])
            break
    fiyat = None
    for k in ("fiyat", "price", "tutar"):
        if raw.get(k) is not None:
            try:
                fiyat = to_float(raw[k])
            except ValueError:
                pass
            break
    if ad is None or fiyat is None:
        return None
    return {"ad": ad, "fiyat": fiyat}


def fetch_product(code):
    key = safe_key(code)
    for path in ("{}/{}".format(PRODUCTS_NODE, key), key):
        p = parse_product(http("GET", path))
        if p:
            return p
    return None


# --------------------------------------------------------------- WIDGETLAR
class Panel(BoxLayout):
    def __init__(self, bg=PANEL, radius=10, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*bg)
            self._r = RoundedRectangle(pos=self.pos, size=self.size,
                                       radius=[dp(radius)])
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size


class L(Label):
    def __init__(self, halign="left", **kw):
        kw.setdefault("color", WHITE)
        super().__init__(halign=halign, valign="middle", **kw)
        self.bind(size=lambda *a: setattr(self, "text_size", self.size))


def btn(text, color, **kw):
    kw.setdefault("font_size", sp(16))
    return Button(text=text, background_normal="", background_down="",
                  background_color=color, color=WHITE, bold=True, **kw)


# ------------------------------------------------------------- UYGULAMA
class BakkalApp(App):
    title = ""

    def build(self):
        Window.clearcolor = BG
        Window.softinput_mode = "below_target"

        self.cart = {}        # barkod -> {ad, fiyat, adet}
        self.products = {}    # önbellek
        self.remove_mode = False
        self.popup = None
        self._status_ev = None
        self._reset_ev = None
        self._reset_armed = False

        root = BoxLayout(orientation="horizontal", padding=dp(8), spacing=dp(8))

        # ---------------- SOL: tarama + sepet
        left = BoxLayout(orientation="vertical", spacing=dp(6))

        self.scan = TextInput(
            hint_text="Barkodu okut", multiline=False, write_tab=False,
            input_type="null", keyboard_suggestions=False,
            font_size=sp(22), size_hint_y=None, height=dp(52),
            padding=[dp(12), dp(12)],
            background_color=(0.2, 0.23, 0.3, 1), foreground_color=WHITE,
            hint_text_color=MUTED, cursor_color=WHITE)
        self.scan.bind(on_text_validate=self.on_scan)
        left.add_widget(self.scan)

        self.status = L(text="", font_size=sp(16), color=MUTED,
                        size_hint_y=None, height=dp(30))
        left.add_widget(self.status)

        cart_panel = Panel(orientation="vertical", padding=dp(6))
        self.list = GridLayout(cols=1, size_hint_y=None, spacing=dp(5))
        self.list.bind(minimum_height=self.list.setter("height"))
        sv = ScrollView(do_scroll_x=False)
        sv.add_widget(self.list)
        cart_panel.add_widget(sv)
        left.add_widget(cart_panel)

        # ---------------- SAĞ: toplam + butonlar
        right = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_x=0.36)

        total_panel = Panel(orientation="vertical", padding=dp(10), size_hint_y=0.42)
        total_panel.add_widget(L(text="TOPLAM", font_size=sp(16), color=MUTED))
        self.total_lbl = L(text=tl(0), font_size=sp(40), bold=True, halign="right")
        total_panel.add_widget(self.total_lbl)
        self.count_lbl = L(text="0 çeşit / 0 adet", font_size=sp(15),
                           color=MUTED, halign="right")
        total_panel.add_widget(self.count_lbl)
        right.add_widget(total_panel)

        self.mode_btn = btn("ürün ekleme modu", GREEN,
                            font_size=sp(16))
        self.mode_btn.bind(on_release=self.toggle_mode)
        right.add_widget(self.mode_btn)

        self.reset_btn = btn("sepeti sil", RED)
        self.reset_btn.bind(on_release=self.reset_cart)
        right.add_widget(self.reset_btn)

        b_new = btn("yeni ürün", BLUE)
        b_new.bind(on_release=lambda *_: self.open_new_product())
        right.add_widget(b_new)

        b_sync = btn("firebasi yenile", GRAY, font_size=sp(14),
                     size_hint_y=None, height=dp(40))
        b_sync.bind(on_release=lambda *_: self.load_all())
        right.add_widget(b_sync)

        root.add_widget(left)
        root.add_widget(right)

        self.refresh_cart()
        Clock.schedule_interval(self.keep_focus, 0.4)
        Clock.schedule_once(lambda dt: self.load_all(), 0.5)
        return root

    def on_pause(self):
        return True

    # ------------------------------------------------------------ ODAK
    def keep_focus(self, dt):
        if self.popup is None and not self.scan.focus:
            self.scan.focus = True

    def refocus(self):
        Clock.schedule_once(lambda dt: setattr(self.scan, "focus", True), 0)

    # ----------------------------------------------------------- DURUM
    def say(self, text, color=MUTED, secs=4):
        self.status.text = text
        self.status.color = color
        if self._status_ev:
            self._status_ev.cancel()
        if secs:
            self._status_ev = Clock.schedule_once(
                lambda dt: self.say("", MUTED, 0), secs)

    # ------------------------------------------------------ VERİ YÜKLE
    def load_all(self):
        self.say("ürünler geliyor", ORANGE, 0)
        threading.Thread(target=self._load_all, daemon=True).start()

    def _load_all(self):
        try:
            raw = http("GET", PRODUCTS_NODE)
            found = {}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    p = parse_product(v)
                    if p:
                        found[str(k)] = p
            Clock.schedule_once(lambda dt: self._loaded(found), 0)
        except Exception as e:
            msg = err_text(e)
            Clock.schedule_once(
                lambda dt: self.say("internet yok " + msg, RED, 6), 0)

    def _loaded(self, found):
        self.products.update(found)
        self.say("{} ürün yüklendi".format(len(found)), GREEN)

    # ------------------------------------------------------------ TARAMA
    def on_scan(self, inst):
        code = inst.text.strip()
        inst.text = ""
        self.refocus()
        if not code:
            return

        if self.remove_mode:
            self.remove_one(code)
            if REMOVE_ONCE:
                self.set_mode(False)
            return

        cached = self.products.get(safe_key(code))
        if cached:
            self.add_to_cart(code, cached)
            return

        self.say("Aranıyor: " + code, ORANGE, 0)
        threading.Thread(target=self._lookup, args=(code,), daemon=True).start()

    def _lookup(self, code):
        try:
            p = fetch_product(code)
        except Exception as e:
            msg = err_text(e)
            Clock.schedule_once(lambda dt: self.say(msg, RED, 6), 0)
            return
        if p is None:
            Clock.schedule_once(
                lambda dt: self.say(
                    "ürün bulamadım " + code + "  yeni ürün ekle",
                    RED, 7), 0)
            return

        def ok(dt):
            self.products[safe_key(code)] = p
            self.add_to_cart(code, p)
        Clock.schedule_once(ok, 0)

    # ------------------------------------------------------------ SEPET
    def add_to_cart(self, code, p):
        key = safe_key(code)
        if key in self.cart:
            self.cart[key]["adet"] += 1
        else:
            self.cart[key] = {"ad": p["ad"], "fiyat": p["fiyat"], "adet": 1}
        self.refresh_cart()
        self.say("+ {}  ({})".format(p["ad"], tl(p["fiyat"])), GREEN, 3)

    def remove_one(self, code):
        key = safe_key(code)
        it = self.cart.get(key)
        if not it:
            self.say("bu ürünü eklemmeişsin " + code, RED, 5)
            return
        name = it["ad"]
        self.change(key, -1)
        self.say("- {}ı çıkardım".format(name), ORANGE, 3)

    def change(self, key, delta):
        it = self.cart.get(key)
        if not it:
            return
        it["adet"] += delta
        if it["adet"] <= 0:
            del self.cart[key]
        self.refresh_cart()

    def delete_line(self, key):
        self.cart.pop(key, None)
        self.refresh_cart()

    def refresh_cart(self):
        self.list.clear_widgets()
        total = 0.0
        pieces = 0
        if not self.cart:
            e = L(text="Sepet boş - barkod okutun", halign="center",
                  color=MUTED, font_size=sp(18), size_hint_y=None, height=dp(80))
            self.list.add_widget(e)
        for key in reversed(list(self.cart.keys())):   # yeni ürün üstte
            it = self.cart[key]
            line = it["fiyat"] * it["adet"]
            total += line
            pieces += it["adet"]

            row = Panel(bg=ROW, radius=8, orientation="horizontal",
                        size_hint_y=None, height=dp(58),
                        padding=[dp(8), dp(4)], spacing=dp(4))
            name = L(text=it["ad"], font_size=sp(17), size_hint_x=0.34)
            unit = L(text=tl(it["fiyat"]), font_size=sp(13), color=MUTED,
                     size_hint_x=0.17, halign="right")
            b_minus = btn("-", RED, size_hint_x=None, width=dp(42),
                          font_size=sp(22))
            b_minus.bind(on_release=lambda *_, k=key: self.change(k, -1))
            qty = L(text=str(it["adet"]), font_size=sp(20), bold=True,
                    halign="center", size_hint_x=None, width=dp(40))
            b_plus = btn("+", GREEN, size_hint_x=None, width=dp(42),
                         font_size=sp(22))
            b_plus.bind(on_release=lambda *_, k=key: self.change(k, 1))
            tot = L(text=tl(line), font_size=sp(17), bold=True,
                    size_hint_x=0.22, halign="right")
            b_del = btn("X", GRAY, size_hint_x=None, width=dp(36))
            b_del.bind(on_release=lambda *_, k=key: self.delete_line(k))

            for w in (name, unit, b_minus, qty, b_plus, tot, b_del):
                row.add_widget(w)
            self.list.add_widget(row)

        self.total_lbl.text = tl(total)
        self.count_lbl.text = "{} çeşit / {} adet".format(len(self.cart), pieces)

    # ------------------------------------------------------ BUTONLAR
    def set_mode(self, remove):
        self.remove_mode = remove
        if remove:
            self.mode_btn.text = "sepetten çıkar"
            self.mode_btn.background_color = RED
            self.say("çıkarcağın ürünü okut", ORANGE, 0)
        else:
            self.mode_btn.text = "ürün ekleme modu"
            self.mode_btn.background_color = GREEN
        self.refocus()

    def toggle_mode(self, *_):
        self.set_mode(not self.remove_mode)

    def reset_cart(self, *_):
        if not self._reset_armed:
            self._reset_armed = True
            self.reset_btn.text = "eminsin mi"
            self.reset_btn.background_color = ORANGE
            self._reset_ev = Clock.schedule_once(self._disarm_reset, 3)
            return
        self._disarm_reset()
        self.cart.clear()
        self.refresh_cart()
        self.say("sepeti sıfırladım", GREEN)
        self.refocus()

    def _disarm_reset(self, *_):
        if self._reset_ev:
            self._reset_ev.cancel()
            self._reset_ev = None
        self._reset_armed = False
        self.reset_btn.text = "SEPETİ SIFIRLA"
        self.reset_btn.background_color = RED

    # ------------------------------------------------- YENİ ÜRÜN FORMU
    def open_new_product(self):
        if self.popup is not None:
            return
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))

        def field(hint, **kw):
            return TextInput(hint_text=hint, multiline=False, write_tab=False,
                             font_size=sp(20), size_hint_y=None, height=dp(48),
                             padding=[dp(10), dp(10)], **kw)

        f_code = field("barkod okut")
        f_name = field("Ürün adı")
        f_price = field("Fiyat", input_filter=None)
        msg = L(text="Barkodu okut",
                color=MUTED, font_size=sp(14), size_hint_y=None, height=dp(28))

        f_code.bind(on_text_validate=lambda *_: setattr(f_name, "focus", True))
        f_name.bind(on_text_validate=lambda *_: setattr(f_price, "focus", True))

        for w in (f_code, f_name, f_price, msg):
            content.add_widget(w)

        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(50))
        b_cancel = btn("vazgeç", GRAY)
        b_save = btn("KAYDET", GREEN)
        row.add_widget(b_cancel)
        row.add_widget(b_save)
        content.add_widget(row)

        self.popup = Popup(title="Yeni Ürün / Güncelle", content=content,
                           size_hint=(0.85, 0.8), auto_dismiss=False)
        self.popup.bind(on_dismiss=self._popup_closed)

        def save(*_):
            code = safe_key(f_code.text)
            name = f_name.text.strip()
            if not code or not name or not f_price.text.strip():
                msg.text = "gir şu barkodu ve ismi ya"
                msg.color = RED
                return
            try:
                price = to_float(f_price.text)
                if price < 0:
                    raise ValueError
            except ValueError:
                msg.text = "gir şu fiyatı"
                msg.color = RED
                return
            msg.text = "Kaydediyom"
            msg.color = ORANGE
            b_save.disabled = True
            threading.Thread(target=self._save_product,
                             args=(code, name, price, msg, b_save),
                             daemon=True).start()

        f_price.bind(on_text_validate=save)
        b_save.bind(on_release=save)
        b_cancel.bind(on_release=lambda *_: self.popup.dismiss())
        self.popup.open()
        Clock.schedule_once(lambda dt: setattr(f_code, "focus", True), 0.2)

    def _save_product(self, code, name, price, msg, b_save):
        data = {"ad": name, "fiyat": price}
        try:
            http("PUT", "{}/{}".format(PRODUCTS_NODE, code), data)
        except Exception as e:
            err = err_text(e)

            def fail(dt):
                msg.text = "Kaydemedim: " + err
                msg.color = RED
                b_save.disabled = False
            Clock.schedule_once(fail, 0)
            return

        def ok(dt):
            self.products[code] = {"ad": name, "fiyat": price}
            if code in self.cart:   # sepetteki fiyatı da güncelle
                self.cart[code]["ad"] = name
                self.cart[code]["fiyat"] = price
                self.refresh_cart()
            if self.popup:
                self.popup.dismiss()
            self.say("Kaydettim: {} - {}".format(name, tl(price)), GREEN, 5)
        Clock.schedule_once(ok, 0)

    def _popup_closed(self, *_):
        self.popup = None
        self.refocus()


if __name__ == "__main__":
    BakkalApp().run()
