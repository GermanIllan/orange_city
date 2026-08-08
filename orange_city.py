#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import random
import sys
import urllib.request
import urllib.parse
from pathlib import Path

import gi

gi.require_foreign("cairo")
import cairo

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gegl
from gi.repository import Gimp
from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import GdkPixbuf


PLUG_IN_PROC = "python-fu-city-generator"
PLUG_IN_BINARY = "generador_ciudad"
LAYER_NAME = "Ciudad Pintada (Pollinations AI)"


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def gegl_to_rgba(color, fallback):
    try:
        rgba = color.get_rgba()
        if len(rgba) >= 4:
            return tuple(clamp(float(channel), 0.0, 1.0) for channel in rgba[:4])
    except Exception:
        pass
    return fallback


def mix(c1, c2, amount):
    return tuple(c1[i] * (1.0 - amount) + c2[i] * amount for i in range(4))


def shade(color, amount):
    target = (1.0, 1.0, 1.0, color[3]) if amount >= 0 else (0.0, 0.0, 0.0, color[3])
    return mix(color, target, abs(amount))


def set_rgba(ctx, color, alpha=None):
    a = color[3] if alpha is None else alpha
    ctx.set_source_rgba(color[0], color[1], color[2], a)


def fetch_pollinations_sky_surface(prompt, width, height, seed):
    """
    Obtiene un fondo de cielo o textura generado por Pollinations.ai (API pública gratuita).
    Retorna una cairo.ImageSurface o None si la red falla o excede el tiempo límite.
    """
    try:
        encoded_prompt = urllib.parse.quote(prompt if prompt else "dramatic sky sunset watercolor")
        seed_val = seed if seed else random.randint(1, 999999)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width={min(width, 1024)}&height={min(height, 1024)}"
            f"&seed={seed_val}&model=turbo&nologo=true"
        )
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "OrangeCity-GIMP-Plugin/1.0 (Pollinations.ai Ecosystem Integration)"
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if resp.status == 200 and "image" in content_type:
                data = resp.read()
                loader = GdkPixbuf.PixbufLoader()
                loader.write(data)
                loader.close()
                pixbuf = loader.get_pixbuf()

                if pixbuf:
                    surface = cairo.ImageSurface(cairo.Format.ARGB32, width, height)
                    ctx = cairo.Context(surface)
                    # Escalar imagen de Pollinations al tamaño total del lienzo de GIMP
                    scale_x = width / float(pixbuf.get_width())
                    scale_y = height / float(pixbuf.get_height())
                    ctx.scale(scale_x, scale_y)
                    Gdk.cairo_set_source_pixbuf(ctx, pixbuf, 0, 0)
                    ctx.paint()
                    return surface
    except Exception as exc:
        print(f"[OrangeCity] Aviso: Fallback procedimental por error de Pollinations API: {exc}")
    return None


def shaky_line(ctx, rng, x1, y1, x2, y2, segments=5, noise=2.0, is_first=False):
    if is_first:
        ctx.move_to(x1, y1)
    for i in range(1, segments + 1):
        t = i / segments
        nx = x1 + (x2 - x1) * t + rng.uniform(-noise, noise)
        ny = y1 + (y2 - y1) * t + rng.uniform(-noise, noise)
        if i == segments:
            nx, ny = x2, y2
        ctx.line_to(nx, ny)


def create_shaky_path(ctx, rng, x, y, w, h, roof_type, noise=2.0):
    ctx.new_path()
    if roof_type == "angled_left":
        shaky_line(ctx, rng, x, y + w * 0.3, x + w, y, max(2, int(w / 20)), noise, True)
        top_y_right = y
    elif roof_type == "angled_right":
        shaky_line(ctx, rng, x, y, x + w, y + w * 0.3, max(2, int(w / 20)), noise, True)
        top_y_right = y + w * 0.3
    else:
        shaky_line(ctx, rng, x, y, x + w, y, max(2, int(w / 20)), noise, True)
        top_y_right = y

    shaky_line(ctx, rng, x + w, top_y_right, x + w, y + h, max(2, int(h / 20)), noise, False)
    shaky_line(ctx, rng, x + w, y + h, x, y + h, max(2, int(w / 20)), noise, False)
    top_y_left = y + w * 0.3 if roof_type == "angled_left" else y
    shaky_line(ctx, rng, x, y + h, x, top_y_left, max(2, int(h / 20)), noise, False)
    ctx.close_path()


