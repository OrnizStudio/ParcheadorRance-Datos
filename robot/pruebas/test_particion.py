"""Fase B: partir `catalogo.json` en archivos sueltos y volver a juntarlo da el mismo catálogo (`robot/particion.py`)."""

import copy
import json
import pathlib
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import lector_app  # noqa: E402
import particion  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[2]
HASH = "blake3:" + "a" * 64
HUELLA = {"ruta": "Juego.exe", "tamano": 1, "hashParcial": HASH, "hash": HASH}


def todo_el_modelo() -> dict:
    """Un catálogo con todos los campos de `Juego` y `Edicion` del modelo rellenos (y con textos difíciles)."""
    edicion = {
        "id": "steam", "nombre": "Steam «ñ» 🎌", "grupo": "pc", "notaEdicion": "nota\nen dos líneas",
        "disponibilidad": "disponible", "pruebas": False, "huella": [HUELLA],
        "huellasParcheadas": [{"version": "1.0.0", "archivos": [HUELLA]}], "ignorar": ["*.log"],
        "ignorados": {"archivos": 3, "bytes": 2 ** 40}, "estado": "publico", "progreso": {"traduccion": 100},
        "parche": {"version": "1.0.0", "paquetes": []},
        "versiones": [{"version": "1.0.0", "estado": "publica", "fecha": "2026-11-20", "paquete": {"url": "https://e/p.zip"}},
                      {"version": "0.9.0", "estado": "retirada", "motivo": "fallo", "motivoPublico": True}],
        "imagenes": {"portada": "p.webp"}, "etiquetas": ["traduccion"], "contenido": {"texto": True, "testing": "x"},
        "lanzar": {"steam": True, "argumentos": "-x"}, "tiendas": [{"nombre": "Steam", "url": "https://s", "gratis": False}],
        "restricciones": {"censura": "si"}, "avisoRestricciones": "aviso",
    }
    juego = {
        "id": "rance-x", "habilitado": True, "disponibilidad": "disponible", "pruebas": False, "orden": 3,
        "titulo": "Rance X", "tituloCorto": "RX", "tituloOriginal": "ランス・クエスト", "relacionado": "rance-9",
        "etiquetas": ["adultos", "rpg"], "estado": "publico", "progreso": {"traduccion": 50, "revision": 10},
        "sinopsis": "‮bidi‬ y \u0000 escapado", "imagenes": {"icono": "i.png", "banner": "b.png"},
        "creditos": [{"rol": "Traducción", "personas": ["ana", "luis"]}],
        "deteccion": {"steamAppId": 2 ** 40, "gogId": "123", "ejecutables": ["Rance10.exe"]},
        "ediciones": [edicion, dict(copy.deepcopy(edicion), id="dl-jp", nombre="DL")],
        "opciones": [{"id": "censura", "nombre": "Censura", "tipo": "lista", "valores": [{"id": "si", "fija": {"a": "b"}}]}],
        "parche": {"version": "1.4.0", "fecha": "2026-11-20", "notas": "n", "pruebas": False,
                   "paquetes": [{"edicion": "steam", "url": "https://e/p.zip", "tamano": 10, "hash": HASH}]},
    }
    return {
        "esquema": 1, "versionCatalogo": 31,
        "launcher": {"ultimaVersion": "0.2.3", "url": "https://e/l.zip", "tamano": 5, "hash": HASH, "novedades": ["a"]},
        "grupo": {"nombre": "canal1", "logo": "l.png", "enlaces": [{"tipo": "web", "url": "https://w"}]},
        "etiquetas": [{"id": "rpg", "nombre": "RPG", "color": "#fff"}],
        "juegos": [juego, {"id": "prueba", "orden": 9999, "pruebas": True}, {"id": "a", "ediciones": None},
                   {"id": "b", "ediciones": []}],
    }


def ida_y_vuelta(catalogo):
    archivos = particion.partir(catalogo)
    for ruta, datos in archivos.items():
        lector_app.leer(datos)  # cada archivo suelto se lee con el JSON estricto
        assert datos.endswith(b"\n") and not datos.startswith(b"\xef\xbb\xbf"), ruta
    return archivos, particion.juntar(archivos, catalogo["versionCatalogo"])


