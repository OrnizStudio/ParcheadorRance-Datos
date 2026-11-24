"""Pruebas de la fase A de canales: roles por archivo, `canales/<canal>/` y JSON estricto.

Uso:  python -m unittest discover -s robot/pruebas
"""
import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from unittest import mock

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "robot"))
import canales  # noqa: E402
from canales import JsonMalo, leer_json_estricto, leer_miembros, error_de_texto  # noqa: E402
import permisos as robot  # noqa: E402
from permisos import (Cambio, Canales, Permisos, Rol, RUTA_CATALOGO, comprobar, leer_canales,  # noqa: E402
                      permisos_de)

DUENO_ID, PROP_ID, ADMIN_ID, EDITOR_ID, COLAB_ID, INVITADO_ID, NUEVO_ID, VETADO_ID = 1, 10, 20, 30, 40, 50, 60, 70
M = "canales/ornizen/miembros.json"
C = "canales/ornizen/canal.json"
L = "canales/ornizen/lista-negra.json"

MIEMBROS = {"esquema": 1, "miembros": [
    {"id": PROP_ID, "cuenta": "prop", "rol": "propietario", "estado": "activo", "desde": "2026-11-21"},
    {"id": ADMIN_ID, "cuenta": "admin", "rol": "administrador", "estado": "activo"},
    {"id": EDITOR_ID, "cuenta": "editor", "rol": "editor", "estado": "activo", "etiquetas": ["traductora"]},
    {"id": COLAB_ID, "cuenta": "colab", "rol": "colaborador", "estado": "activo"},
    {"id": INVITADO_ID, "cuenta": "invitada", "rol": "editor", "estado": "invitado", "invitadoPor": ADMIN_ID},
]}
CANAL = {"esquema": 1, "id": "ornizen", "nombre": "Ornizen", "descripcion": "Canal oficial.",
         "contacto": {"issues": True}, "paquetes": ["OrnizStudio/ParcheadorRance-Datos"], "adultos": True,
         "normasAceptadas": 0, "creado": "2026-11-21", "estado": "activo", "oculto": False,
         "verificacion": {"verificado": True, "desde": "2026-11-21", "motivo": "Canal oficial.",
                          "historial": [{"fecha": "2026-11-21", "accion": "verificar", "motivo": "Canal oficial.", "por": DUENO_ID}]}}
LISTA = {"esquema": 1, "archivos": [{"patron": "*.sig", "motivo": "Firmas"}], "huellas": [],
         "usuarios": [{"id": VETADO_ID, "cuenta": "spammer", "motivo": "Abusos"}]}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 100
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
CUENTAS = {PROP_ID: "prop", ADMIN_ID: "admin", EDITOR_ID: "editor", COLAB_ID: "colab", INVITADO_ID: "invitada",
           NUEVO_ID: "nueva", NUEVO_ID + 1: "prop2", VETADO_ID: "spammer", DUENO_ID: "0rnizL"}
CATALOGO = {"esquema": 1, "versionCatalogo": 1, "etiquetas": [], "juegos": []}


def b(objeto) -> bytes:
    return json.dumps(objeto, ensure_ascii=False).encode()


def rol_de(cuenta_id):
    return Rol(canales.rol_en_canal(leer_miembros(MIEMBROS, M)[0], cuenta_id))


def permisos(cuenta_id):
    if cuenta_id == DUENO_ID:
        return Permisos(Rol.DUENO, cuenta_id=DUENO_ID)
    rol = rol_de(cuenta_id)
    return Permisos(rol, por_canal={"ornizen": rol} if rol else {}, cuenta_id=cuenta_id)


def proponer(cuenta_id, archivos: dict, antes: dict | None = None, modos=None, extra=(), cuentas=None, estados=None, cuenta_de=None, rol_externo=None):
    """`archivos` = {ruta: objeto o bytes o None (borrar)}; `antes` = lo que hay en `main` (por defecto, lo de siempre)."""
    main = {M: b(MIEMBROS), C: b(CANAL), L: b(LISTA)}
    if antes is not None:
        main.update({k: (v if isinstance(v, bytes) or v is None else b(v)) for k, v in antes.items()})
    despues = dict(main)
    cambios = []
    for ruta, valor in archivos.items():
        datos = None if valor is None else valor if isinstance(valor, bytes) else b(valor)
        estado = (estados or {}).get(ruta) or ("D" if datos is None else "A" if main.get(ruta) is None else "M")
        despues[ruta] = datos
        cambios.append(Cambio(ruta, estado, (modos or {}).get(ruta, "000000" if datos is None else "100644"), len(datos or b"")))
    cambios += list(extra)

    def leer(ruta, lado):
        return (main if lado == "antes" else despues).get(ruta)
    nombres = CUENTAS if cuentas is None else cuentas
    return comprobar(cambios, json.dumps(CATALOGO), json.dumps(CATALOGO), permisos(cuenta_id), leer_archivo=leer,
                     ids_duenos=frozenset({DUENO_ID}), cuenta_de=cuenta_de or nombres.get, rol_externo=rol_externo)


def miembros(cambiar):
    nuevo = copy.deepcopy(MIEMBROS)
    cambiar(nuevo["miembros"])
    return nuevo


def fila(lista, cuenta_id):
    return next(m for m in lista if m["id"] == cuenta_id)


def invitar(cuenta_id=NUEVO_ID, rol="editor", estado="invitado", por=ADMIN_ID, cuenta="nueva"):
    nuevo = {"id": cuenta_id, "cuenta": cuenta, "rol": rol, "estado": estado}
    if por is not None:
        nuevo["invitadoPor"] = por
    return lambda lista: lista.append(dict(nuevo))


class JsonEstricto(unittest.TestCase):
    def malo(self, datos, contiene, tope=None):
        with self.assertRaises(JsonMalo) as error:
            leer_json_estricto(datos, "x.json", tope)
        self.assertIn(contiene, str(error.exception))

    def test_lee_un_json_normal(self):
        self.assertEqual({"a": [1, "ñ"]}, leer_json_estricto('{"a": [1, "ñ"]}'.encode(), "x.json"))

    def test_rechaza_bom_utf8_roto_y_claves_repetidas(self):
        self.malo(b"\xef\xbb\xbf{}", "BOM")
        self.malo(b'{"a": "\xff"}', "UTF-8")
        self.malo(b'{"a": 1, "a": 2}', "repetida")

    def test_rechaza_nan_e_infinito(self):
        for texto in (b'{"a": NaN}', b'{"a": Infinity}', b'{"a": -Infinity}'):
            with self.subTest(texto=texto):
                self.malo(texto, "no es un número")

    def test_rechaza_lo_anidado_sin_tumbar_a_python(self):
        self.malo(b"[" * 33 + b"]" * 33, "niveles")
        self.malo(b"[" * 200000, "niveles")
        self.assertEqual([[1]], leer_json_estricto(b"[[1]]", "x.json"))
        # Los corchetes dentro de una cadena no cuentan.
        self.assertEqual({"a": "[[[[" * 20}, leer_json_estricto(json.dumps({"a": "[[[[" * 20}).encode(), "x.json"))

    def test_dice_la_linea_y_el_tope(self):
        self.malo(b'{\n"a": 1,\n"b" 2}', "línea 3")
        self.malo(b"{}" + b" " * 100, "pesa", tope=50)


class Textos(unittest.TestCase):
    def test_nombres_validos(self):
        for nombre in ("Ornizen", "Rance Traducciones", "ランス翻訳", "Équipe Ñandú", "Grupo 2 🎮"):
            with self.subTest(nombre=nombre):
                self.assertIsNone(error_de_texto(nombre, 60, 1))

    def test_nombres_que_engañan(self):
        casos = {
            "Orniz​en": "invisible",            # espacio de anchura cero
            "Orniz‮en": "invisible",            # cambio de dirección
            "Оrnizen": "mezcla alfabetos",           # la О es cirílica
            "Ornizen ": "espacios",
            "Ornizén": "NFC",             # é descompuesta
            "a" * 61: "máximo es 60",
            "": "vacío",
            "Uno\nDos": "saltos de línea",
            "Ctrl\x07": "control",
        }
        for nombre, contiene in casos.items():
            with self.subTest(nombre=nombre):
                self.assertIn(contiene, error_de_texto(nombre, 60, 1) or "")

    def test_las_marcas_que_se_combinan_no_cuentan_como_letra(self):
        texto = "á" * 60  # no es NFC, pero el largo visible es 60
        self.assertEqual(60, canales.largo_visible(texto))


class MiembrosFormato(unittest.TestCase):
    def errores(self, objeto):
        return leer_miembros(objeto, M)[1]

    def test_el_archivo_de_las_pruebas_vale(self):
        self.assertEqual([], self.errores(MIEMBROS))

    def test_campos_y_tipos(self):
        casos = [
            (lambda m: m[0].update(id="10"), "`id`"),
            (lambda m: m[0].update(id=True), "`id`"),
            (lambda m: m[0].update(id=-1), "`id`"),
            (lambda m: m[1].update(rol="dueño"), "`rol`"),
            (lambda m: m[1].update(estado="pendiente"), "`estado`"),
            (lambda m: m[1].update(cuenta="con espacio"), "`cuenta`"),
            (lambda m: m[1].update(desde="21/11/2026"), "`desde`"),
            (lambda m: m[1].update(desde="2026-02-30"), "`desde`"),
            (lambda m: m[1].update(secreto="x"), "`secreto` no existe"),
            (lambda m: m[2].update(etiquetas=["a"] * 2), "`etiquetas`"),
            (lambda m: m[2].update(etiquetas=[str(i) for i in range(6)]), "`etiquetas`"),
            (lambda m: m[2].update(etiquetas=["x" * 25]), "`etiquetas`"),
            (lambda m: m[2].update(etiquetas=[""]), "`etiquetas`"),
            (lambda m: m.append(dict(m[1])), "repetida"),
            (lambda m: m[0].update(estado="invitado"), "sin ningún Propietario activo"),
        ]
        for cambiar, contiene in casos:
            with self.subTest(contiene=contiene):
                self.assertTrue(any(contiene in e for e in self.errores(miembros(cambiar))), self.errores(miembros(cambiar)))

    def test_el_nombre_de_cuenta_no_tiene_que_ser_unico(self):
        # Una cuenta se renombra y otra se queda con su nombre viejo: lo que cuenta es el id.
        self.assertEqual([], self.errores(miembros(lambda m: m.append(dict(m[1], id=999, cuenta="ADMIN")))))

    def test_topes_de_miembros_e_invitaciones(self):
        def muchos(n, estado):
            return lambda m: m.extend({"id": 1000 + i, "cuenta": f"c{i}", "rol": "colaborador", "estado": estado}
                                      for i in range(n))
        self.assertEqual([], self.errores(miembros(muchos(500 - 4, "activo"))))
        self.assertIn("máximo son 500", self.errores(miembros(muchos(500 - 3, "activo")))[0])
        self.assertIn("máximo son 100", self.errores(miembros(muchos(100, "invitado")))[0])

    def test_no_es_un_objeto(self):
        for objeto in ([], "x", None, {"esquema": 1}, {"esquema": 2, "miembros": []}):
            with self.subTest(objeto=objeto):
                self.assertTrue(self.errores(objeto))


