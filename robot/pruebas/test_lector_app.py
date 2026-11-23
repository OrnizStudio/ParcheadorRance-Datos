"""Lo que la app no puede leer, el robot no lo deja publicar (tercera revisión, N1).

Cada caso es un catálogo que el robot aceptaba y con el que todos los parcheadores se quedaban sin catálogo nuevo.
"""

import copy
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import lector_app  # noqa: E402
from permisos import Cambio, Permisos, Rol, RUTA_CATALOGO, comprobar, validar_catalogo  # noqa: E402

HASH = "blake3:" + "a" * 64
BASE = {
    "esquema": 1, "versionCatalogo": 30, "etiquetas": [],
    "juegos": [{
        "id": "juego1", "habilitado": True, "titulo": "Juego", "progreso": {"traduccion": 50},
        "deteccion": {"steamAppId": 123, "gogId": "456"},
        "ediciones": [{"id": "steam", "huella": [{"ruta": "Juego.exe", "tamano": 1, "hashParcial": HASH, "hash": HASH}],
                       "lanzar": {"ejecutable": "Juego.exe"}, "restricciones": {"censura": "si"}}],
        "opciones": [{"id": "censura", "valores": [{"id": "si", "fija": {}}]}],
        "parche": {"version": "1.0.0", "paquetes": [
            {"edicion": "steam", "url": "https://example.org/p.zip", "tamano": 10, "hash": HASH}]},
    }],
}
ADMIN = Permisos(Rol.ADMINISTRADOR)
COLABORADOR = Permisos(Rol.COLABORADOR)
PROPIETARIO = Permisos(Rol.PROPIETARIO)


def con(cambiar, version=31):
    cat = copy.deepcopy(BASE)
    cat["versionCatalogo"] = version
    cambiar(cat)
    return cat


def motivos_de(datos, antes=None, puede_rescatar=False):
    return validar_catalogo(datos, BASE if antes is None else antes, puede_rescatar)[1]


def juego(c):
    return c["juegos"][0]


def edicion(c):
    return c["juegos"][0]["ediciones"][0]