class IdaYVuelta(unittest.TestCase):
    def test_el_catalogo_de_main(self):
        original = lector_app.leer((RAIZ / particion.RUTA_CATALOGO).read_bytes())
        _, vuelta = ida_y_vuelta(original)
        self.assertTrue(particion.mismo_catalogo(original, vuelta))
        self.assertEqual([], lector_app.errores_de_la_app(vuelta))

    def test_todos_los_campos_del_modelo(self):
        original = todo_el_modelo()
        archivos, vuelta = ida_y_vuelta(original)
        self.assertTrue(particion.mismo_catalogo(original, vuelta))
        # Los juegos salen en el orden en que los enseña la app.
        self.assertEqual(["a", "b", "rance-x", "prueba"], [j["id"] for j in vuelta["juegos"]])
        # Sin la clave, `null` o lista vacía: cada uno vuelve como estaba.
        por_id = {j["id"]: j for j in vuelta["juegos"]}
        self.assertNotIn("ediciones", por_id["prueba"])
        self.assertIsNone(por_id["a"]["ediciones"])
        self.assertEqual([], por_id["b"]["ediciones"])
        # Lo central y lo del canal, cada cosa en su archivo.
        central = json.loads(archivos["juegos/rance-x/juego.json"])
        self.assertEqual({"canal": "ornizen", "cuenta": None, "fecha": None}, central["alta"])
        self.assertEqual("activo", central["estado"])
        self.assertEqual(["steam", "dl-jp"], central["ediciones"])
        self.assertNotIn("parche", central)
        parche = json.loads(archivos["canales/ornizen/parches/rance-x.json"])
        self.assertEqual("rance-x", parche["juego"])
        self.assertEqual("publico", parche["estado"])
        self.assertNotIn("huella", json.dumps(parche["ediciones"]).replace("huellasParcheadas", ""))
        self.assertEqual(2, len(json.loads(archivos["canales/ornizen/parches/rance-x.json"])["ediciones"][0]["versiones"]))
        self.assertIn("huella", json.loads(archivos["juegos/rance-x/ediciones/steam.json"]))
        self.assertEqual({"esquema": 1, "etiquetas": original["etiquetas"]}, json.loads(archivos["normas/etiquetas.json"]))
        self.assertEqual({"esquema": 1, "launcher": original["launcher"], "grupo": original["grupo"]},
                         json.loads(archivos["programa/parcheador.json"]))

    def test_vacio(self):
        for catalogo in ({"esquema": 1, "versionCatalogo": 1}, {"esquema": 1, "versionCatalogo": 1, "juegos": [], "etiquetas": []}):
            with self.subTest(catalogo=catalogo):
                archivos, vuelta = ida_y_vuelta(catalogo)
                self.assertEqual({"normas/etiquetas.json", "programa/parcheador.json"}, set(archivos))
                self.assertEqual([], vuelta["juegos"])
                self.assertTrue(particion.mismo_catalogo(catalogo, vuelta))

    def test_cinco_mil_juegos_con_tres_ediciones(self):
        base = todo_el_modelo()["juegos"][0]
        juegos = []
        for i in range(5000):
            juego = copy.deepcopy(base)
            juego["id"], juego["orden"] = f"juego-{i:05}", i % 7
            juego["ediciones"].append(dict(copy.deepcopy(juego["ediciones"][0]), id="gog"))
            juegos.append(juego)
        original = {"esquema": 1, "versionCatalogo": 2, "juegos": juegos}
        inicio = time.monotonic()
        archivos, vuelta = ida_y_vuelta(original)
        self.assertLess(time.monotonic() - inicio, 60)
        self.assertEqual(5000 * 5 + 2, len(archivos))
        self.assertTrue(particion.mismo_catalogo(original, vuelta))


class LoQueNoSePuedePartir(unittest.TestCase):
    def partir(self, cambiar):
        catalogo = todo_el_modelo()
        cambiar(catalogo)
        with self.assertRaises(particion.ErrorParticion) as error:
            particion.partir(catalogo)
        return str(error.exception)

    def test_ids_que_no_valen_como_archivo(self):
        for malo in ("../x", "a/b", "a\\b", "", " a", "a ", ".oculto", "x" * 101, "CON", "nul.json", "com1", "lpt9.x",
                     "a..b", "ñ", None, 5, "a\u0000"):
            with self.subTest(id=malo):
                self.assertIn("no vale como nombre", self.partir(lambda c: c["juegos"][0].update(id=malo)))
                self.assertIn("no vale como nombre",
                              self.partir(lambda c: c["juegos"][0]["ediciones"][0].update(id=malo)))
        for bueno in ("a", "x" * 100, "rance_10.v2", "Rance-X", "console"):
            self.assertTrue(particion.id_valido(bueno), bueno)

    def test_repetidos_aunque_solo_cambien_mayusculas(self):
        self.assertIn("repetido", self.partir(lambda c: c["juegos"].append({"id": "Rance-X"})))
        self.assertIn("repetido", self.partir(lambda c: c["juegos"][0]["ediciones"].append({"id": "STEAM"})))

    def test_campo_que_no_es_del_modelo(self):
        self.assertIn("deUnaAppMasNueva", self.partir(lambda c: c["juegos"][0].update(deUnaAppMasNueva=1)))
        self.assertIn("x", self.partir(lambda c: c["juegos"][0]["ediciones"][0].update(x=1)))
        self.assertIn("raro", self.partir(lambda c: c.update(raro=1)))

    def test_topes(self):
        self.assertIn("tope", self.partir(lambda c: c["juegos"][0].update(
            ediciones=[{"id": f"e{i}"} for i in range(particion.TOPE_EDICIONES + 1)])))
        with self.assertRaises(particion.ErrorParticion):
            particion.partir({"esquema": 2, "versionCatalogo": 1})


