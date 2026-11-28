"""La versión mínima del Modo equipo (`launcher.versionMinimaEquipo`, docs/canales.md §8.1)."""
import copy
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import version_equipo as ve  # noqa: E402
from permisos import Cambio, RUTA_CATALOGO, comprobar  # noqa: E402
from test_permisos import ADMIN, BASE, PROPIETARIO, catalogo, juego  # noqa: E402

MARCA = "\n\n<!-- parcheador: {} -->"


def con_minima(valor, donde="catalogo"):
    """(texto de `catalogo.json` de main, lector de archivos de main) con la versión mínima en un sitio u otro."""
    base = copy.deepcopy(BASE)
    programa = None
    if donde == "catalogo":
        base["launcher"]["versionMinimaEquipo"] = valor
    else:
        programa = json.dumps({"esquema": 1, "launcher": {"ultimaVersion": "0.5.0", "versionMinimaEquipo": valor}})

    def leer(ruta, lado):
        return programa.encode() if programa is not None and ruta == ve.RUTA_PARCHEADOR and lado == "antes" else None
    return json.dumps(base), leer


def revisar(permisos, minima, cuerpo, donde="catalogo"):
    antes, leer = con_minima(minima, donde)
    despues = json.loads(antes)
    despues["versionCatalogo"] += 1
    juego(despues).update(sinopsis="Cambiada")
    return comprobar([Cambio(RUTA_CATALOGO, "M")], antes, json.dumps(despues), permisos, leer_archivo=leer, cuerpo=cuerpo)


class Versiones(unittest.TestCase):
    def test_se_leen_como_la_app(self):
        self.assertEqual(([0, 4, 3], []), ve.leer_version("0.4.3"))
        self.assertEqual(([1, 2], ["beta", "2"]), ve.leer_version(" v1.2-beta.2+abc "))
        for malo in (None, "", "  ", "1.2.3.4.5", "1..2", "a.b", "1.2-", "1.2-be ta", "1.2-é", "１.２", "99999999999.0", 5):
            with self.subTest(malo):
                self.assertIsNone(ve.leer_version(malo))

    def test_se_comparan_como_la_app(self):
        menor_a_mayor = ["0.4", "0.4.1-alpha", "0.4.1-alpha.1", "0.4.1-alpha.beta", "0.4.1-beta", "0.4.1-beta.2",
                         "0.4.1-beta.11", "0.4.1-rc.1", "0.4.1", "0.4.2", "0.10.0", "1"]
        for i, a in enumerate(menor_a_mayor):
            for j, b in enumerate(menor_a_mayor):
                with self.subTest(a=a, b=b):
                    r = ve.comparar(ve.leer_version(a), ve.leer_version(b))
                    self.assertEqual((i > j) - (i < j), (r > 0) - (r < 0))
        self.assertEqual(0, ve.comparar(ve.leer_version("1.2"), ve.leer_version("v1.2.0.0+x")))
        self.assertEqual(0, ve.comparar(ve.leer_version("1.0.0-rc.01"), ve.leer_version("1.0.0-rc.1")))

    def test_vale_la_ultima_marca_y_un_cuerpo_enorme_no_se_mira(self):
        self.assertEqual("0.4.4", ve.version_de("<!-- parcheador: 0.1.0 -->\ntexto" + MARCA.format("0.4.4")))
        self.assertIsNone(ve.version_de("sin marca"))
        self.assertIsNone(ve.version_de(None))
        self.assertIsNone(ve.version_de("x" * 80_000 + MARCA.format("0.4.4")))


class Propuestas(unittest.TestCase):
    def test_sin_version_minima_no_se_mira_nada(self):
        for minima in ("", "   ", "no-es-version", None):
            with self.subTest(minima):
                self.assertEqual([], revisar(ADMIN, minima, None))

    def test_con_la_version_justa_o_mayor_pasa(self):
        for donde in ("catalogo", "programa"):
            for usada in ("0.4.4", "v0.4.4", "0.5.0", "0.4.4+compilacion"):
                with self.subTest(donde=donde, usada=usada):
                    self.assertEqual([], revisar(ADMIN, "0.4.4", "Cambio." + MARCA.format(usada), donde))

    def test_sin_marca_o_con_una_version_vieja_se_rechaza(self):
        casos = {
            "": "no dice con qué parcheador se hizo",
            "Cambio a mano en GitHub.": "no dice con qué parcheador se hizo",
            "x" + MARCA.format("no.es.version"): "no dice con qué parcheador se hizo",
            MARCA.format("0.4.3"): "se hizo con el parcheador v0.4.3",
            MARCA.format("0.4.4-beta.1"): "se hizo con el parcheador v0.4.4-beta.1",
            # La última marca manda: copiar una marca nueva arriba del texto no sirve.
            MARCA.format("0.9.0") + MARCA.format("0.4.0"): "se hizo con el parcheador v0.4.0",
        }
        for donde in ("catalogo", "programa"):
            for cuerpo, esperado in casos.items():
                with self.subTest(donde=donde, cuerpo=cuerpo[-40:]):
                    motivos = revisar(ADMIN, "0.4.4", cuerpo, donde)
                    self.assertEqual(1, len(motivos), motivos)
                    self.assertIn(esperado, motivos[0])
                    self.assertIn("hace falta la v0.4.4 o posterior", motivos[0])

    def test_el_dueno_no_tiene_version_minima(self):
        self.assertEqual([], revisar(PROPIETARIO, "0.4.4", "Hecho a mano en GitHub.", "programa"))

    def test_programa_manda_sobre_el_catalogo_y_uno_ilegible_no_bloquea(self):
        antes, _ = con_minima("0.9.0")  # el catálogo dice 0.9.0…
        _, leer = con_minima("0.4.4", "programa")  # …pero programa/parcheador.json (la fuente) dice 0.4.4

        despues = json.loads(antes)
        despues["versionCatalogo"] += 1
        self.assertEqual([], comprobar([Cambio(RUTA_CATALOGO, "M")], antes, json.dumps(despues), ADMIN,
                                       leer_archivo=leer, cuerpo=MARCA.format("0.4.4")))
        self.assertIsNone(ve.minima("{roto", json.dumps(catalogo())))
        self.assertIsNone(ve.minima("[]", None))
        self.assertIsNone(ve.minima('{"launcher": {"versionMinimaEquipo": 4}}', None))


if __name__ == "__main__":
    unittest.main()