class Version(unittest.TestCase):
    def test_sube_uno(self):
        self.assertEqual([], motivos_de(json.dumps(con(lambda c: None))))

    def test_no_baja_ni_se_queda(self):
        for v in (30, 29, 1):
            with self.subTest(v=v):
                self.assertIn("tiene que subir", motivos_de(json.dumps(con(lambda c: None, v)))[0])

    def test_no_salta_mas_de_mil(self):
        self.assertEqual([], motivos_de(json.dumps(con(lambda c: None, 30 + lector_app.SALTO_MAXIMO_VERSION))))
        motivos = motivos_de(json.dumps(con(lambda c: None, 31 + lector_app.SALTO_MAXIMO_VERSION)))
        self.assertIn("Basta con subirlo 1 (a 31)", motivos[0])

    def test_nunca_cerca_del_tope_del_int(self):
        antes = con(lambda c: None, lector_app.VERSION_MAXIMA - 1)
        self.assertEqual([], motivos_de(json.dumps(con(lambda c: None, lector_app.VERSION_MAXIMA)), antes))
        for v in (lector_app.VERSION_MAXIMA + 1, 2 ** 31 - 1, 2 ** 31, 2 ** 63, 0, -5):
            with self.subTest(v=v):
                self.assertTrue(motivos_de(json.dumps(con(lambda c: None, v)), antes))

    def test_desde_una_version_absurda_solo_rescata_quien_manda_y_poco(self):
        # main ya envenenado (de antes de este arreglo): solo quien manda en todo lo devuelve a un valor normal, incluso
        # bajando, y como mucho al de rescate (cuarta revisión, 2.4): nadie aprovecha el arreglo para volver a congelarlo.
        for absurda in (2 ** 31 - 1, 2 ** 31, 10 ** 29, 0, "31", None):
            with self.subTest(absurda=absurda):
                antes = con(lambda c: c.update(versionCatalogo=absurda))
                for v in (1, 31, lector_app.VERSION_RESCATE):
                    self.assertEqual([], motivos_de(json.dumps(con(lambda c: None, v)), antes, puede_rescatar=True))
                    self.assertIn("Arreglarlo lo hace solo", motivos_de(json.dumps(con(lambda c: None, v)), antes)[0])
                for v in (lector_app.VERSION_RESCATE + 1, lector_app.VERSION_MAXIMA):
                    self.assertIn("como mucho a", motivos_de(json.dumps(con(lambda c: None, v)), antes, True)[0])

    def test_main_ilegible_solo_lo_toca_quien_manda(self):
        # Sin catálogo legible en main no se pueden comprobar los permisos campo a campo (cuarta revisión, 2.5).
        for antes in ('{"esquema": 1, "versionCatalogo": ' + "9" * 5000 + "}", "\ufeff" + json.dumps(BASE),
                      "no es JSON", "[1, 2]", None):
            with self.subTest(antes=str(antes)[:20]):
                for quien in (ADMIN, COLABORADOR):
                    motivos = comprobar([Cambio(RUTA_CATALOGO, "M")], antes, json.dumps(con(lambda c: None, 31)), quien)
                    self.assertEqual(1, len(motivos), motivos)
                    self.assertIn("no se puede leer", motivos[0])

    def test_main_ilegible_no_bloquea(self):
        # Un main con un número de 5000 cifras no tumba al robot: se lee como «no hay antes».
        antes = '{"esquema": 1, "versionCatalogo": ' + "9" * 5000 + "}"
        motivos = comprobar([Cambio(RUTA_CATALOGO, "M")], antes, json.dumps(con(lambda c: None, 31)), PROPIETARIO)
        self.assertEqual([], motivos)

    def test_no_es_un_entero(self):
        for v in ("31", 31.0, True, None, [31]):
            with self.subTest(v=v):
                self.assertTrue(motivos_de(json.dumps(con(lambda c: c.update(versionCatalogo=v)))))
        sin = con(lambda c: None)
        del sin["versionCatalogo"]
        self.assertTrue(motivos_de(json.dumps(sin)))


class Bytes(unittest.TestCase):
    def test_utf8_invalido(self):
        datos = json.dumps(con(lambda c: juego(c).update(sinopsis="ñ")), ensure_ascii=False).encode("utf-8")
        for malo in (datos.replace("ñ".encode(), b"\xff"), datos.replace("ñ".encode(), b"\xc3"),
                     datos.replace("ñ".encode(), b"\xed\xa0\x80")):  # el último: un sustituto codificado en UTF-8
            with self.subTest(malo=malo[-60:]):
                self.assertIn("no es UTF-8 válido", motivos_de(malo)[0])

    def test_bom(self):
        self.assertIn("BOM", motivos_de(b"\xef\xbb\xbf" + json.dumps(con(lambda c: None)).encode())[0])

    def test_sustituto_suelto(self):
        for texto in ("\ud800", "a\udfffb", "\udc00\ud800"):
            for poner in (lambda c, t: juego(c).update(sinopsis=t), lambda c, t: c.update({t: 1}),
                          lambda c, t: edicion(c)["restricciones"].update({"x": t})):
                with self.subTest(texto=repr(texto)):
                    cat = con(lambda c: poner(c, texto))
                    self.assertIn("carácter partido", motivos_de(json.dumps(cat))[0])

    def test_pareja_de_sustitutos_valida(self):
        # «\ud83d\ude00» es 😀 bien escrito: eso sí vale.
        texto = json.dumps(con(lambda c: juego(c).update(sinopsis="😀")))
        self.assertIn("\\ud83d\\ude00", texto)
        self.assertEqual([], motivos_de(texto))

    def test_claves_repetidas_nan_y_numeros_enormes(self):
        normal = json.dumps(con(lambda c: None))
        casos = {
            "repite la clave": normal.replace('"esquema": 1', '"esquema": 1, "esquema": 1'),
            "NaN": normal.replace('"titulo": "Juego"', '"titulo": NaN'),
            "Infinity": normal.replace('"titulo": "Juego"', '"titulo": -Infinity'),
            "demasiado grande": normal.replace('"titulo": "Juego"', '"titulo": 1e400'),
            "cifras": normal.replace('"versionCatalogo": 31', '"versionCatalogo": ' + "1" * 5000),
        }
        for esperado, texto in casos.items():
            with self.subTest(esperado):
                self.assertIn(esperado, motivos_de(texto)[0])

    def test_anidacion(self):
        hondo = lambda n: json.dumps(con(lambda c: c.update(extra=json.loads("[" * n + "]" * n))))  # noqa: E731
        self.assertEqual([], motivos_de(hondo(lector_app.PROFUNDIDAD_MAXIMA - 1)))
        self.assertIn("niveles", motivos_de(hondo(lector_app.PROFUNDIDAD_MAXIMA))[0])
        self.assertIn("niveles", motivos_de("[" * 100000 + "]" * 100000)[0])

    def test_la_propuesta_en_bytes_igual_que_en_texto(self):
        cat = json.dumps(con(lambda c: juego(c).update(sinopsis="ñandú 😀")), ensure_ascii=False)
        self.assertEqual([], motivos_de(cat))
        self.assertEqual([], motivos_de(cat.encode("utf-8")))