class GestionDeMiembros(unittest.TestCase):
    def test_un_administrador_invita_por_debajo_de_su_rol(self):
        self.assertEqual([], proponer(ADMIN_ID, {M: miembros(invitar(rol="editor"))}))
        self.assertEqual([], proponer(ADMIN_ID, {M: miembros(invitar(rol="colaborador"))}))
        self.assertIn("por debajo de tu rol", proponer(ADMIN_ID, {M: miembros(invitar(rol="administrador"))})[0])

    def test_nadie_invita_como_propietario_ni_como_activo(self):
        self.assertIn("como Propietario", proponer(PROP_ID, {M: miembros(invitar(rol="propietario", por=PROP_ID))})[0])
        self.assertIn("entrar como `invitado`", proponer(ADMIN_ID, {M: miembros(invitar(estado="activo"))})[0])

    def test_invitado_por_tiene_que_ser_quien_invita(self):
        self.assertIn("`invitadoPor` tiene que ser tu cuenta", proponer(ADMIN_ID, {M: miembros(invitar(por=PROP_ID))})[0])
        self.assertIn("`invitadoPor` tiene que ser tu cuenta", proponer(ADMIN_ID, {M: miembros(invitar(por=None))})[-1])

    def test_editores_y_colaboradores_no_gestionan_gente(self):
        for quien in (EDITOR_ID, COLAB_ID):
            with self.subTest(quien=quien):
                self.assertIn("cosa de un Administrador", proponer(quien, {M: miembros(invitar(por=quien))})[0])
                self.assertIn("cosa de un Administrador",
                              proponer(quien, {M: miembros(lambda m: m.remove(fila(m, COLAB_ID if quien != COLAB_ID else EDITOR_ID)))})[0])

    def test_un_administrador_no_toca_a_otro_administrador_ni_al_propietario(self):
        otro_admin = invitar(cuenta_id=NUEVO_ID, rol="administrador", estado="activo", por=PROP_ID)
        otro_prop = invitar(cuenta_id=NUEVO_ID + 1, rol="propietario", estado="activo", por=PROP_ID, cuenta="prop2")
        antes = miembros(lambda m: (otro_admin(m), otro_prop(m)))

        def quitar(cuenta_id):
            nuevo = copy.deepcopy(antes)
            nuevo["miembros"].remove(fila(nuevo["miembros"], cuenta_id))
            return nuevo
        self.assertIn("no puedes cambiar ni quitar", proponer(ADMIN_ID, {M: quitar(NUEVO_ID)}, antes={M: antes})[0])
        self.assertIn("no puedes cambiar ni quitar", proponer(ADMIN_ID, {M: quitar(PROP_ID)}, antes={M: antes})[0])
        self.assertEqual([], proponer(ADMIN_ID, {M: quitar(EDITOR_ID)}, antes={M: antes}))
        self.assertEqual([], proponer(PROP_ID, {M: quitar(NUEVO_ID)}, antes={M: antes}))

    def test_ascender(self):
        self.assertIn("no puedes dar", proponer(ADMIN_ID, {M: miembros(lambda m: fila(m, EDITOR_ID).update(rol="administrador"))})[0])
        self.assertEqual([], proponer(ADMIN_ID, {M: miembros(lambda m: fila(m, EDITOR_ID).update(rol="colaborador"))}))
        self.assertEqual([], proponer(PROP_ID, {M: miembros(lambda m: fila(m, EDITOR_ID).update(rol="propietario"))}))
        self.assertIn("sobre un miembro activo",
                      proponer(PROP_ID, {M: miembros(lambda m: fila(m, INVITADO_ID).update(rol="propietario"))})[0])

    def test_aceptar_la_propia_invitacion(self):
        aceptar = miembros(lambda m: fila(m, INVITADO_ID).update(estado="activo"))
        self.assertEqual([], proponer(INVITADO_ID, {M: aceptar}))
        # Nadie la acepta por otro, ni el Propietario del canal.
        self.assertIn("solo `invitada` puede aceptar", proponer(PROP_ID, {M: aceptar})[0])

    def test_aceptar_y_cambiarse_algo_a_la_vez_no(self):
        for cambio in ({"rol": "administrador"}, {"etiquetas": ["jefa"]}, {"invitadoPor": PROP_ID}):
            with self.subTest(cambio=cambio):
                nuevo = miembros(lambda m: fila(m, INVITADO_ID).update(estado="activo", **cambio))
                self.assertIn("tu propia fila", proponer(INVITADO_ID, {M: nuevo})[0])

    def test_un_invitado_solo_puede_aceptar(self):
        aceptar = miembros(lambda m: fila(m, INVITADO_ID).update(estado="activo"))
        motivos = proponer(INVITADO_ID, {M: aceptar, RUTA_CATALOGO: CATALOGO})
        self.assertIn("ningún rol", motivos[0])
        # Ni invitar a otra persona aprovechando la propuesta.
        otro = miembros(lambda m: (fila(m, INVITADO_ID).update(estado="activo"), invitar(por=INVITADO_ID)(m)))
        self.assertIn("cosa de un Administrador", proponer(INVITADO_ID, {M: otro})[0])

    def test_añadirse_a_si_mismo_no(self):
        for rol in ("colaborador", "propietario"):
            with self.subTest(rol=rol):
                nuevo = miembros(invitar(cuenta_id=NUEVO_ID, rol=rol, estado="activo", por=NUEVO_ID))
                self.assertIn("tu propia fila", proponer(NUEVO_ID, {M: nuevo})[0])
        self.assertIn("tu propia fila", proponer(EDITOR_ID, {M: miembros(lambda m: fila(m, EDITOR_ID).update(rol="administrador"))})[0])

    def test_salir_del_canal(self):
        self.assertEqual([], proponer(COLAB_ID, {M: miembros(lambda m: m.remove(fila(m, COLAB_ID)))}))
        self.assertEqual([], proponer(INVITADO_ID, {M: miembros(lambda m: m.remove(fila(m, INVITADO_ID)))}))
        self.assertIn("sin ningún Propietario activo", proponer(PROP_ID, {M: miembros(lambda m: m.remove(fila(m, PROP_ID)))})[0])

    def test_alguien_de_fuera_no_toca_nada(self):
        self.assertIn("cosa de un Administrador", proponer(NUEVO_ID, {M: miembros(lambda m: m.remove(fila(m, COLAB_ID)))})[0])

    def test_lista_negra_del_canal(self):
        motivos = proponer(ADMIN_ID, {M: miembros(invitar(cuenta_id=VETADO_ID, cuenta="spammer"))})
        self.assertIn("lista negra del canal", motivos[0])
        # Banear = quitar de miembros y añadir a la lista en la misma propuesta.
        lista = copy.deepcopy(LISTA)
        lista["usuarios"].append({"id": COLAB_ID, "cuenta": "colab", "motivo": "Spam", "por": ADMIN_ID})
        self.assertEqual([], proponer(ADMIN_ID, {M: miembros(lambda m: m.remove(fila(m, COLAB_ID))), L: lista}))
        self.assertIn("lista negra del canal", proponer(ADMIN_ID, {L: lista, M: miembros(lambda m: None)})[0])

    def test_el_dueno_puede_todo_salvo_el_formato(self):
        self.assertEqual([], proponer(DUENO_ID, {M: miembros(invitar(rol="propietario", estado="activo", por=DUENO_ID))}))
        self.assertIn("sin ningún Propietario activo",
                      proponer(DUENO_ID, {M: miembros(lambda m: m.remove(fila(m, PROP_ID)))})[0])

    def test_json_dañado_es_un_rechazo_con_el_archivo(self):
        for datos, contiene in ((b"{", "no es un JSON válido"), (b'{"esquema": 1, "esquema": 1}', "repetida"),
                                (b"[" * 5000, "niveles"), (b" " * (130 * 1024), "pesa")):
            with self.subTest(contiene=contiene):
                motivos = proponer(ADMIN_ID, {M: datos})
                self.assertIn(contiene, motivos[0])
                self.assertIn(M, motivos[0])


class CanalJson(unittest.TestCase):
    def canal(self, **cambios):
        nuevo = copy.deepcopy(CANAL)
        nuevo.update(cambios)
        return nuevo

    def test_quien_cambia_cada_campo(self):
        casos = [("nombre", "Ornizen Oficial", ADMIN_ID), ("descripcion", "Otra", ADMIN_ID), ("adultos", False, ADMIN_ID),
                 ("paquetes", ["OrnizStudio/Ornizen-Parches"], PROP_ID), ("estado", "retirado", PROP_ID),
                 ("normasAceptadas", 3, PROP_ID), ("oculto", True, DUENO_ID), ("estado", "bloqueado", DUENO_ID),
                 ("verificacion", {"verificado": False}, DUENO_ID), ("creado", "2020-01-01", DUENO_ID)]
        orden = [EDITOR_ID, ADMIN_ID, PROP_ID, DUENO_ID]
        for campo, valor, minimo in casos:
            for quien in orden:
                with self.subTest(campo=campo, quien=quien):
                    motivos = proponer(quien, {C: self.canal(**{campo: valor})})
                    if orden.index(quien) >= orden.index(minimo):
                        self.assertEqual([], motivos)
                    else:
                        self.assertTrue(motivos)

    def test_formato(self):
        casos = [({"id": "otro"}, "nombre de su carpeta"), ({"nombre": "Оrnizen"}, "mezcla alfabetos"),
                 ({"nombre": "x" * 61}, "máximo es 60"), ({"descripcion": "x" * 301}, "máximo es 300"),
                 ({"descripcion": "a\nb\nc\nd\ne"}, "saltos"), ({"secreto": 1}, "no existe"),
                 ({"paquetes": ["a/b", "c/d", "e/f", "g/h"]}, "`paquetes`"), ({"paquetes": ["no es repo"]}, "`paquetes`"),
                 ({"contacto": {"web": "http://x"}}, "https"), ({"contacto": {"enlaces": [{"tipo": "x", "url": "https://x"}] * 9}}, "enlaces"),
                 ({"contacto": {"correo": "sin-arroba"}}, "correo"), ({"logo": "../logo.png"}, "`logo`"),
                 ({"logo": "logo.exe"}, "`logo`"), ({"estado": "pendiente"}, "`estado`"), ({"adultos": "sí"}, "`adultos`")]
        for cambios, contiene in casos:
            with self.subTest(cambios=cambios):
                motivos = proponer(DUENO_ID, {C: self.canal(**cambios)})
                self.assertTrue(any(contiene in m for m in motivos), motivos)

    def test_crear_o_borrar_un_canal_solo_el_dueno(self):
        self.assertIn("No eres miembro de @nuevo", proponer(ADMIN_ID, {"canales/nuevo/canal.json": self.canal(id="nuevo")})[0])
        self.assertIn("solo lo hace el Dueño", proponer(PROP_ID, {C: None})[0])
        self.assertEqual([], proponer(DUENO_ID, {"canales/nuevo/canal.json": self.canal(id="nuevo")}))


class RutasYTopes(unittest.TestCase):
    def test_un_canal_por_propuesta(self):
        motivos = proponer(ADMIN_ID, {C: dict(CANAL, nombre="Otro"), "canales/otro/canal.json": dict(CANAL, id="otro")})
        self.assertIn("varios canales", motivos[0])

    def test_rutas_raras(self):
        for ruta, contiene in (("canales/ornizen/Logo.png", "minúsculas"), ("canales/ornizen/a b.png", "minúsculas"),
                               ("canales/ornizen/../normas/x.json", "`..`"), ("canales/Ornizen/canal.json", "minúsculas"),
                               ("canales/ab/canal.json", "no puede ser el @"), ("canales/ornizen/notas.txt", "solo van")):
            with self.subTest(ruta=ruta):
                self.assertIn(contiene, proponer(ADMIN_ID, {ruta: b"x"})[0])

    def test_la_carpeta_de_canales_con_mayusculas(self):
        self.assertIn("en minúsculas", proponer(ADMIN_ID, {}, extra=[Cambio("Canales/ornizen/miembros.json", "A")])[0])

    def test_logo(self):
        self.assertEqual([], proponer(ADMIN_ID, {"canales/ornizen/logo.webp": WEBP}))
        self.assertEqual([], proponer(ADMIN_ID, {"canales/ornizen/logo.png": PNG}))
        self.assertEqual([], proponer(ADMIN_ID, {"canales/ornizen/logo.jpg": JPEG, "canales/ornizen/otro.jpeg": JPEG}))
        self.assertIn("máximo son 512 KB", proponer(ADMIN_ID, {"canales/ornizen/logo.webp": WEBP + b"x" * (513 * 1024)})[0])
        self.assertIn("lo cambia un Administrador", proponer(EDITOR_ID, {"canales/ornizen/logo.webp": WEBP})[0])

    def test_un_logo_tiene_que_ser_una_imagen_de_verdad(self):
        for datos, contiene in ((b"x" * 1000, "de verdad"), (b"<svg onload=alert(1)>", "de verdad"), (b"", "de verdad"),
                                (b"RIFF\x00\x00\x00\x00AVI ", "de verdad"), (b"MZ\x90\x00", "de verdad"),
                                (PNG, "por dentro es PNG")):
            with self.subTest(contiene=contiene, datos=datos[:8]):
                self.assertIn(contiene, proponer(ADMIN_ID, {"canales/ornizen/logo.webp": datos})[0])
        # Borrar el logo no necesita mirar nada.
        self.assertEqual([], proponer(ADMIN_ID, {"canales/ornizen/logo.png": None}, antes={"canales/ornizen/logo.png": PNG}))

    def test_propuestas_enormes(self):
        muchos = [Cambio(f"catalogo/juegos/j/{i}.png", "A", "100644", 10) for i in range(301)]
        self.assertTrue(any("máximo son 300" in m for m in proponer(ADMIN_ID, {}, extra=muchos)))
        grande = [Cambio(f"catalogo/juegos/j/{i}.png", "A", "100644", 5 * 1024 * 1024) for i in range(5)]
        self.assertTrue(any("MB y el máximo son 20 MB" in m for m in proponer(ADMIN_ID, {}, extra=grande)))
        self.assertTrue(any("ejecutables" in m for m in proponer(ADMIN_ID, {}, extra=[Cambio("catalogo/juegos/j/a.png", "A", "100755", 10)])))
        self.assertIn("solo valen archivos normales", proponer(ADMIN_ID, {"canales/ornizen/logo.png": PNG},
                                                                modos={"canales/ornizen/logo.png": "100755"})[0])
        self.assertEqual([], [m for m in proponer(DUENO_ID, {}, extra=muchos) if "máximo son 300" in m])