def draw_palette_knife_texture(ctx, rng, x, y, w, h, base_color):
    for _ in range(int(w * h / 100)):
        tx = x + rng.uniform(-w * 0.1, w * 0.9)
        ty = y + rng.uniform(0, h)
        tw = rng.uniform(w * 0.2, w * 0.8)
        th = rng.uniform(2, 8)

        shade_amt = rng.uniform(-0.2, 0.2)
        c = shade(base_color, shade_amt)
        set_rgba(ctx, c, rng.uniform(0.4, 0.9))

        ctx.rectangle(tx, ty, tw, th)
        ctx.fill()

        if rng.random() > 0.7:
            edge_c = (0.9, 0.9, 0.9, rng.uniform(0.2, 0.5)) if shade_amt > 0 else (0.1, 0.1, 0.1, rng.uniform(0.2, 0.5))
            set_rgba(ctx, edge_c)
            ctx.rectangle(tx, ty + th - 1, tw, 1)
            ctx.fill()


def draw_building(ctx, rng, x, y, w, h, base_color):
    roof_type = rng.choice(["flat", "flat", "flat", "flat", "angled_left", "angled_right"])
    
    create_shaky_path(ctx, rng, x, y, w, h, roof_type, noise=w * 0.02)
    
    ctx.save()
    ctx.clip_preserve()
    
    set_rgba(ctx, base_color)
    ctx.fill_preserve()
    
    draw_palette_knife_texture(ctx, rng, x, y, w, h, base_color)
    
    brightness = base_color[0] * 0.299 + base_color[1] * 0.587 + base_color[2] * 0.114
    if brightness < 0.4:
        detail_color = (0.95, 0.95, 0.95, rng.uniform(0.7, 0.9))
    elif brightness > 0.6:
        detail_color = (0.05, 0.05, 0.05, rng.uniform(0.7, 0.9))
    else:
        detail_color = rng.choice([
            (0.95, 0.95, 0.95, rng.uniform(0.7, 0.9)),
            (0.05, 0.05, 0.05, rng.uniform(0.7, 0.9))
        ])

    style = rng.choice(["h_lines", "grid", "dots", "v_lines", "dashed"])
    set_rgba(ctx, detail_color)
    ctx.set_line_cap(cairo.LineCap.SQUARE)
    
    pad_x = w * 0.1
    pad_y = h * 0.05
    
    if style == "h_lines":
        ctx.set_line_width(rng.uniform(2.0, 5.0))
        cy = y + pad_y
        while cy < y + h - pad_y:
            if rng.random() > 0.2:
                ctx.move_to(x + pad_x + rng.uniform(-2, 2), cy + rng.uniform(-1, 1))
                ctx.line_to(x + w - pad_x + rng.uniform(-2, 2), cy + rng.uniform(-1, 1))
                ctx.stroke()
            cy += rng.uniform(10, 20)
            
    elif style == "dashed":
        ctx.set_line_width(rng.uniform(2.0, 6.0))
        cy = y + pad_y
        while cy < y + h - pad_y:
            cx = x + pad_x
            while cx < x + w - pad_x:
                dash_len = rng.uniform(8, 20)
                if rng.random() > 0.3:
                    ctx.move_to(cx, cy + rng.uniform(-1, 1))
                    ctx.line_to(cx + dash_len, cy + rng.uniform(-1, 1))
                    ctx.stroke()
                cx += dash_len + rng.uniform(5, 12)
            cy += rng.uniform(10, 20)
            
    elif style == "grid":
        ctx.set_line_width(rng.uniform(1.5, 4.0))
        cy = y + pad_y
        while cy < y + h - pad_y:
            if rng.random() > 0.1:
                ctx.move_to(x + pad_x, cy)
                ctx.line_to(x + w - pad_x, cy)
                ctx.stroke()
            cy += rng.uniform(10, 20)
        cx = x + pad_x
        while cx < x + w - pad_x:
            if rng.random() > 0.1:
                ctx.move_to(cx, y + pad_y)
                ctx.line_to(cx, y + h - pad_y)
                ctx.stroke()
            cx += rng.uniform(10, 20)
            
    elif style == "dots":
        cy = y + pad_y
        while cy < y + h - pad_y:
            cx = x + pad_x
            while cx < x + w - pad_x:
                if rng.random() > 0.2:
                    r = rng.uniform(2.0, 4.0)
                    ctx.arc(cx + rng.uniform(-1, 1), cy + rng.uniform(-1, 1), r, 0, math.tau)
                    ctx.fill()
                cx += rng.uniform(10, 20)
            cy += rng.uniform(10, 20)
            
    elif style == "v_lines":
        ctx.set_line_width(rng.uniform(2.0, 5.0))
        cx = x + pad_x
        while cx < x + w - pad_x:
            if rng.random() > 0.2:
                ctx.move_to(cx + rng.uniform(-1, 1), y + pad_y)
                ctx.line_to(cx + rng.uniform(-1, 1), y + h - pad_y)
                ctx.stroke()
            cx += rng.uniform(10, 20)

    ctx.restore()
    
    set_rgba(ctx, (0.05, 0.05, 0.05, 1.0))
    ctx.set_line_width(rng.uniform(4.0, 10.0))
    ctx.set_line_join(cairo.LineJoin.ROUND)
    ctx.set_line_cap(cairo.LineCap.ROUND)
    
    create_shaky_path(ctx, rng, x, y, w, h, roof_type, noise=w * 0.02)
    ctx.stroke()
    
    if rng.random() > 0.5:
        ctx.set_line_width(rng.uniform(1.0, 3.0))
        set_rgba(ctx, (0.0, 0.0, 0.0, 0.8))
        create_shaky_path(ctx, rng, x, y, w, h, roof_type, noise=w * 0.03)
        ctx.stroke()
        
    if rng.random() > 0.5:
        num_antennas = rng.randint(1, 3)
        set_rgba(ctx, (0.05, 0.05, 0.05, 1.0))
        ctx.set_line_width(rng.uniform(2.0, 4.0))
        for _ in range(num_antennas):
            ax = x + rng.uniform(w * 0.2, w * 0.8)
            ay = y if roof_type not in ["angled_left", "angled_right"] else y + w * 0.15
            ah = rng.uniform(10, 40)
            ctx.move_to(ax, ay)
            ctx.line_to(ax, ay - ah)
            ctx.stroke()