class Tipos(unittest.TestCase):
    """Los tipos de `Catalogo.cs`/`Juego.cs`: lo que System.Text.Json no puede convertir, no entra."""

    def assertRechaza(self, cambiar, texto=None):
        motivos = motivos_de(json.dumps(con(cambiar)))
        self.assertTrue(motivos, "el robot lo aceptaba")
        if texto:
            self.assertIn(texto, motivos[0])

    def test_progreso_como_texto(self):
        self.assertRechaza(lambda c: juego(c).update(progreso="x"), "`progreso` tiene que ser un objeto")
        self.assertRechaza(lambda c: juego(c)["progreso"].update(traduccion="50"), "número entero")
        self.assertRechaza(lambda c: juego(c)["progreso"].update(traduccion=50.5), "número entero")
        self.assertRechaza(lambda c: juego(c)["progreso"].update(traduccion=2 ** 31), "no cabe")

    def test_enteros_y_booleanos(self):
        self.assertRechaza(lambda c: juego(c).update(orden=True), "número entero")
        self.assertRechaza(lambda c: juego(c).update(orden=None), "número entero")
        self.assertRechaza(lambda c: juego(c).update(habilitado=1), "`true` o `false`")
        self.assertRechaza(lambda c: juego(c).update(habilitado=None), "`true` o `false`")
        self.assertRechaza(lambda c: juego(c).update(habilitado="true"), "`true` o `false`")
        self.assertRechaza(lambda c: juego(c)["parche"]["paquetes"][0].update(tamano=2 ** 63), "no cabe")

    def test_nulos_que_la_app_si_acepta(self):
        for campo in ("titulo", "progreso", "parche", "imagenes", "creditos", "etiquetas", "tituloOriginal"):
            with self.subTest(campo=campo):
                self.assertEqual([], motivos_de(json.dumps(con(lambda c: juego(c).update({campo: None})))))
        self.assertEqual([], motivos_de(json.dumps(con(lambda c: juego(c)["deteccion"].update(steamAppId=None)))))

    def test_textos_listas_y_diccionarios(self):
        self.assertRechaza(lambda c: juego(c).update(titulo=5), "texto")
        self.assertRechaza(lambda c: juego(c).update(etiquetas="beta"), "lista")
        self.assertRechaza(lambda c: juego(c).update(etiquetas=[None]), "es `null`")
        self.assertRechaza(lambda c: juego(c).update(ediciones=[None]), "es `null`")
        self.assertRechaza(lambda c: edicion(c).update(restricciones={"censura": 1}), "objeto con textos")
        self.assertRechaza(lambda c: edicion(c).update(restricciones=[]), "objeto con textos")
        self.assertRechaza(lambda c: c.update(launcher=[]), "objeto")
        self.assertRechaza(lambda c: c.update(grupo="Ornizen"), "objeto")

    def test_gog_id(self):
        for valor in ("456", 456, None, "-3"):
            with self.subTest(valor=valor):
                self.assertEqual([], motivos_de(json.dumps(con(lambda c: juego(c)["deteccion"].update(gogId=valor)))))
        for valor in ("", "abc", " 456", "4.5", "١٢٣", True, 4.5):
            with self.subTest(valor=valor):
                self.assertRechaza(lambda c: juego(c)["deteccion"].update(gogId=valor))

    def test_obligatorios_y_hashes(self):
        for campo in ("ruta", "tamano", "hashParcial", "hash"):
            with self.subTest(campo=campo):
                self.assertRechaza(lambda c: edicion(c)["huella"][0].pop(campo), "obligatorio")
        for hash_malo in ("", "blake3", "blake3:", ":aa", "blake3:abc", "blake3:zz", None, 5):
            with self.subTest(hash_malo=hash_malo):
                self.assertRechaza(lambda c: edicion(c)["huella"][0].update(hashParcial=hash_malo), "hash")
        sin = con(lambda c: None)
        del sin["esquema"]
        self.assertIn("obligatorio", motivos_de(json.dumps(sin))[0])

    def test_esquema(self):
        for v in (0, 2, -1):
            with self.subTest(v=v):
                self.assertRechaza(lambda c: c.update(esquema=v), "solo entiende el 1")

    def test_lo_que_comprueba_lector_catalogo(self):
        self.assertRechaza(lambda c: edicion(c)["huella"][0].update(ruta="../x.dll"), "ruta de huella")
        self.assertRechaza(lambda c: edicion(c)["huella"][0].update(ruta="C:/x.dll"), "ruta de huella")
        self.assertRechaza(lambda c: edicion(c)["huella"][0].update(ruta="dir/.. /x"), "ruta de huella")
        self.assertRechaza(lambda c: edicion(c)["huella"][0].update(ruta="/x"), "ruta de huella")
        self.assertRechaza(lambda c: edicion(c)["lanzar"].update(ejecutable="..\\x.exe"), "ejecutable")
        self.assertRechaza(lambda c: edicion(c).update(huellasParcheadas=[{"version": " "}]), "sin versión")
        self.assertRechaza(lambda c: juego(c)["opciones"].append({"id": "censura"}), "opción")
        self.assertRechaza(lambda c: juego(c)["opciones"].append({"id": ""}), "opción")

    def test_desconocidos_y_enums_se_toleran(self):
        # Como la app: campos que no conoce y estados nuevos no impiden leer el catálogo.
        cat = con(lambda c: juego(c).update(estado=7, disponibilidad="nuevo", campoFuturo={"x": [1, 2]}))
        self.assertEqual([], motivos_de(json.dumps(cat)))

    def test_el_catalogo_publicado_hoy_se_lee(self):
        # Los catálogos de las pruebas de concepto de la revisión y el de hoy: el arreglo no rompe lo que hay.
        self.assertEqual([], lector_app.errores_de_la_app(BASE))


class EnLaPropuesta(unittest.TestCase):
    def test_un_colaborador_no_congela_el_catalogo(self):
        for cambiar in (lambda c: c.update(versionCatalogo=2 ** 31 - 1), lambda c: juego(c).update(progreso="x"),
                        lambda c: juego(c).update(sinopsis="\ud800")):
            with self.subTest():
                motivos = comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(BASE), json.dumps(con(cambiar)),
                                    COLABORADOR)
                self.assertTrue(motivos)

    def test_tampoco_el_propietario(self):
        motivos = comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(BASE),
                            json.dumps(con(lambda c: None, 2 ** 31 - 1)), PROPIETARIO)
        self.assertTrue(motivos)


if __name__ == "__main__":
    unittest.main()