class ListaNegraDelCanal(unittest.TestCase):
    def lista(self, cambiar):
        nuevo = copy.deepcopy(LISTA)
        cambiar(nuevo)
        return nuevo

    def test_quien_añade_y_quien_quita(self):
        añadir = self.lista(lambda l: l["archivos"].append({"patron": "*.exe", "motivo": "Ejecutables"}))
        quitar_archivo = self.lista(lambda l: l["archivos"].clear())
        quitar_usuario = self.lista(lambda l: l["usuarios"].clear())
        self.assertEqual([], proponer(ADMIN_ID, {L: añadir}))
        # El veto de `spammer` no dice quién lo puso: cuenta como de un Administrador; otro Administrador no lo deshace.
        self.assertIn("no puedes quitar ni cambiar el veto", proponer(ADMIN_ID, {L: quitar_usuario})[0])
        self.assertEqual([], proponer(PROP_ID, {L: quitar_usuario}))
        self.assertIn("es del Propietario del canal", proponer(ADMIN_ID, {L: quitar_archivo})[0])
        self.assertEqual([], proponer(PROP_ID, {L: quitar_archivo}))
        self.assertIn("la cambia un Administrador", proponer(EDITOR_ID, {L: añadir})[0])

    def vetar(self, cuenta_id, por, cuenta=None):
        fila = {"id": cuenta_id, "motivo": "Abusos", "por": por}
        if cuenta:
            fila["cuenta"] = cuenta
        return self.lista(lambda l: l["usuarios"].append(fila))

    def test_solo_se_veta_por_debajo_del_rol_propio(self):
        # Un Administrador no veta al Propietario, a otro Administrador ni al Dueño (dejaría `miembros.json` congelado).
        otro_admin = miembros(invitar(cuenta_id=NUEVO_ID, rol="administrador", estado="activo", por=PROP_ID))
        for victima in (PROP_ID, NUEVO_ID):
            with self.subTest(victima=victima):
                self.assertIn("por debajo de tu rol", proponer(ADMIN_ID, {L: self.vetar(victima, ADMIN_ID)}, antes={M: otro_admin})[0])
        self.assertEqual([], proponer(ADMIN_ID, {L: self.vetar(EDITOR_ID, ADMIN_ID), M: miembros(lambda m: m.remove(fila(m, EDITOR_ID)))}))
        self.assertEqual([], proponer(ADMIN_ID, {L: self.vetar(999, ADMIN_ID)}))  # alguien de fuera
        # Un Propietario tampoco veta a otro Propietario; el Dueño, a cualquiera menos a sí mismo.
        dos = miembros(invitar(cuenta_id=NUEVO_ID + 1, rol="propietario", estado="activo", por=PROP_ID, cuenta="prop2"))
        self.assertIn("por debajo de tu rol", proponer(PROP_ID, {L: self.vetar(NUEVO_ID + 1, PROP_ID)}, antes={M: dos})[0])
        sin_prop2 = copy.deepcopy(dos)
        sin_prop2["miembros"].remove(fila(sin_prop2["miembros"], NUEVO_ID + 1))
        self.assertEqual([], proponer(DUENO_ID, {L: self.vetar(NUEVO_ID + 1, DUENO_ID), M: sin_prop2}, antes={M: dos}))

    def test_el_dueno_no_se_puede_vetar_nunca(self):
        for quien in (ADMIN_ID, PROP_ID, DUENO_ID):
            with self.subTest(quien=quien):
                motivos = proponer(quien, {L: self.vetar(DUENO_ID, quien)})
                self.assertTrue(any("Dueño del programa y no se puede vetar" in m for m in motivos), motivos)

    def test_por_tiene_que_ser_quien_veta(self):
        self.assertIn("`por` tiene que ser tu cuenta", proponer(ADMIN_ID, {L: self.vetar(999, PROP_ID)})[0])
        sin_por = self.lista(lambda l: l["usuarios"].append({"id": 999, "motivo": "x"}))
        self.assertIn("`por` tiene que ser tu cuenta", proponer(ADMIN_ID, {L: sin_por})[0])

    def test_cada_uno_quita_solo_los_vetos_de_quien_esta_por_debajo(self):
        def con(por):
            return self.vetar(999, por)
        sin = self.lista(lambda l: None)
        otro_admin = miembros(invitar(cuenta_id=NUEVO_ID, rol="administrador", estado="activo", por=PROP_ID))
        # El suyo, sí; el de otro Administrador o el de un Propietario, no.
        self.assertEqual([], proponer(ADMIN_ID, {L: sin}, antes={L: con(ADMIN_ID)}))
        self.assertIn("no puedes quitar ni cambiar", proponer(ADMIN_ID, {L: sin}, antes={L: con(NUEVO_ID), M: otro_admin})[0])
        self.assertIn("no puedes quitar ni cambiar", proponer(ADMIN_ID, {L: sin}, antes={L: con(PROP_ID)})[0])
        # Un Propietario deshace el de un Administrador, pero no el del Dueño; el Dueño, todos.
        self.assertEqual([], proponer(PROP_ID, {L: sin}, antes={L: con(ADMIN_ID)}))
        self.assertIn("no puedes quitar ni cambiar", proponer(PROP_ID, {L: sin}, antes={L: con(DUENO_ID)})[0])
        self.assertEqual([], proponer(DUENO_ID, {L: sin}, antes={L: con(PROP_ID)}))
        # Cambiar el motivo de un veto ajeno es como quitarlo y volverlo a poner.
        otro_motivo = self.lista(lambda l: l["usuarios"].append({"id": 999, "motivo": "Otro", "por": ADMIN_ID}))
        self.assertIn("no puedes quitar ni cambiar", proponer(ADMIN_ID, {L: otro_motivo}, antes={L: con(PROP_ID)})[0])

    def test_el_nombre_del_vetado_es_el_de_su_cuenta(self):
        self.assertIn("se llama `colab` en GitHub", proponer(ADMIN_ID, {L: self.vetar(COLAB_ID, ADMIN_ID, cuenta="otra"),
                                                                       M: miembros(lambda m: m.remove(fila(m, COLAB_ID)))})[0])

    def test_formato(self):
        for cambiar, contiene in ((lambda l: l["huellas"].append({"hash": "md5:1", "motivo": "x"}), "`hash`"),
                                  (lambda l: l["archivos"].append({"patron": "*.dll"}), "texto"),
                                  (lambda l: l["usuarios"].append({"id": "x", "motivo": "x"}), "`id`"),
                                  (lambda l: l.update(otros=[]), "no existe")):
            with self.subTest(contiene=contiene):
                self.assertTrue(any(contiene in m for m in proponer(PROP_ID, {L: self.lista(cambiar)})))

    def test_sus_archivos_cuentan_en_los_parches_del_catalogo(self):
        juego = {"id": "j", "ediciones": [{"id": "e", "huella": [], "huellasParcheadas": [
            {"version": "1", "archivos": [{"ruta": "datos/firma.SIG", "tamano": 1, "hashParcial": "blake3:" + "a" * 64, "hash": "blake3:" + "a" * 64}]}]}]}
        despues = dict(CATALOGO, versionCatalogo=2, juegos=[juego])

        def leer(ruta, lado):
            return b(LISTA) if ruta == L else None
        motivos = comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(CATALOGO), json.dumps(despues),
                            Permisos(Rol.ADMINISTRADOR), leer_archivo=leer)
        self.assertEqual(1, len(motivos))
        self.assertIn("del canal @ornizen", motivos[0])
        self.assertIn("lista-negra.json", motivos[0])


class Seguridad(unittest.TestCase):
    """Lo que sale de la revisión de seguridad del PR de la fase A."""

    def test_en_canales_solo_archivos_normales_tambien_sin_rol(self):
        aceptar = miembros(lambda m: fila(m, INVITADO_ID).update(estado="activo"))
        for modo, estado in (("120000", "T"), ("120000", "A"), ("160000", "M"), ("100755", "M")):
            for quien in (INVITADO_ID, NUEVO_ID, ADMIN_ID, DUENO_ID):
                with self.subTest(modo=modo, estado=estado, quien=quien):
                    motivos = proponer(quien, {M: aceptar}, modos={M: modo}, estados={M: estado})
                    self.assertTrue(motivos)
                    self.assertTrue(any("solo valen archivos normales" in m or "ningún rol" in m for m in motivos), motivos)
        # Un cambio de tipo (T) aunque diga 100644.
        self.assertIn("solo valen archivos normales", proponer(INVITADO_ID, {M: aceptar}, estados={M: "T"})[0])

    def test_json_con_numeros_enormes_o_infinitos_es_un_rechazo_y_no_una_caida(self):
        for datos in (b'{"esquema": 1, "miembros": [], "x": ' + b"9" * 5000 + b"}", b'{"esquema": 1e999}',
                      b'{"esquema": -1e999}', b'{"a": ' + b"1" * 31 + b"}"):
            with self.subTest(datos=datos[:30]):
                with self.assertRaises(JsonMalo):
                    leer_json_estricto(datos, "x.json")
                self.assertTrue(proponer(ADMIN_ID, {M: datos}))
        self.assertEqual({"a": 1.5, "b": 10 ** 20}, leer_json_estricto(b'{"a": 1.5, "b": 100000000000000000000}', "x.json"))

    def test_un_archivo_de_main_ilegible_no_se_juzga_como_si_no_existiera(self):
        roto = b'{"esquema": 1, "esquema": 1}'
        self.assertIn("de `main` no se puede leer", proponer(ADMIN_ID, {C: dict(CANAL, nombre="Otro")}, antes={C: roto})[0])
        self.assertIn("de `main` no se puede leer", proponer(PROP_ID, {L: LISTA}, antes={L: roto})[0])
        self.assertIn("de `main` no se puede leer", proponer(ADMIN_ID, {M: miembros(invitar())}, antes={L: roto})[0])
        # El Dueño sí lo puede arreglar.
        self.assertEqual([], proponer(DUENO_ID, {C: CANAL}, antes={C: roto}))

    def test_un_propietario_no_toca_a_otro_propietario_pero_puede_irse(self):
        dos = miembros(invitar(cuenta_id=NUEVO_ID + 1, rol="propietario", estado="activo", por=PROP_ID, cuenta="prop2"))

        def cambiar(quien, como):
            nuevo = copy.deepcopy(dos)
            como(nuevo["miembros"], fila(nuevo["miembros"], quien))
            return nuevo
        degradar = cambiar(NUEVO_ID + 1, lambda m, f: f.update(rol="administrador"))
        quitar = cambiar(NUEVO_ID + 1, lambda m, f: m.remove(f))
        irse = cambiar(PROP_ID, lambda m, f: m.remove(f))
        for propuesta in (degradar, quitar):
            self.assertIn("no puedes cambiar ni quitar", proponer(PROP_ID, {M: propuesta}, antes={M: dos})[0])
            self.assertEqual([], proponer(DUENO_ID, {M: propuesta}, antes={M: dos}))
        self.assertEqual([], proponer(PROP_ID, {M: irse}, antes={M: dos}))
        # Ascender a otro a Propietario sí; y siempre queda al menos uno.
        self.assertEqual([], proponer(PROP_ID, {M: miembros(lambda m: fila(m, ADMIN_ID).update(rol="propietario"))}))
        self.assertIn("sin ningún Propietario activo", proponer(DUENO_ID, {M: miembros(lambda m: m.remove(fila(m, PROP_ID)))})[0])

    def test_el_nombre_va_con_su_id(self):
        # Al invitar no se puede poner el nombre de otra persona junto al id.
        self.assertIn("se llama `nueva` en GitHub", proponer(ADMIN_ID, {M: miembros(invitar(cuenta="admin"))})[0])
        self.assertIn("no existe en GitHub", proponer(ADMIN_ID, {M: miembros(invitar(cuenta_id=123456))})[0])
        # Tampoco el Dueño (es una regla de formato).
        self.assertIn("se llama", proponer(DUENO_ID, {M: miembros(invitar(cuenta="otra", por=DUENO_ID))})[0])

    def test_cada_uno_corrige_su_propio_nombre_tras_renombrarse(self):
        renombrada = {**CUENTAS, EDITOR_ID: "editora-nueva"}
        nuevo = miembros(lambda m: fila(m, EDITOR_ID).update(cuenta="editora-nueva"))
        self.assertEqual([], proponer(EDITOR_ID, {M: nuevo}, cuentas=renombrada))
        # …pero no a un nombre que no es el suyo, ni de paso el rol.
        self.assertIn("se llama `editor`", proponer(EDITOR_ID, {M: nuevo})[0])
        con_rol = miembros(lambda m: fila(m, EDITOR_ID).update(cuenta="editora-nueva", rol="administrador"))
        self.assertIn("tu propia fila", proponer(EDITOR_ID, {M: con_rol}, cuentas=renombrada)[0])
        # Y un invitado puede aceptar y corregirse el nombre a la vez.
        aceptar = miembros(lambda m: fila(m, INVITADO_ID).update(estado="activo", cuenta="invitada-2"))
        self.assertEqual([], proponer(INVITADO_ID, {M: aceptar}, cuentas={**CUENTAS, INVITADO_ID: "invitada-2"}))

    def test_el_catalogo_pide_rol_en_el_canal_oficial(self):
        # Un rol en otro canal no da nada fuera de `canales/`.
        solo_otro = Permisos(Rol.NINGUNO, por_canal={"otro_canal": Rol.PROPIETARIO}, cuenta_id=ADMIN_ID)
        self.assertIn("ningún rol", comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(CATALOGO), json.dumps(CATALOGO), solo_otro)[0])
        self.assertIn("ningún rol", comprobar([Cambio("catalogo/juegos/j/a.png", "A", "100644", 10)], None, None, solo_otro)[0])

    def test_falta_el_id_de_quien_sube_el_ultimo_cambio(self):
        api = mock.Mock(return_value={"head": {"sha": "a" * 40}, "base": {"ref": "main"}, "user": {"login": "admin", "id": ADMIN_ID}})
        entorno = {"GITHUB_REPOSITORY": "a/b", "PR_NUMERO": "1", "GITHUB_TOKEN": "t", "PR_ACTOR": "admin", "PR_CABEZA": "a" * 40}
        with mock.patch.dict(os.environ, entorno, clear=True), mock.patch.object(robot, "crear_api", return_value=api), \
                mock.patch.object(sys, "argv", ["permisos.py"]):
            with self.assertRaises(RuntimeError) as error:
                robot.main()
        self.assertIn("PR_ACTOR_ID", str(error.exception))