class LoQueNoSePuedeJuntar(unittest.TestCase):
    def setUp(self):
        self.archivos = particion.partir(todo_el_modelo())

    def juntar(self):
        return particion.juntar(self.archivos, 32)

    def poner(self, ruta, valor):
        self.archivos[ruta] = particion.texto_json(valor)

    def leer(self, ruta):
        return json.loads(self.archivos[ruta])

    def falla(self, texto):
        with self.assertRaises(particion.ErrorParticion) as error:
            self.juntar()
        self.assertIn(texto, str(error.exception))

    def test_parche_de_un_juego_que_no_existe(self):
        del self.archivos["juegos/rance-x/juego.json"]
        self.falla("no existe")

    def test_el_nombre_del_archivo_manda(self):
        self.poner("canales/ornizen/parches/rance-x.json", dict(self.leer("canales/ornizen/parches/rance-x.json"), juego="otro"))
        self.falla("nombre del archivo")
        self.setUp()
        self.poner("juegos/rance-x/juego.json", dict(self.leer("juegos/rance-x/juego.json"), id="otro"))
        self.falla("nombre de la carpeta")
        self.setUp()
        self.poner("juegos/rance-x/ediciones/steam.json", dict(self.leer("juegos/rance-x/ediciones/steam.json"), id="gog"))
        self.falla("nombre del archivo")

    def test_ediciones_que_no_cuadran(self):
        parche = self.leer("canales/ornizen/parches/rance-x.json")
        parche["ediciones"].append({"id": "fantasma"})
        self.poner("canales/ornizen/parches/rance-x.json", parche)
        self.falla("ediciones que el juego no tiene")
        self.setUp()
        del self.archivos["juegos/rance-x/ediciones/dl-jp.json"]
        self.falla("no tiene archivo")
        self.setUp()
        self.poner("juegos/rance-x/juego.json", dict(self.leer("juegos/rance-x/juego.json"), ediciones=["steam", "steam"]))
        self.falla("repetido")
        self.setUp()
        self.poner("juegos/rance-x/juego.json", dict(self.leer("juegos/rance-x/juego.json"), ediciones="steam"))
        self.falla("lista de ids")

    def test_json_roto_o_con_claves_repetidas(self):
        self.archivos["juegos/rance-x/juego.json"] = b'{"id": "rance-x", "id": "x"}'
        self.falla("juegos/rance-x/juego.json")
        self.setUp()
        self.archivos["normas/etiquetas.json"] = b"\xef\xbb\xbf{}"
        self.falla("BOM")

    def test_retirado_o_bloqueado_no_se_ofrece(self):
        for estado in ("retirado", "bloqueado"):
            with self.subTest(estado=estado):
                self.setUp()
                self.poner("juegos/rance-x/juego.json", dict(self.leer("juegos/rance-x/juego.json"), estado=estado))
                self.assertNotIn("rance-x", [j["id"] for j in self.juntar()["juegos"]])

    def test_un_juego_sin_parche_del_canal_oficial_no_entra(self):
        del self.archivos["canales/ornizen/parches/rance-x.json"]
        self.poner("canales/otro/parches/rance-x.json", {"esquema": 1, "juego": "rance-x"})
        self.assertNotIn("rance-x", [j["id"] for j in self.juntar()["juegos"]])

    def test_nombre_y_sinopsis_del_canal_encima(self):
        parche = self.leer("canales/ornizen/parches/rance-x.json")
        parche.update(titulo="Rance X (fan)", sinopsis="De la traducción")
        self.poner("canales/ornizen/parches/rance-x.json", parche)
        juego = next(j for j in self.juntar()["juegos"] if j["id"] == "rance-x")
        self.assertEqual(("Rance X (fan)", "De la traducción", "RX"), (juego["titulo"], juego["sinopsis"], juego["tituloCorto"]))

    def test_lo_que_no_es_suyo_no_se_mira(self):
        self.archivos["canales/ornizen/parches/sub/x.json"] = b"basura"
        self.archivos["canales/ornizen/parches/LEEME.md"] = b"basura"
        self.archivos["juegos/huerfano/juego.json"] = b"basura"
        self.assertEqual(4, len(self.juntar()["juegos"]))


class Migracion(unittest.TestCase):
    def test_escribe_y_no_pisa(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = pathlib.Path(carpeta)
            (raiz / "catalogo").mkdir()
            (raiz / particion.RUTA_CATALOGO).write_bytes(particion.texto_json(todo_el_modelo()))
            self.assertEqual(0, particion.main(["partir", carpeta]))
            self.assertTrue((raiz / "juegos/rance-x/ediciones/dl-jp.json").is_file())
            self.assertEqual(1, particion.main(["partir", carpeta]))  # ya existen: no se pisa nada
            self.assertEqual(2, particion.main(["otra-cosa", carpeta]))


if __name__ == "__main__":
    unittest.main()
