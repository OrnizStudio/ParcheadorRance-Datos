"""Pruebas de la fase A de canales: roles por archivo, `canales/<canal>/` y JSON estricto.

Uso:  python -m unittest discover -s robot/pruebas
"""
import copy
import json
import pathlib
import sys
import tempfile
import unittest

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "robot"))
import canales  # noqa: E402
from canales import JsonMalo, leer_json_estricto, leer_miembros, error_de_texto  # noqa: E402
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


def proponer(cuenta_id, archivos: dict, antes: dict | None = None, modos=None, extra=()):
    """`archivos` = {ruta: objeto o bytes o None (borrar)}; `antes` = lo que hay en `main` (por defecto, lo de siempre)."""
    main = {M: b(MIEMBROS), C: b(CANAL), L: b(LISTA)}
    if antes is not None:
        main.update({k: (v if isinstance(v, bytes) or v is None else b(v)) for k, v in antes.items()})
    despues = dict(main)
    cambios = []
    for ruta, valor in archivos.items():
        datos = None if valor is None else valor if isinstance(valor, bytes) else b(valor)
        estado = "D" if datos is None else "A" if main.get(ruta) is None else "M"
        despues[ruta] = datos
        cambios.append(Cambio(ruta, estado, (modos or {}).get(ruta, "100644"), len(datos or b"")))
    cambios += list(extra)

    def leer(ruta, lado):
        return (main if lado == "antes" else despues).get(ruta)
    return comprobar(cambios, json.dumps(CATALOGO), json.dumps(CATALOGO), permisos(cuenta_id), leer_archivo=leer)


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
            (lambda m: m.append(dict(m[1], id=999, cuenta="ADMIN")), "repetida"),
            (lambda m: m[0].update(estado="invitado"), "sin ningún Propietario activo"),
        ]
        for cambiar, contiene in casos:
            with self.subTest(contiene=contiene):
                self.assertTrue(any(contiene in e for e in self.errores(miembros(cambiar))), self.errores(miembros(cambiar)))

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
        lista["usuarios"].append({"id": COLAB_ID, "cuenta": "colab", "motivo": "Spam"})
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
        self.assertEqual([], proponer(ADMIN_ID, {"canales/ornizen/logo.webp": b"x" * 1000}))
        self.assertIn("máximo son 512 KB", proponer(ADMIN_ID, {"canales/ornizen/logo.webp": b"x" * (513 * 1024)})[0])
        self.assertIn("lo cambia un Administrador", proponer(EDITOR_ID, {"canales/ornizen/logo.webp": b"x"})[0])

    def test_propuestas_enormes(self):
        muchos = [Cambio(f"catalogo/juegos/j/{i}.png", "A", "100644", 10) for i in range(301)]
        self.assertTrue(any("máximo son 300" in m for m in proponer(ADMIN_ID, {}, extra=muchos)))
        grande = [Cambio(f"catalogo/juegos/j/{i}.png", "A", "100644", 5 * 1024 * 1024) for i in range(5)]
        self.assertTrue(any("MB y el máximo son 20 MB" in m for m in proponer(ADMIN_ID, {}, extra=grande)))
        self.assertTrue(any("ejecutables" in m for m in proponer(ADMIN_ID, {"canales/ornizen/logo.png": b"x"},
                                                                 modos={"canales/ornizen/logo.png": "100755"})))
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
        self.assertEqual([], proponer(ADMIN_ID, {L: quitar_usuario}))
        self.assertIn("es del Propietario del canal", proponer(ADMIN_ID, {L: quitar_archivo})[0])
        self.assertEqual([], proponer(PROP_ID, {L: quitar_archivo}))
        self.assertIn("la cambia un Administrador", proponer(EDITOR_ID, {L: añadir})[0])

    def test_formato(self):
        for cambiar, contiene in ((lambda l: l["huellas"].append({"hash": "md5:1", "motivo": "x"}), "`hash`"),
                                  (lambda l: l["archivos"].append({"patron": "*.dll"}), "texto"),
                                  (lambda l: l["usuarios"].append({"id": "x", "motivo": "x"}), "`id`"),
                                  (lambda l: l.update(otros=[]), "no existe")):
            with self.subTest(contiene=contiene):
                self.assertTrue(any(contiene in m for m in proponer(PROP_ID, {L: self.lista(cambiar)})))

    def test_sus_archivos_cuentan_en_los_parches_del_catalogo(self):
        juego = {"id": "j", "ediciones": [{"id": "e", "huella": [], "huellasParcheadas": [
            {"version": "1", "archivos": [{"ruta": "datos/firma.SIG"}]}]}]}
        despues = dict(CATALOGO, versionCatalogo=2, juegos=[juego])

        def leer(ruta, lado):
            return b(LISTA) if ruta == L else None
        motivos = comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(CATALOGO), json.dumps(despues),
                            Permisos(Rol.ADMINISTRADOR), leer_archivo=leer)
        self.assertEqual(1, len(motivos))
        self.assertIn("del canal @ornizen", motivos[0])
        self.assertIn("lista-negra.json", motivos[0])


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

    def test_un_miembros_json_dañado_en_main_para_al_robot(self):
        with tempfile.TemporaryDirectory() as carpeta:
            canal = pathlib.Path(carpeta, "canales", "x_y")
            canal.mkdir(parents=True)
            (canal / "miembros.json").write_bytes(b'{"esquema": 1, "miembros": [{"id": 1}]}')
            with self.assertRaises(ValueError):
                leer_canales(pathlib.Path(carpeta))


if __name__ == "__main__":
    unittest.main()