def draw_canvas_texture(ctx, rng, width, height):
    ctx.set_line_width(1.0)
    for y in range(0, height, 4):
        set_rgba(ctx, (1.0, 1.0, 1.0, rng.uniform(0.01, 0.04)))
        ctx.move_to(0, y)
        ctx.line_to(width, y)
        ctx.stroke()
    for x in range(0, width, 4):
        set_rgba(ctx, (0.0, 0.0, 0.0, rng.uniform(0.01, 0.04)))
        ctx.move_to(x, 0)
        ctx.line_to(x, height)
        ctx.stroke()


def render_scene(image, config):
    width = image.get_width()
    height = image.get_height()
    
    c1 = gegl_to_rgba(config.get_property("color1"), (0.9, 0.3, 0.1, 1.0))
    c2 = gegl_to_rgba(config.get_property("color2"), (0.6, 0.6, 0.6, 1.0))
    c3 = gegl_to_rgba(config.get_property("color3"), (0.1, 0.1, 0.1, 1.0))
    seed = config.get_property("semilla")
    
    usar_pollinations = config.get_property("usar_pollinations")
    prompt_pollinations = config.get_property("prompt_pollinations")

    rng = random.Random(seed if seed else None)
    colors = [c1, c2, c3]

    surface = cairo.ImageSurface(cairo.Format.ARGB32, width, height)
    ctx = cairo.Context(surface)
    
    pollinations_sky = None
    if usar_pollinations:
        try:
            Gimp.progress_init("Conectando con Pollinations.ai para generar fondo IA...")
        except Exception:
            pass
        pollinations_sky = fetch_pollinations_sky_surface(prompt_pollinations, width, height, seed)

    ctx.set_operator(cairo.Operator.SOURCE)
    if pollinations_sky:
        ctx.set_source_surface(pollinations_sky, 0, 0)
        ctx.paint()
        # Capa suave oscura de integración para que destaquen las siluetas
        ctx.set_operator(cairo.Operator.OVER)
        set_rgba(ctx, (0.05, 0.05, 0.08, 0.35))
        ctx.paint()
    else:
        set_rgba(ctx, (0.1, 0.1, 0.1, 1.0))
        ctx.paint()
        ctx.set_operator(cairo.Operator.OVER)

    buildings = []
    y_cursor = height * 0.05
    while y_cursor < height * 1.1:
        x_cursor = -width * 0.1
        while x_cursor < width * 1.1:
            w = width * rng.uniform(0.05, 0.15)
            h = height * rng.uniform(0.2, 0.7)
            y = y_cursor + rng.uniform(-height * 0.05, height * 0.05)
            buildings.append((y, x_cursor, w, h))
            x_cursor += w * rng.uniform(0.5, 1.1)
        y_cursor += height * rng.uniform(0.08, 0.15)

    buildings.sort(key=lambda b: b[0] + b[3])

    for y, x, w, h in buildings:
        base_color = rng.choice(colors)
        draw_building(ctx, rng, x, y, w, h, base_color)

    draw_canvas_texture(ctx, rng, width, height)

    surface.flush()
    return surface