class RolesDesdeMain(unittest.TestCase):
    """`permisos_de`: el rol sale del archivo por id y, en la transición, del equipo de GitHub."""

    def setUp(self):
        self.canales = Canales({"ornizen": leer_miembros(MIEMBROS, M)[0]}, {"ornizen": {VETADO_ID}})

    def de(self, login, cuenta_id, nivel=None, ids=frozenset({DUENO_ID}), propietarios=frozenset()):
        api = lambda metodo, ruta, tolerar=(): {"role_name": nivel} if nivel else None  # noqa: E731
        return permisos_de(login, api, {}, propietarios, cuenta_id, self.canales, ids)

    def test_por_id_aunque_la_cuenta_se_haya_renombrado(self):
        self.assertEqual(Rol.EDITOR, self.de("editor-con-nombre-nuevo", EDITOR_ID).rol_global)
        self.assertEqual(Rol.NINGUNO, self.de("editor", 999).rol_global)  # el nombre viejo, otra persona

    def test_una_invitacion_no_da_nada(self):
        self.assertEqual(Rol.NINGUNO, self.de("invitada", INVITADO_ID).rol_global)

    def test_transicion_el_mayor_entre_archivo_y_equipo(self):
        self.assertEqual(Rol.ADMINISTRADOR, self.de("colab", COLAB_ID, "admin").rol_global)
        self.assertEqual(Rol.ADMINISTRADOR, self.de("admin", ADMIN_ID, "triage").rol_global)
        self.assertEqual(Rol.EDITOR, self.de("fuera", 999, "write").rol_global)

    def test_la_lista_negra_del_canal_gana_al_equipo(self):
        permisos = self.de("spammer", VETADO_ID, "admin")
        self.assertEqual(Rol.NINGUNO, permisos.rol_global)
        self.assertEqual({}, permisos.por_canal)

    def test_dueno_por_id(self):
        self.assertTrue(self.de("cualquiera", DUENO_ID, "write").es_dueno)
        self.assertFalse(self.de("0rnizl", 999, "admin", propietarios={"0rnizl"}).es_dueno)
        # Sin ids en el archivo, como antes: cuenta en la lista y admin del repositorio.
        self.assertTrue(self.de("0rnizL", 999, "admin", ids=frozenset(), propietarios={"0rnizl"}).es_dueno)
        self.assertFalse(self.de("0rnizL", 999, "write", ids=frozenset(), propietarios={"0rnizl"}).es_dueno)

    def test_bots_y_cuentas_vacias(self):
        self.assertEqual(Rol.NINGUNO, self.de("dependabot[bot]", PROP_ID, "admin").rol_global)
        self.assertEqual(Rol.NINGUNO, self.de("", PROP_ID).rol_global)

    def test_el_menor_quita_la_cuenta_si_son_dos_personas(self):
        uno, otro = self.de("prop", PROP_ID), self.de("admin", ADMIN_ID)
        menor = uno.el_menor(otro)
        self.assertEqual(Rol.ADMINISTRADOR, menor.rol_global)
        self.assertIsNone(menor.cuenta_id)
        self.assertEqual(PROP_ID, uno.el_menor(uno).cuenta_id)
        # Un invitado no puede aceptar con el último cambio subido por otra cuenta.
        aceptar = miembros(lambda m: fila(m, INVITADO_ID).update(estado="activo"))
        sin_cuenta = Permisos(Rol.NINGUNO)
        self.assertIn("ningún rol", comprobar([Cambio(M, "M")], None, None, sin_cuenta,
                                              leer_archivo=lambda r, l: b(aceptar if l == "despues" else MIEMBROS))[0])


class ArchivosDelRepositorio(unittest.TestCase):
    """Los archivos de verdad de `main` se leen bien (si no, el robot fallaría con todas las propuestas)."""

    def test_canales_y_dueno(self):
        leidos = leer_canales(RAIZ)
        self.assertIn("ornizen", leidos.miembros)
        ids, _ = canales.leer_duenos((RAIZ / "normas/propietario.json").read_text(encoding="utf-8"))
        self.assertTrue(ids)
        for cuenta_id in ids:
            self.assertEqual(Rol.PROPIETARIO, leidos.rol("ornizen", cuenta_id))
        for nombre in ("canal.json", "lista-negra.json"):
            ruta = f"canales/ornizen/{nombre}"
            objeto = leer_json_estricto((RAIZ / ruta).read_bytes(), ruta)
            errores = (canales.validar_canal(objeto, "ornizen", ruta) if nombre == "canal.json"
                       else canales.leer_lista_negra(objeto, ruta)[1])
            self.assertEqual([], errores)

    def test_un_enlace_simbolico_en_main_cuenta_como_roto(self):
        with tempfile.TemporaryDirectory() as carpeta:
            canal = pathlib.Path(carpeta, "canales", "x_y")
            canal.mkdir(parents=True)
            fuera = pathlib.Path(carpeta, "fuera.json")
            fuera.write_bytes(b(MIEMBROS))
            try:
                os.symlink(fuera, canal / "miembros.json")
            except (OSError, NotImplementedError):
                self.skipTest("este sistema no deja crear enlaces simbólicos")
            with self.assertRaises(ValueError):
                leer_canales(pathlib.Path(carpeta))

    def test_las_reglas_se_leen_de_main_con_git(self):
        """`leer_canales(revision=…)` y `archivo_de_git`: modo, tamaño y contenido salen de git, no de la copia."""
        import subprocess
        with tempfile.TemporaryDirectory() as carpeta:
            def g(*a):
                return subprocess.run(["git", "-C", carpeta, *a], capture_output=True, check=True)
            g("init", "-q")
            g("config", "user.email", "robot@example.invalid")
            g("config", "user.name", "robot")
            canal = pathlib.Path(carpeta, "canales", "ornizen")
            canal.mkdir(parents=True)
            (canal / "miembros.json").write_bytes(b(MIEMBROS))
            (canal / "lista-negra.json").write_bytes(b(LISTA))
            g("add", ".")
            g("commit", "-qm", "uno")
            actual = os.getcwd()
            os.chdir(carpeta)
            try:
                leidos = leer_canales(revision="HEAD")
                self.assertEqual(Rol.PROPIETARIO, leidos.rol("ornizen", PROP_ID))
                self.assertEqual(Rol.NINGUNO, leidos.rol("ornizen", VETADO_ID))
                # En la copia de trabajo se cambia, pero lo que vale es el commit.
                (canal / "miembros.json").write_bytes(b"{")
                self.assertEqual(Rol.PROPIETARIO, leer_canales(revision="HEAD").rol("ornizen", PROP_ID))
                self.assertIsNone(robot.archivo_de_git("HEAD", "normas/no-existe.json", 10))
                with self.assertRaises(ValueError):
                    robot.archivo_de_git("HEAD", "canales/ornizen/miembros.json", 10)  # pasa del tope
                # Un enlace simbólico guardado en git (modo 120000) no se sigue.
                enlace = subprocess.run(["git", "-C", carpeta, "hash-object", "-w", "--stdin"], input=b"../../fuera.json",
                                        capture_output=True, check=True).stdout.decode().strip()
                g("update-index", "--add", "--cacheinfo", f"120000,{enlace},canales/ornizen/miembros.json")
                g("commit", "-qm", "enlace")
                with self.assertRaises(ValueError):
                    leer_canales(revision="HEAD")
            finally:
                os.chdir(actual)

    def test_un_miembros_json_dañado_en_main_para_al_robot(self):
        with tempfile.TemporaryDirectory() as carpeta:
            canal = pathlib.Path(carpeta, "canales", "x_y")
            canal.mkdir(parents=True)
            (canal / "miembros.json").write_bytes(b'{"esquema": 1, "miembros": [{"id": 1}]}')
            with self.assertRaises(ValueError):
                leer_canales(pathlib.Path(carpeta))


# Formato que escribe el parcheador (Equipo, `EscritorCatalogo.Escribir`). La misma cadena está en
# tests/Parcheador.Equipo.Tests/MiembrosTests.cs del repositorio del programa: si una cambia, la otra también.
FORMATO_APP = (
    '{\n'
    '  "esquema": 1,\n'
    '  "miembros": [\n'
    '    { "id": 101, "cuenta": "ana-trad", "rol": "propietario", "estado": "activo" },\n'
    '    {\n'
    '      "id": 201,\n'
    '      "cuenta": "pepe",\n'
    '      "rol": "editor",\n'
    '      "estado": "activo",\n'
    '      "invitadoPor": 101,\n'
    '      "etiquetas": ["traductora", "revisora"]\n'
    '    }\n'
    '  ]\n'
    '}\n')


def indentado(objeto) -> bytes:
    return (json.dumps(objeto, ensure_ascii=False, indent=2) + "\n").encode()


class SegundaRevision(unittest.TestCase):
    """Segunda revisión de seguridad de la fase A (cada prueba, un hallazgo)."""

    # ── 2. La cabeza del evento y quién cuenta ──
    def test_la_cabeza_es_la_del_evento(self):
        sha = "b" * 40
        self.assertEqual(sha, robot.cabeza_del_evento({"head": {"sha": sha}}, {"PR_CABEZA": sha}))
        with self.assertRaises(RuntimeError) as error:
            robot.cabeza_del_evento({"head": {"sha": "c" * 40}}, {"PR_CABEZA": sha})
        self.assertIn("ha cambiado", str(error.exception))
        for malo in ("", "x", "b" * 39, None):
            with self.subTest(malo=malo), self.assertRaises(RuntimeError):
                robot.cabeza_del_evento({"head": {"sha": sha}}, {"PR_CABEZA": malo} if malo is not None else {})

    def test_relanzar_un_evento_viejo_con_un_commit_nuevo_no_publica(self):
        api = mock.Mock(return_value={"head": {"sha": "c" * 40}, "base": {"ref": "main"},
                                      "user": {"login": "0rnizL", "id": DUENO_ID}})
        entorno = {"GITHUB_REPOSITORY": "a/b", "PR_NUMERO": "1", "GITHUB_TOKEN": "t", "PR_ACTOR": "0rnizL",
                   "PR_ACTOR_ID": str(DUENO_ID), "PR_CABEZA": "b" * 40, "PR_DISPARADOR": "0rnizL"}
        with mock.patch.dict(os.environ, entorno, clear=True), mock.patch.object(robot, "crear_api", return_value=api), \
                mock.patch.object(sys, "argv", ["permisos.py", "--fusionar"]):
            with self.assertRaises(RuntimeError) as error:
                robot.main()
        self.assertIn("ha cambiado", str(error.exception))
        self.assertEqual(1, api.call_count)  # solo ha leído la propuesta: ni comenta ni fusiona

    def test_cuenta_tambien_quien_relanza(self):
        ids = {"admin": ADMIN_ID, "editor": EDITOR_ID}.get
        base = {"PR_ACTOR": "admin", "PR_ACTOR_ID": str(ADMIN_ID)}
        self.assertEqual([("admin", ADMIN_ID)],
                         robot.cuentas_de_la_ejecucion({**base, "PR_DISPARADOR": "Admin"}, "admin", ADMIN_ID, ids))
        self.assertEqual([("admin", ADMIN_ID), ("editor", EDITOR_ID)],
                         robot.cuentas_de_la_ejecucion({**base, "PR_DISPARADOR": "editor"}, "admin", ADMIN_ID, ids))
        with self.assertRaises(RuntimeError):
            robot.cuentas_de_la_ejecucion({**base, "PR_DISPARADOR": "nadie"}, "admin", ADMIN_ID, ids)
        with self.assertRaises(RuntimeError):
            robot.cuentas_de_la_ejecucion({"PR_ACTOR": "admin"}, "admin", ADMIN_ID, ids)
        # Mismo nombre, otra cuenta: cuentan las dos.
        self.assertEqual(2, len(robot.cuentas_de_la_ejecucion({"PR_ACTOR": "admin", "PR_ACTOR_ID": "999"},
                                                               "admin", ADMIN_ID, ids)))

    def test_el_rol_mas_bajo_y_el_dueno_no_rompe_la_cuenta(self):
        dueno, admin, editor = permisos(DUENO_ID), permisos(ADMIN_ID), permisos(EDITOR_ID)
        self.assertEqual(Rol.EDITOR, robot.combinar([admin, editor]).rol_global)
        self.assertIsNone(robot.combinar([admin, editor]).cuenta_id)
        self.assertEqual(admin, robot.combinar([admin, dueno]))  # el Dueño relanza la de otro: sigue siendo la del otro
        self.assertEqual(admin, robot.combinar([dueno, admin]))
        self.assertTrue(robot.combinar([dueno]).es_dueno)

    # ── 3. Cambiar la base de la propuesta ──
    def test_cambiar_la_base_vuelve_a_lanzar_el_robot_y_solo_vale_main(self):
        flujo = (RAIZ / ".github/workflows/permisos.yml").read_text(encoding="utf-8")
        self.assertRegex(flujo, r"types: \[[^\]]*\bedited\b")
        self.assertEqual(2, flujo.count("PR_CABEZA: ${{ github.event.pull_request.head.sha }}"))
        self.assertEqual(2, flujo.count("PR_DISPARADOR: ${{ github.triggering_actor }}"))
        self.assertIsNone(robot.motivo_de_base({"base": {"ref": "main"}}))
        for otra in ("otra", "Main", "", None):
            with self.subTest(otra=otra):
                self.assertIn("solo publica propuestas contra `main`", robot.motivo_de_base({"base": {"ref": otra}}))

    # ── 4. Sin rol o con rol bajo: solo la propia fila, sin mover `main` por nada ──
    def test_nadie_publica_un_archivo_reordenado_o_lleno_de_espacios(self):
        reordenado = copy.deepcopy(MIEMBROS)
        reordenado["miembros"].reverse()
        for datos in (b(reordenado), b(MIEMBROS) + b" " * 100_000, indentado(MIEMBROS)):
            for quien in (NUEVO_ID, INVITADO_ID, COLAB_ID, EDITOR_ID, ADMIN_ID, PROP_ID):
                with self.subTest(quien=quien, largo=len(datos)):
                    motivos = proponer(quien, {M: datos})
                    self.assertEqual(1, len(motivos), motivos)
                    self.assertIn("no cambia nada de lo que dice", motivos[0])
        self.assertEqual([], proponer(DUENO_ID, {M: indentado(MIEMBROS)}))  # el Dueño puede (migraciones)

    def test_nadie_publica_un_canal_json_o_una_lista_negra_reformateados(self):
        for quien in (COLAB_ID, EDITOR_ID, ADMIN_ID, PROP_ID):
            with self.subTest(quien=quien):
                motivos = proponer(quien, {C: indentado(CANAL)})
                self.assertEqual(1, len(motivos), motivos)
                self.assertIn("no cambia nada de lo que dice", motivos[0])
        self.assertIn("no cambia nada de lo que dice", proponer(ADMIN_ID, {L: indentado(LISTA)})[0])
        self.assertEqual([], proponer(DUENO_ID, {C: indentado(CANAL)}))

    def test_aceptar_y_de_paso_reformatear_lo_de_los_demas_no_vale(self):
        main = {M: indentado(MIEMBROS)}
        aceptado = miembros(lambda m: fila(m, INVITADO_ID).update(estado="activo"))
        self.assertIn("solo puedes cambiar tu propia fila", proponer(INVITADO_ID, {M: b(aceptado)}, antes=main)[0])
        al_reves = miembros(lambda m: (m.reverse(), fila(m, INVITADO_ID).update(estado="activo")))
        self.assertIn("solo puedes cambiar tu propia fila", proponer(INVITADO_ID, {M: indentado(al_reves)}, antes=main)[0])
        # Con el formato del parcheador, pero los demás reordenados, tampoco.
        self.assertIn("solo puedes cambiar tu propia fila",
                      proponer(INVITADO_ID, {M: canales.escribir_como_la_app(al_reves).encode()}, antes=main)[0])
        # Un Colaborador que corrige su nombre y de paso mete espacios en otra fila.
        texto = indentado(MIEMBROS).decode().replace('"cuenta": "admin"', '"cuenta":     "admin"')
        self.assertIn("solo puedes cambiar tu propia fila", proponer(
            COLAB_ID, {M: texto.replace('"cuenta": "colab"', '"cuenta": "Colab"').encode()}, antes=main)[0])

    def test_aceptar_desde_el_parcheador_o_tocando_solo_su_fila_vale(self):
        main = {M: indentado(MIEMBROS)}
        aceptado = miembros(lambda m: fila(m, INVITADO_ID).update(estado="activo"))
        self.assertEqual([], proponer(INVITADO_ID, {M: canales.escribir_como_la_app(aceptado).encode()}, antes=main))
        texto = indentado(MIEMBROS).decode()
        self.assertEqual(1, texto.count('"estado": "invitado"'))
        a_mano = texto.replace('"estado": "invitado"', '"estado": "activo"')
        self.assertEqual([], proponer(INVITADO_ID, {M: a_mano.encode()}, antes=main))
        # Salir (quitar su fila) a mano: con la coma de delante o con la de detrás.
        filas = canales._filas_con_posicion(texto)
        k = next(i for i, f in enumerate(filas) if f[2] == INVITADO_ID)
        sin_su_fila = texto[:filas[k - 1][1]] + texto[filas[k][1]:]
        self.assertEqual([f for f in MIEMBROS["miembros"] if f["id"] != INVITADO_ID], json.loads(sin_su_fila)["miembros"])
        self.assertEqual([], proponer(INVITADO_ID, {M: sin_su_fila.encode()}, antes=main))
        k = next(i for i, f in enumerate(filas) if f[2] == COLAB_ID)
        self.assertEqual([], proponer(COLAB_ID, {M: (texto[:filas[k][0]] + texto[filas[k + 1][0]:]).encode()}, antes=main))
        # Quitar una fila ajena con su coma no vale (no es la suya).
        k = next(i for i, f in enumerate(filas) if f[2] == EDITOR_ID)
        self.assertTrue(proponer(COLAB_ID, {M: (texto[:filas[k][0]] + texto[filas[k + 1][0]:]).encode()}, antes=main))

    def test_el_formato_del_parcheador(self):
        self.assertEqual(FORMATO_APP, canales.escribir_como_la_app(json.loads(FORMATO_APP)))
        self.assertEqual("[]\n", canales.escribir_como_la_app([]))
        # Una lista o un objeto vacío no es «simple»: el objeto que los tiene va en varias líneas (igual que en C#).
        self.assertEqual('{\n  "a": [],\n  "b": {}\n}\n', canales.escribir_como_la_app({"a": [], "b": {}}))
        for raro in ("", "[", '{"miembros": 3}', '{"a": 1 "miembros": []}', "{}", '{"miembros": [1,]}'):
            with self.subTest(raro=raro):
                self.assertIsNone(canales._filas_con_posicion(raro))
        self.assertEqual([], canales._filas_con_posicion('{"esquema": 1, "miembros": [ ]}'))

    # ── 5. El rol del vetado, como lo calcula el robot ──
    def test_no_se_veta_a_un_administrador_que_lo_es_por_el_equipo_de_github(self):
        externo_id = 777
        main = {L: b(LISTA), M: b(MIEMBROS)}

        def revisar(quien, rol_externo):
            lista = copy.deepcopy(LISTA)
            lista["usuarios"].append({"id": externo_id, "cuenta": "deequipo", "motivo": "x", "por": quien})
            despues = {**main, L: b(lista)}
            return comprobar([Cambio(L, "M", "100644", len(despues[L]))], json.dumps(CATALOGO), json.dumps(CATALOGO),
                             permisos(quien), leer_archivo=lambda r, lado: (main if lado == "antes" else despues).get(r),
                             ids_duenos=frozenset({DUENO_ID}), cuenta_de={**CUENTAS, externo_id: "deequipo"}.get,
                             rol_externo=rol_externo)
        de_equipo = lambda canal, i: 3 if (canal, i) == ("ornizen", externo_id) else 0  # noqa: E731
        motivos = revisar(ADMIN_ID, de_equipo)
        self.assertEqual(1, len(motivos), motivos)
        self.assertIn("Administrador", motivos[0])
        self.assertEqual([], revisar(PROP_ID, de_equipo))
        self.assertEqual([], revisar(ADMIN_ID, None))  # sin rol fuera del archivo, sí

    # ── 6. Varias cuentas en una propuesta de canales ──
    def test_con_varias_cuentas_no_se_cambia_nada_de_un_canal(self):
        varias = Permisos(Rol.ADMINISTRADOR, por_canal={"ornizen": Rol.ADMINISTRADOR}, cuenta_id=None)
        casos = {
            "invitar sin invitadoPor": {M: miembros(invitar(por=None))},
            "vetar sin por": {L: {**LISTA, "usuarios": LISTA["usuarios"] + [{"id": EDITOR_ID, "cuenta": "editor", "motivo": "x"}]}},
            "quitar un veto antiguo": {L: {**LISTA, "usuarios": []}},
        }
        for nombre, archivos in casos.items():
            with self.subTest(nombre):
                cambios = [Cambio(r, "M", "100644", 10) for r in archivos]
                motivos = comprobar(cambios, json.dumps(CATALOGO), json.dumps(CATALOGO), varias,
                                    leer_archivo=lambda r, lado, a=archivos: b(a[r] if lado == "despues" else {M: MIEMBROS, L: LISTA}[r]),
                                    ids_duenos=frozenset({DUENO_ID}), cuenta_de=CUENTAS.get)
                self.assertEqual(1, len(motivos))
                self.assertIn("la han tocado varias cuentas", motivos[0])
        motivos = comprobar([Cambio(L, "M", "100644", 10)], None, None, Permisos(Rol.DUENO),
                            leer_archivo=lambda r, lado: b({**LISTA, "usuarios": []} if lado == "despues" else LISTA))
        self.assertNotIn("varias cuentas", " ".join(motivos))

    # ── 7. Nombres que se hacen pasar por otros ──
    def test_el_esqueleto_junta_lo_que_se_ve_igual(self):
        for falso in ("Ornizen", "0rnizen", "ORNIZEN", "Оrnizen", "Οrnizen", "Ｏｒｎｉｚｅｎ", "𝐎𝐫𝐧𝐢𝐳𝐞𝐧", "Ⓞⓡⓝⓘⓩⓔⓝ",
                      "ᴏʀɴɪᴢᴇɴ", "Ornlzen", "Orn1zen", "Omizen", "Órnízen", "orniz_fan", "Los de Orniz", "O r n i z"):
            with self.subTest(falso=falso):
                self.assertTrue(canales.nombre_reservado(falso), canales.esqueleto(falso))
        for bueno in ("Rance Traducciones", "Ornitorrinco", "Zen Studio", "Nori Zen", "", "ランス翻訳"):
            with self.subTest(bueno=bueno):
                self.assertFalse(canales.nombre_reservado(bueno), canales.esqueleto(bueno))
        self.assertFalse(canales.nombre_reservado(None))
        self.assertEqual(canales.esqueleto("Rance"), canales.esqueleto("Rаnce"))  # con a cirílica

    def test_el_nombre_de_un_canal_no_usa_letras_de_estilo(self):
        for falso in ("Ｒａｎｃｅ", "𝐑𝐚𝐧𝐜𝐞", "Ⓡance", "ʀance", "Rance²"):
            with self.subTest(falso=falso):
                motivos = canales.validar_canal({**CANAL, "nombre": falso}, "ornizen", C)
                self.assertTrue(any("letras" in m or "versalitas" in m for m in motivos), motivos)
        self.assertEqual([], canales.validar_canal({**CANAL, "nombre": "Équipe Ñandú 🎮"}, "ornizen", C))

    def test_solo_el_dueno_y_el_canal_oficial_se_llaman_como_orniz(self):
        otro = {**CANAL, "id": "otro_canal", "nombre": "Rance Fans"}
        ruta = "canales/otro_canal/canal.json"

        def renombrar(nombre, rol, es_dueno=False):
            nuevo = {**otro, "nombre": nombre}
            return canales.comprobar_canales([canales.CambioCanal(ruta, "M", len(b(nuevo)), b(otro), b(nuevo))],
                                             {"otro_canal": rol}, ADMIN_ID, es_dueno)
        for nombre in ("0rnizen", "Orniz Traducciones", "ᴏʀɴɪᴢ"):
            with self.subTest(nombre=nombre):
                self.assertTrue(any("se parece a Orniz" in m for m in renombrar(nombre, 4)), renombrar(nombre, 4))
        self.assertFalse(any("Orniz" in m for m in renombrar("0rnizen", 5, es_dueno=True)))
        self.assertEqual([], renombrar("Rance Fans 2", 3))
        # En el canal oficial sí: es el suyo.
        self.assertEqual([], proponer(ADMIN_ID, {C: {**CANAL, "nombre": "Ornizen Traducciones"}}))

    # ── 8. JSON estricto en el catálogo ──
    def test_el_catalogo_tambien_es_json_estricto(self):
        casos = {"NaN": '{"esquema": NaN}', "clave repetida": '{"esquema": 1, "esquema": 1}',
                 "entero gigante": '{"esquema": ' + "9" * 5000 + "}", "1e999": '{"esquema": 1e999}',
                 "anidado": "[" * 100000, "roto": '{"esquema": 1,}'}
        for nombre, texto in casos.items():
            with self.subTest(nombre):
                cat, errores = robot.validar_catalogo(texto, CATALOGO)
                self.assertIsNone(cat)
                self.assertEqual(1, len(errores))
                self.assertIn("catalogo.json", errores[0])
                self.assertTrue(comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(CATALOGO), texto, permisos(DUENO_ID)))
        cat, errores = robot.validar_catalogo(json.dumps({**CATALOGO, "versionCatalogo": 2}), CATALOGO)
        self.assertEqual([], errores)