class CiudadPintada(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PLUG_IN_PROC]

    def do_create_procedure(self, name):
        if name != PLUG_IN_PROC:
            return None

        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None
        )

        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(
            Gimp.ProcedureSensitivityMask.DRAWABLE | Gimp.ProcedureSensitivityMask.NO_DRAWABLES
        )
        procedure.set_menu_label("Orange City (Pollinations AI)")
        procedure.add_menu_path("<Image>/German Illan Plugins/")
        procedure.set_documentation(
            "Generador de Ciudad Pintada con Pollinations AI",
            "Crea una ciudad con textura de pintura gruesa y fondo generado por Pollinations.ai.",
            name,
        )
        procedure.set_attribution("German Illan", "German Illan & Pollinations.ai", "2026")

        flags = GObject.ParamFlags.READWRITE
        procedure.add_color_argument("color1", "Color 1", "Primer color principal", False, Gegl.Color.new("rgb(230, 75, 25)"), flags)
        procedure.add_color_argument("color2", "Color 2", "Segundo color", False, Gegl.Color.new("rgb(160, 160, 160)"), flags)
        procedure.add_color_argument("color3", "Color 3", "Tercer color de acento", False, Gegl.Color.new("rgb(30, 30, 30)"), flags)
        procedure.add_int_argument("semilla", "Semilla Aleatoria", "0 para azar", 0, 2147483647, 0, flags)

        procedure.add_boolean_argument("usar_pollinations", "Usar Fondo Pollinations IA", "Genera el fondo/cielo con Pollinations.ai", True, flags)
        procedure.add_string_argument("prompt_pollinations", "Prompt Cielo IA", "Descripción para la IA de Pollinations", "dramatic sunset sky watercolor impasto texture", flags)

        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if run_mode == Gimp.RunMode.INTERACTIVE:
            gi.require_version("GimpUi", "3.0")
            from gi.repository import GimpUi

            GimpUi.init(PLUG_IN_BINARY)
            dialog = GimpUi.ProcedureDialog.new(procedure, config, "Ciudad Pintada con Pollinations AI")
            dialog.fill(["color1", "color2", "color3", "semilla", "usar_pollinations", "prompt_pollinations"])

            if not dialog.run():
                dialog.destroy()
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
            dialog.destroy()

        image.undo_group_start()
        try:
            Gimp.progress_init("Generando obra con Pollinations AI...")
            surface = render_scene(image, config)
            layer = Gimp.Layer.new_from_surface(image, LAYER_NAME, surface, 0.0, 1.0)
            
            parent = None
            position = 0
            image.insert_layer(layer, parent, position)
            Gimp.displays_flush()
        except Exception as exc:
            image.undo_group_end()
            error = GLib.Error.new_literal(Gimp.PlugIn.error_quark(), str(exc), 0)
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, error)

        image.undo_group_end()
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


if __name__ == "__main__":
    Gimp.main(CiudadPintada.__gtype__, sys.argv)