class Contador:
    """Un `cuenta_de` que cuenta cuántas veces se pregunta a GitHub."""

    def __init__(self, nombres=None):
        self.nombres, self.veces = dict(CUENTAS if nombres is None else nombres), 0

    def __call__(self, cuenta_id):
        self.veces += 1
        return self.nombres.get(cuenta_id, f"cuenta{cuenta_id}")


def muchas(n, desde=1000, estado="invitado", rol="editor", por=ADMIN_ID):
    def poner(lista):
        for i in range(n):
            fila_nueva = {"id": desde + i, "cuenta": f"cuenta{desde + i}", "rol": rol, "estado": estado}
            if por is not None:
                fila_nueva["invitadoPor"] = por
            lista.append(fila_nueva)
    return poner


CABEZA = "c" * 40
REPO = "copia/ParcheadorRance-Datos"


class FalsaApi:
    """La API de GitHub para `cuentas_de_la_propuesta`: commits y ejecuciones del robot (de la más nueva a la más vieja)
    y, si se relanza, la ejecución actual."""

    def __init__(self, commits, ejecuciones, actual=None):
        self.commits, self.ejecuciones, self.actual, self.llamadas = commits, ejecuciones, actual, []

    def __call__(self, metodo, ruta, datos=None, tolerar=()):
        self.llamadas.append(ruta)
        pagina = int(ruta.rsplit("page=", 1)[1]) if "page=" in ruta else 1
        trozo = slice((pagina - 1) * 100, pagina * 100)
        if "/commits" in ruta:
            return self.commits[trozo]
        if ruta.startswith("/actions/runs/"):
            return self.actual if self.actual and str(self.actual["id"]) == ruta.rsplit("/", 1)[1] else None
        if ruta.startswith("/actions/workflows/permisos.yml/runs?") and "head_sha=" in ruta:
            sha = ruta.split("head_sha=", 1)[1].split("&", 1)[0]
            desde = urllib.parse.unquote(ruta.split("created=", 1)[1].split("&", 1)[0])
            assert desde.startswith(">="), ruta
            return {"workflow_runs": [e for e in self.ejecuciones
                                      if e["head_sha"] == sha and e["created_at"] >= desde[2:]][trozo]}
        raise AssertionError(ruta)


def usuario(cuenta_id):
    return {"login": CUENTAS.get(cuenta_id, f"cuenta{cuenta_id}"), "id": cuenta_id}


def commit(autor, committer=None, sha=CABEZA):
    committer = robot.ID_WEB_FLOW if committer is None else committer
    return {"sha": sha, "author": None if autor == "nadie" else usuario(autor),
            "committer": None if committer == "nadie" else (
                {"login": "web-flow", "id": robot.ID_WEB_FLOW} if committer == robot.ID_WEB_FLOW else usuario(committer)),
            "commit": {"author": {"email": "alguien@example.org"}, "committer": {"email": "noreply@github.com"}}}


_IDS = iter(range(1000, 10 ** 9))
ABIERTA = "a" * 40   # la cabeza con la que se abrió la propuesta
OCULTO = "b" * 40    # un commit que el robot no vio subir


def ejecucion(actor, accion="synchronize", antes=ABIERTA, sha=CABEZA, disparador=None, numero=7, repo=REPO,
              creada="2026-11-23T10:00:00Z", id_=None, ruta=".github/workflows/permisos.yml", evento="pull_request_target",
              titulo=None, intento=1):
    """Una ejecución del robot como la devuelve GitHub, con el nombre de `run-name` (o `titulo`, como las de antes)."""
    nombre = f"Robot de permisos · #{numero} · {accion} · antes {antes if accion == 'synchronize' else 'ninguno'}"
    return {"id": id_ or next(_IDS), "actor": usuario(actor), "triggering_actor": usuario(disparador or actor),
            "head_repository": {"full_name": repo}, "created_at": creada, "head_sha": sha, "path": ruta, "event": evento,
            "display_title": nombre if titulo is None else titulo, "run_attempt": intento}


def abierta(actor=ADMIN_ID, sha=ABIERTA):
    return ejecucion(actor, "opened", sha=sha)


PROPUESTA = {"commits": 1, "created_at": "2026-11-23T09:00:00Z",
             "head": {"ref": "equipo/colab/cambio", "repo": {"full_name": REPO}}}


def quienes(api, accion="synchronize", antes=ABIERTA, propuesta=PROPUESTA, actual=None, intento=None, actuales=(),
            desde=""):
    return robot.cuentas_de_la_propuesta(api, 7, propuesta, CABEZA, accion, actual, lambda i: i == DUENO_ID, actuales,
                                         antes, intento, desde)


def ids(cuentas):
    return [i for _, i in cuentas]


class TerceraRevision(unittest.TestCase):
    """Tercera revisión de seguridad de la fase A (cada prueba, un hallazgo)."""

    # ── N1: un main con una versión absurda no bloquea a nadie, tampoco al Dueño ──
    def test_n1_el_dueno_arregla_un_main_envenenado(self):
        for absurda in ("9" * 30, "9" * 5000, str(2 ** 31 - 1)):
            with self.subTest(cifras=len(absurda)):
                antes = '{"esquema": 1, "versionCatalogo": ' + absurda + ', "etiquetas": [], "juegos": []}'
                motivos = comprobar([Cambio(RUTA_CATALOGO, "M")], antes, json.dumps({**CATALOGO, "versionCatalogo": 31}),
                                    permisos(DUENO_ID))
                self.assertEqual([], motivos)

    # ── N2: nadie agota la cuota del robot ──
    def test_n2_sin_rol_cientos_de_filas_no_consultan_nada_de_mas(self):
        contador = Contador()
        nuevo = miembros(lambda m: (fila(m, INVITADO_ID).update(estado="activo"), muchas(596, por=None)(m)))
        motivos = proponer(INVITADO_ID, {M: nuevo}, cuenta_de=contador)
        self.assertTrue(motivos)
        self.assertLessEqual(contador.veces, 1)

    def test_n2_un_colaborador_tampoco(self):
        contador = Contador()
        motivos = proponer(COLAB_ID, {M: miembros(muchas(90))}, cuenta_de=contador)
        self.assertIn("cosa de un Administrador", motivos[0])
        self.assertEqual(0, contador.veces)

    def test_n2_un_administrador_tiene_un_tope_de_filas(self):
        contador = Contador()
        motivos = proponer(ADMIN_ID, {M: miembros(muchas(canales.TOPE_FILAS_CON_CUENTA + 1))}, cuenta_de=contador)
        self.assertIn(f"el máximo son {canales.TOPE_FILAS_CON_CUENTA}", motivos[0])
        self.assertEqual(0, contador.veces)
        contador = Contador()
        self.assertEqual([], proponer(ADMIN_ID, {M: miembros(muchas(canales.TOPE_FILAS_CON_CUENTA))}, cuenta_de=contador))
        self.assertEqual(canales.TOPE_FILAS_CON_CUENTA, contador.veces)

    def test_n2_tampoco_con_la_lista_negra(self):
        lista = copy.deepcopy(LISTA)
        lista["usuarios"] += [{"id": 5000 + i, "cuenta": f"cuenta{5000 + i}", "motivo": "x", "por": ADMIN_ID}
                              for i in range(canales.TOPE_FILAS_CON_CUENTA + 1)]
        contador = Contador()
        motivos = proponer(ADMIN_ID, {L: lista}, cuenta_de=contador)
        self.assertIn("vetos a la vez", motivos[0])
        self.assertEqual(0, contador.veces)

    def test_n2_ni_el_dueno_pasa_del_tope_de_consultas(self):
        contador = Contador()
        nuevo = miembros(muchas(canales.TOPE_CONSULTAS_DUENO + 1, estado="activo", rol="colaborador", por=None))
        motivos = proponer(DUENO_ID, {M: nuevo}, cuenta_de=contador)
        self.assertTrue(any("demasiadas cuentas" in m for m in motivos), motivos)
        self.assertEqual(canales.TOPE_CONSULTAS_DUENO, contador.veces)

    # ── N3 (cuarta revisión 2.1, 2.2, L8; quinta 1–4): cuentan todos los que han subido algo ──
    def test_n3_un_edited_no_blanquea_commits_ajenos(self):
        # El Administrador abre, el Colaborador sube (su ejecución) y el Administrador edita el título (la actual).
        api = FalsaApi([commit(COLAB_ID)], [ejecucion(ADMIN_ID, "edited", id_=2), ejecucion(COLAB_ID), abierta()])
        cuentas = robot.unir_cuentas([("admin", ADMIN_ID)], quienes(api, "edited", actual=2))
        self.assertIn(COLAB_ID, ids(cuentas))
        self.assertEqual(Rol.COLABORADOR, robot.combinar([permisos(i) for _, i in cuentas]).rol_global)

    def test_n3_el_que_sube_cuenta_aunque_falsee_el_autor(self):
        # El Colaborador sube un commit con el correo del Administrador: cuenta igual, por la ejecución de su subida.
        api = FalsaApi([commit(ADMIN_ID, ADMIN_ID)], [abierta()])
        cuentas = ids(quienes(api, actuales=[("colab", COLAB_ID)]))
        self.assertIn(COLAB_ID, cuentas)
        self.assertIn(ADMIN_ID, cuentas)

    def test_5_1_sin_ver_subir_la_cabeza_se_rechaza(self):
        # Reabierta (o base cambiada, o ejecución borrada): nadie vio subir la cabeza. Que haya ejecuciones con esa
        # cabeza que no son subidas (la del `reopened` rechazado, por ejemplo) no basta.
        for accion in ("reopened", "edited", "ready_for_review", ""):
            with self.subTest(accion=accion):
                api = FalsaApi([commit(ADMIN_ID, ADMIN_ID)], [ejecucion(ADMIN_ID, "reopened", id_=5),
                                                              ejecucion(ADMIN_ID, "edited"), abierta(sha=OCULTO)])
                with self.assertRaises(robot.SinSaberQuien) as error:
                    quienes(api, accion, actual=5)
                self.assertIn("Cierra esta propuesta", str(error.exception))
                self.assertIn(CABEZA[:7], str(error.exception))
        # Las subidas con esa cabeza de otra copia, otro flujo, otro evento, otra propuesta, de antes de abrirla o de
        # antes del `run-name` (con el título de la propuesta como nombre, aunque lo imite) no valen.
        imitado = f"Robot de permisos · #7 · synchronize · antes {ABIERTA}"
        for nombre, otra in {"otra copia": ejecucion(COLAB_ID, repo="otra/copia"),
                             "otro flujo": ejecucion(COLAB_ID, ruta=".github/workflows/otro.yml"),
                             "evento pull_request": ejecucion(COLAB_ID, evento="pull_request"),
                             "otra propuesta": ejecucion(COLAB_ID, numero=8),
                             "antes de abrirla": ejecucion(COLAB_ID, creada="2026-11-23T08:00:00Z"),
                             "título a mano": ejecucion(COLAB_ID, titulo=imitado + " "),
                             "sin nombre": ejecucion(COLAB_ID, titulo="Canales fase A"),
                             "otra cabeza": ejecucion(COLAB_ID, sha=OCULTO)}.items():
            with self.subTest(nombre):
                with self.assertRaises(robot.SinSaberQuien):
                    quienes(FalsaApi([commit(COLAB_ID)], [ejecucion(ADMIN_ID, "reopened", id_=5), otra, abierta()]),
                            "reopened", actual=5)
        with self.subTest("de antes del run-name en main"), self.assertRaises(robot.SinSaberQuien):
            quienes(FalsaApi([commit(COLAB_ID)], [ejecucion(COLAB_ID), abierta()]), "reopened",
                    desde="2026-11-24T00:00:00Z")

    def test_5_1_con_la_subida_vista_vale(self):
        api = FalsaApi([commit(COLAB_ID)], [ejecucion(ADMIN_ID, "reopened", id_=6), ejecucion(COLAB_ID), abierta()])
        self.assertIn(COLAB_ID, ids(quienes(api, "reopened", actual=6)))
        # ready_for_review de un borrador que abrió el mismo Editor y nadie más tocó.
        api = FalsaApi([commit(EDITOR_ID)], [abierta(EDITOR_ID, sha=CABEZA)])
        self.assertEqual({EDITOR_ID}, set(ids(quienes(api, "ready_for_review"))))

    def test_5_1_el_dueno_solo_responde_si_relanza_de_verdad(self):
        # Propuesta del Dueño; un Editor ha subido la cabeza sin que el robot lo viera (autor: el Dueño, falseado).
        subidas = [abierta(DUENO_ID)]
        relanzada = ejecucion(DUENO_ID, "reopened", id_=5, intento=2)
        dueno = [("0rnizL", DUENO_ID)]
        # El Dueño reabre, edita o marca como lista: no blanquea nada (N3-f, N3-f3).
        for accion in ("reopened", "edited", "ready_for_review"):
            with self.subTest(accion=accion), self.assertRaises(robot.SinSaberQuien):
                quienes(FalsaApi([commit(DUENO_ID, DUENO_ID)], subidas, actual=relanzada), accion, actual=5,
                        intento="1", actuales=dueno)
        # Relanzarla de verdad, sí: intento 2 o más según la API, por el Dueño y con la misma cabeza.
        api = FalsaApi([commit(DUENO_ID, DUENO_ID)], subidas, actual=relanzada)
        self.assertIn(DUENO_ID, ids(quienes(api, "reopened", actual=5, intento="2", actuales=dueno)))
        self.assertIn("/actions/runs/5", api.llamadas)
        falsos = {"el entorno dice 2 y la API 1": {**relanzada, "run_attempt": 1},
                  "lo relanza un Administrador": {**relanzada, "triggering_actor": usuario(ADMIN_ID)},
                  "otra cabeza": {**relanzada, "head_sha": OCULTO},
                  "otra propuesta": {**relanzada, "display_title": relanzada["display_title"].replace("#7", "#8")},
                  "otra copia": {**relanzada, "head_repository": {"full_name": "otra/copia"}},
                  "no se encuentra": None}
        for nombre, actual in falsos.items():
            with self.subTest(nombre), self.assertRaises(robot.SinSaberQuien):
                quienes(FalsaApi([commit(DUENO_ID, DUENO_ID)], subidas, actual=actual), "reopened", actual=5,
                        intento="2", actuales=dueno)
        # Al relanzar la propuesta de un Administrador, el Administrador sigue contando.
        api = FalsaApi([commit(ADMIN_ID)], [abierta()], actual=ejecucion(ADMIN_ID, "reopened", id_=5, intento=2,
                                                                        disparador=DUENO_ID))
        self.assertIn(ADMIN_ID, ids(quienes(api, "reopened", actual=5, intento="2",
                                            actuales=[("admin", ADMIN_ID), ("0rnizL", DUENO_ID)])))

    def test_5_2_subir_otro_commit_encima_no_blanquea(self):
        # N3-h: el commit OCULTO lo subió otro con la propuesta cerrada; tras el rechazo, el Administrador sube encima.
        rechazada = ejecucion(ADMIN_ID, "reopened", sha=OCULTO)
        api = FalsaApi([commit(ADMIN_ID), commit(ADMIN_ID)], [rechazada, abierta()])
        with self.assertRaises(robot.SinSaberQuien) as error:
            quienes(api, "synchronize", antes=OCULTO, actuales=[("admin", ADMIN_ID)])
        self.assertIn(OCULTO[:7], str(error.exception))
        # Ni subiendo dos veces: la subida rechazada de en medio no hace bueno lo de debajo.
        medio = "d" * 40
        api = FalsaApi([commit(ADMIN_ID)] * 3, [ejecucion(ADMIN_ID, antes=OCULTO, sha=medio), rechazada, abierta()])
        with self.assertRaises(robot.SinSaberQuien):
            quienes(api, "synchronize", antes=medio, actuales=[("admin", ADMIN_ID)])
        # Y sin `before` (flujo sin PR_ANTES) tampoco.
        for antes in (None, "", "zzz", ABIERTA[:7]):
            with self.subTest(antes=antes), self.assertRaises(robot.SinSaberQuien):
                quienes(FalsaApi([commit(ADMIN_ID)], [abierta()]), "synchronize", antes=antes)

    def test_5_2_la_cadena_entera_cuenta_y_no_da_vueltas(self):
        # Abre el Administrador, sube el Colaborador, sube el Editor y luego se rehace con force-push encima de la
        # primera: cuentan todos los que subieron algo por el camino; una vuelta a una cabeza ya vista no se repite.
        b, d = "1" * 40, "2" * 40
        api = FalsaApi([commit(ADMIN_ID)], [ejecucion(ADMIN_ID, antes=d), ejecucion(EDITOR_ID, antes=b, sha=d),
                                            ejecucion(COLAB_ID, antes=ABIERTA, sha=b),
                                            ejecucion(VETADO_ID, antes=d, sha=ABIERTA), abierta()])
        cuentas = set(ids(quienes(api, "edited")))
        self.assertTrue({ADMIN_ID, EDITOR_ID, COLAB_ID, VETADO_ID} <= cuentas)
        self.assertEqual(4, sum("head_sha=" in r for r in api.llamadas))

    def test_6_1_las_ajenas_se_filtran_antes_de_contar(self):
        leidas = robot.TOPE_PAGINAS_POR_COMMIT * 100
        # Con el mismo commit, cientos de ejecuciones de otras copias (más que el tope de subidas) y la buena al final,
        # en la última página que se lee: no bloquean ni cuentan.
        ajenas = [ejecucion(VETADO_ID, repo="otra/copia") for _ in range(leidas - 1)]
        api = FalsaApi([commit(COLAB_ID)], ajenas + [ejecucion(COLAB_ID), abierta()])
        cuentas = ids(quienes(api, "edited"))
        self.assertIn(COLAB_ID, cuentas)
        self.assertNotIn(VETADO_ID, cuentas)
        self.assertGreater(leidas - 1, robot.TOPE_SUBIDAS_POR_COMMIT)
        # Más de las que se leen: ese commit no se puede comprobar; el mensaje dice cómo salir.
        ajenas = [ejecucion(VETADO_ID, repo="otra/copia") for _ in range(leidas)]
        api = FalsaApi([commit(COLAB_ID)], ajenas + [ejecucion(COLAB_ID), abierta()])
        with self.assertRaises(robot.SinSaberQuien) as error:
            quienes(api, "edited")
        self.assertIn(f"más de {leidas}", str(error.exception))
        self.assertIn("propuesta nueva", str(error.exception))
        self.assertIn("relance", str(error.exception))
        self.assertEqual(robot.TOPE_PAGINAS_POR_COMMIT + 1, sum("head_sha=" in r for r in api.llamadas))
        # …y el Dueño sí puede relanzarla (se mira antes de rechazar).
        relanzada = ejecucion(ADMIN_ID, "edited", id_=5, intento=2, disparador=DUENO_ID)
        api = FalsaApi([commit(COLAB_ID)], ajenas + [ejecucion(COLAB_ID), abierta()], actual=relanzada)
        self.assertIn(DUENO_ID, ids(quienes(api, "edited", actual=5, intento="2",
                                           actuales=[("admin", ADMIN_ID), ("0rnizL", DUENO_ID)])))
        # Las de antes de abrir la propuesta no llegan (las filtra GitHub con `created`) ni gastan nada.
        viejas = [ejecucion(VETADO_ID, creada="2026-11-20T00:00:00Z") for _ in range(5000)]
        api = FalsaApi([commit(COLAB_ID)], [ejecucion(COLAB_ID)] + viejas + [abierta()])
        self.assertNotIn(VETADO_ID, ids(quienes(api, "reopened")))
        self.assertEqual(2, sum("head_sha=" in r for r in api.llamadas))

    def test_6_1_el_tope_de_subidas_por_commit_cuenta_solo_las_de_la_propuesta(self):
        tope = robot.TOPE_SUBIDAS_POR_COMMIT
        propias = [ejecucion(COLAB_ID) for _ in range(tope)]
        self.assertIn(COLAB_ID, ids(quienes(FalsaApi([commit(COLAB_ID)], propias + [abierta()]), "edited")))
        with self.assertRaises(robot.SinSaberQuien) as error:
            quienes(FalsaApi([commit(COLAB_ID)], propias + [ejecucion(COLAB_ID), abierta()]), "edited")
        self.assertIn(f"más de {tope} veces", str(error.exception))

    def test_5_tope_de_subidas(self):
        cadena, antes = [], ABIERTA
        for i in range(robot.TOPE_SUBIDAS):
            sha = f"{i + 1:040x}"
            cadena.append(ejecucion(COLAB_ID, antes=antes, sha=sha))
            antes = sha
        api = FalsaApi([commit(COLAB_ID)], cadena + [abierta()])
        with self.assertRaises(robot.SinSaberQuien) as error:
            quienes(api, "synchronize", antes=antes)
        self.assertIn(f"más de {robot.TOPE_SUBIDAS} subidas", str(error.exception))
        api = FalsaApi([commit(COLAB_ID)], cadena[1:] + [ejecucion(COLAB_ID, "opened", sha=cadena[0]["head_sha"])])
        self.assertIn(COLAB_ID, ids(quienes(api, "synchronize", antes=antes)))

    def test_n3_si_no_se_sabe_quien_se_rechaza(self):
        casos = {
            "autor sin cuenta": FalsaApi([commit("nadie")], [abierta(COLAB_ID)]),
            "committer sin cuenta": FalsaApi([commit(COLAB_ID, "nadie")], [abierta(COLAB_ID)]),
            "ejecución sin actor": FalsaApi([commit(COLAB_ID)], [{**abierta(COLAB_ID), "actor": None}]),
        }
        for nombre, api in casos.items():
            with self.subTest(nombre), self.assertRaises(robot.SinSaberQuien):
                quienes(api, actuales=[("colab", COLAB_ID)])
        with self.assertRaises(robot.SinSaberQuien):
            quienes(FalsaApi([], [abierta()]), propuesta={**PROPUESTA, "head": {"ref": "x", "repo": None}})

    def test_l8_correos_sin_cuenta_valen_si_todo_lo_subio_el_dueno(self):
        dueno = [("0rnizL", DUENO_ID)]
        # `publicar-version.ps1` desde otro equipo: el commit no es de ninguna cuenta, pero lo sube el Dueño.
        self.assertEqual({DUENO_ID}, set(ids(quienes(FalsaApi([commit("nadie", "nadie")], []), "opened",
                                                     actuales=dueno))))
        self.assertEqual({DUENO_ID}, set(ids(quienes(FalsaApi([commit("nadie", "nadie")], [abierta(DUENO_ID)]),
                                                     actuales=dueno))))
        # …pero no si alguien más ha subido algo a la propuesta.
        api = FalsaApi([commit("nadie", "nadie"), commit(COLAB_ID, sha="e" * 40)],
                       [ejecucion(COLAB_ID, sha="e" * 40), abierta(DUENO_ID)])
        with self.assertRaises(robot.SinSaberQuien):
            quienes(api, antes="e" * 40, actuales=dueno)
        # …ni si la última subida no la ha hecho el Dueño (aunque el resto, sí).
        with self.assertRaises(robot.SinSaberQuien):
            quienes(FalsaApi([commit("nadie", "nadie")], [abierta(DUENO_ID)]), actuales=[("colab", COLAB_ID)])
        # …ni si la propuesta la abrió otro, aunque el Dueño la relance (L8-g).
        relanzada = ejecucion(ADMIN_ID, "opened", id_=5, intento=2, disparador=DUENO_ID)
        with self.assertRaises(robot.SinSaberQuien):
            quienes(FalsaApi([commit("nadie", "nadie")], [], actual=relanzada), "opened", actual=5, intento="2",
                    actuales=[("admin", ADMIN_ID), ("0rnizL", DUENO_ID)])
        # …ni si el Dueño reabre o edita su propuesta con un commit sin cuenta que el robot no vio subir (L8-e).
        with self.assertRaises(robot.SinSaberQuien):
            quienes(FalsaApi([commit(DUENO_ID), commit("nadie", "nadie")], [abierta(DUENO_ID, sha=OCULTO)]),
                    "reopened", actuales=dueno)

    def test_n3_topes(self):
        with self.assertRaises(robot.SinSaberQuien):
            quienes(FalsaApi([], [abierta()]), propuesta={**PROPUESTA, "commits": 251})
        # Aunque la propuesta diga que tiene pocos, se cuentan los que llegan (paginando).
        api = FalsaApi([commit(COLAB_ID, sha=f"{i:040x}") for i in range(251)], [abierta()])
        with self.assertRaises(robot.SinSaberQuien):
            quienes(api)
        self.assertLessEqual(sum("/commits" in r for r in api.llamadas), 3)
        with self.assertRaises(robot.SinSaberQuien):
            robot.unir_cuentas([(f"c{i}", i) for i in range(robot.TOPE_CUENTAS + 1)])

    def test_n3_web_flow_no_es_nadie(self):
        api = FalsaApi([commit(COLAB_ID)], [abierta(COLAB_ID)])
        self.assertNotIn(robot.ID_WEB_FLOW, ids(quienes(api, actuales=[("colab", COLAB_ID)])))

    def test_5_el_nombre_del_flujo_es_el_que_lee_el_robot(self):
        flujo = (pathlib.Path(robot.__file__).parent.parent / robot.FLUJO_DEL_ROBOT).read_text(encoding="utf-8")
        plantilla = next(l for l in flujo.splitlines() if l.startswith("run-name:")).split(":", 1)[1].strip().strip('"')
        for accion, antes in (("synchronize", CABEZA), ("opened", None), ("edited", None)):
            nombre = (plantilla.replace("${{ github.event.pull_request.number }}", "7")
                      .replace("${{ github.event.action }}", accion)
                      .replace("${{ github.event.before || 'ninguno' }}", antes or "ninguno"))
            with self.subTest(accion=accion):
                self.assertNotIn("${{", nombre)
                self.assertTrue(robot.NOMBRE_DE_EJECUCION.fullmatch(nombre), nombre)
        self.assertEqual(2, flujo.count("PR_ANTES: ${{ github.event.before }}"))

    def test_5_desde_cuando_hay_nombres_es_la_fusion_en_main(self):
        # Las ejecuciones de antes de que el `run-name` llegara a `main` no valen: cuenta la fusión, no el commit.
        with tempfile.TemporaryDirectory() as carpeta:
            def g(*a, fecha="2026-01-01T00:00:00Z"):
                subprocess.run(["git", *a], cwd=carpeta, check=True, capture_output=True,
                               env={**os.environ, "GIT_AUTHOR_DATE": fecha, "GIT_COMMITTER_DATE": fecha})
            g("init", "-q", "-b", "main")
            g("config", "user.email", "a@b.c")
            g("config", "user.name", "x")
            flujo = pathlib.Path(carpeta, robot.FLUJO_DEL_ROBOT)
            flujo.parent.mkdir(parents=True)
            flujo.write_text("name: Robot de permisos\n", encoding="utf-8")
            g("add", "-A")
            g("commit", "-qm", "sin nombre")
            antes = os.getcwd()
            os.chdir(carpeta)
            try:
                self.assertEqual("9999-12-31T23:59:59Z", robot.desde_cuando_hay_nombres("HEAD"))
                g("checkout", "-q", "-b", "rama")
                flujo.write_text("name: Robot de permisos\n" + robot.RUN_NAME + "\n", encoding="utf-8")
                g("commit", "-qam", "con nombre", fecha="2026-02-01T00:00:00Z")
                g("checkout", "-q", "main")
                g("merge", "-q", "--no-ff", "-m", "fusión", "rama", fecha="2026-03-01T10:20:30Z")
                self.assertEqual("2026-03-01T10:20:30Z", robot.desde_cuando_hay_nombres("HEAD"))
                # Si luego se quita o se cambia, no cuenta la fecha del commit que lo quita: ninguna vale (sexta, 2).
                for texto in ("name: Robot de permisos\n", "name: Robot de permisos\nrun-name: x\n",
                              "name: Robot de permisos\n# " + robot.RUN_NAME + "\n"):
                    with self.subTest(texto=texto):
                        flujo.write_text(texto, encoding="utf-8")
                        g("commit", "-qam", "cambio", fecha="2026-04-01T00:00:00Z")
                        self.assertEqual("9999-12-31T23:59:59Z", robot.desde_cuando_hay_nombres("HEAD"))
            finally:
                os.chdir(antes)

    def test_2_3_solo_se_menciona_a_quien_abrio_la_propuesta(self):
        texto = pathlib.Path(robot.__file__).read_text(encoding="utf-8")
        self.assertIn('", ".join(_sin_enlaces(c) for c, _ in cuentas[1:])', texto)
        self.assertNotIn('", ".join(f"@{c}"', texto)

    def test_vetos_hasta_el_maximo_no_dan_demasiadas_consultas(self):
        # 20 vetos con cuenta (el máximo anunciado) caben en el tope de consultas, también quitando vetos de otros.
        lista = copy.deepcopy(LISTA)
        lista["usuarios"] += [{"id": 5000 + i, "cuenta": f"cuenta{5000 + i}", "motivo": "x", "por": ADMIN_ID}
                              for i in range(canales.TOPE_FILAS_CON_CUENTA - 1)]
        consultas = []
        motivos = proponer(ADMIN_ID, {L: lista}, cuenta_de=lambda i: consultas.append(i) or CUENTAS.get(i, f"cuenta{i}"),
                           rol_externo=lambda canal, i: consultas.append(("rol", i)) or 0)
        self.assertEqual([], motivos)
        self.assertGreater(len(consultas), 30)  # con el tope de antes (30) salía «demasiadas cuentas»
        self.assertGreaterEqual(canales.TOPE_CONSULTAS, 4 * canales.TOPE_FILAS_CON_CUENTA)

    # ── N4: el comentario no se puede manipular ──
    def test_n4_nada_de_la_propuesta_se_interpreta(self):
        malo = ("`catalogo/a`\n\n# Título falso\n[pulsa](https://malo.example) ![x](https://malo.example/p.png) "
                "<img src=x onerror=alert(1)> @0rnizL #12 www.malo.example\u202e`")
        linea = robot.linea_segura(f"`{malo}`: la ruta no vale.")
        self.assertNotIn("\n", linea)
        self.assertNotIn("<img", linea)
        self.assertNotIn("](", linea.replace("\\](", ""))
        self.assertNotIn("https://", linea)
        self.assertNotIn("www.", linea)
        self.assertNotIn("@0rnizL", linea)
        self.assertNotIn("#12", linea)
        self.assertNotIn("\u202e", linea)
        self.assertNotIn("`", linea)

    def test_n4_lo_normal_se_sigue_leyendo_bien(self):
        linea = robot.linea_segura("`canales/ornizen/miembros.json`: tu rol es **Editor**.")
        self.assertEqual("<code>canales/ornizen/miembros.json</code>: tu rol es **Editor**.", linea)

    def test_n4_recortado(self):
        linea = robot.linea_segura("`" + "a" * 10000 + "`: " + "b" * 10000)
        self.assertLess(len(linea), robot.LARGO_MOTIVO + 50)
        self.assertIn("a" * robot.LARGO_CODIGO + "…</code>", linea)

    def test_n4_en_codigo_tampoco(self):
        self.assertEqual("<code>&lt;b&gt;@\u2060x &amp;</code>", robot.linea_segura("`<b>@x &`"))
        # Dentro de <code> GitHub sigue leyendo Markdown: ni enlaces ni negritas.
        self.assertEqual(r"<code>\_\_pycache\_\_/ \[a\](b) \*x\*</code>", robot.linea_segura("`__pycache__/ [a](b) *x*`"))

    # ── N5: la propia fila no se hincha ──
    def test_n5_aceptar_con_la_fila_hinchada_no(self):
        main = {M: canales.escribir_como_la_app(MIEMBROS).encode()}
        texto = main[M].decode()
        filas = canales._filas_con_posicion(texto)
        ini, fin, _ = next(f for f in filas if f[2] == INVITADO_ID)
        propia = json.loads(texto[ini:fin])
        propia["estado"] = "activo"
        canonica = canales._valor_app(propia, 2)
        hinchadas = {
            "espacios": canonica.replace(", ", "," + " " * 100000 + " ", 1),
            "escapes": canonica.replace('"invitada"', '"' + "".join(f"\\u{ord(c):04x}" for c in "invitada") + '"'),
            "salto de línea": canonica.replace("{ ", "{\n      ", 1),
        }
        for nombre, fila_mala in hinchadas.items():
            with self.subTest(nombre):
                self.assertEqual(propia, json.loads(fila_mala))
                motivos = proponer(INVITADO_ID, {M: (texto[:ini] + fila_mala + texto[fin:]).encode()}, antes=main)
                self.assertIn("tu propia fila", motivos[0])
        self.assertEqual([], proponer(INVITADO_ID, {M: (texto[:ini] + canonica + texto[fin:]).encode()}, antes=main))

if __name__ == "__main__":
    unittest.main()
