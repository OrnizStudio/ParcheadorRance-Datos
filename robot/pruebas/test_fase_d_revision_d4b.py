"""Revisión de D4b (#51): de quién es cada repositorio de `paquetes`, expresiones sin `$`, el tope de
`catalogo/canales.json` (que no frena el catálogo) y `Я`."""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import canales  # noqa: E402
import particion  # noqa: E402
import permisos  # noqa: E402
import publicar  # noqa: E402
from test_fase_d_publicar import base  # noqa: E402
from test_particion import todo_el_modelo  # noqa: E402
from test_publicado_app import canal_json  # noqa: E402


def canal(cid="rance_es", **cambios):
    objeto = json.loads(canal_json(cid))
    objeto.update(cambios)
    return objeto


def errores(cid, paquetes):
    return canales.validar_canal(canal(cid, paquetes=paquetes), cid, f"canales/{cid}/canal.json")


class RepositoriosDePaquetes(unittest.TestCase):
    def test_los_de_OrnizStudio_solo_el_oficial(self):
        for repo in ("OrnizStudio/Ornizen-Parches", "ornizstudio/parcheadorrance-datos", "ORNIZSTUDIO/x"):
            with self.subTest(repo=repo):
                self.assertTrue(any("OrnizStudio" in e for e in errores("rance_es", [repo])))
                self.assertEqual([], errores("ornizen", [repo]))
        # Una cuenta que solo empieza igual no es la organización.
        self.assertEqual([], errores("rance_es", ["OrnizStudio2/x"]))

    def test_sin_repetir_sin_distinguir_mayusculas(self):
        self.assertTrue(any("sin repetir" in e for e in errores("rance_es", ["A/B", "a/b"])))
        self.assertEqual([], errores("rance_es", ["a/b", "a/c"]))

    def test_el_de_otro_canal_de_main_no(self):
        de_otros = {"kagami/paquetes": "kagamifs"}
        self.assertTrue(canales.repositorios_ajenos(["Kagami/Paquetes"], "rance_es", de_otros))
        self.assertIn("@kagamifs", canales.repositorios_ajenos(["kagami/paquetes"], "rance_es", de_otros)[0])
        # El propio, sí; y lo que ya tenía no frena otros cambios.
        self.assertEqual([], canales.repositorios_ajenos(["kagami/paquetes"], "kagamifs", de_otros))
        self.assertEqual([], canales.repositorios_ajenos(["kagami/paquetes"], "rance_es", de_otros, ["KAGAMI/paquetes"]))
        # Entradas raras: ni fallan ni cuentan.
        self.assertEqual([], canales.repositorios_ajenos("no es lista", "rance_es", de_otros))
        self.assertEqual([], canales.repositorios_ajenos([1, None], "rance_es", de_otros, "nada"))

    def test_por_el_robot_completo(self):
        main = {"canales/kagamifs/canal.json": canal_json("kagamifs", paquetes=["kagami/paquetes"]),
                "canales/rance_es/canal.json": canal_json("rance_es")}
        de_otros = permisos._paquetes_de(main)
        self.assertEqual({"kagami/paquetes": "kagamifs"}, de_otros)
        antes = canal("rance_es")
        for paquetes, rechaza in ((["Kagami/Paquetes"], True), (["OrnizStudio/x"], True), (["mio/parches"], False)):
            with self.subTest(paquetes=paquetes):
                motivos = canales._comprobar_canal_json("rance_es", "canales/rance_es/canal.json", antes,
                                                        canal("rance_es", paquetes=paquetes), 4,
                                                        paquetes_de_otros=de_otros)
                self.assertEqual(rechaza, bool(motivos), motivos)
        # Un canal.json de main ilegible no rompe la lista.
        self.assertEqual({}, permisos._paquetes_de({"canales/x/canal.json": b"{", "canales/y/canal.json": b"[]"}))

    def test_al_publicar_por_si_acaso_se_quitan(self):
        archivos = dict(base())
        archivos["canales/rance_es/canal.json"] = canal_json("rance_es", paquetes=["OrnizStudio/Ornizen-Parches", "rance-es/parches"])
        archivos["canales/viejo/canal.json"] = canal_json("viejo", paquetes=["Rance-ES/Parches", "viejo/parches"])
        entradas, _ = publicar.canales_publicados(archivos)
        self.assertEqual([], entradas["rance_es"]["paquetes"])
        self.assertEqual(["viejo/parches"], entradas["viejo"]["paquetes"])


class SinSaltoAlFinal(unittest.TestCase):
    def test_ninguna_acepta_un_salto_de_linea_final(self):
        for expresion, valido in ((canales.REPOSITORIO, "a/x"), (canales.ID_CANAL, "abc"),
                                  (canales.CUENTA_GITHUB, "ana"), (canales.FECHA, "2026-11-25"),
                                  (canales.HASH_VALIDO, "blake3:" + "0" * 64), (canales.RUTA_SEGURA, "logo.png"),
                                  (permisos.ID_VALIDO, "rance"), (permisos.HASH_VALIDO, "blake3:" + "0" * 64),
                                  (permisos.SHA, "0" * 40)):
            with self.subTest(expresion=expresion.pattern):
                self.assertTrue(expresion.match(valido))
                self.assertIsNone(expresion.match(valido + "\n"))
        self.assertTrue(any("`paquetes`" in e for e in errores("rance_es", ["a/x\n"])))
        self.assertIsNone(canales.REPOSITORIO.match("a/.."))
        self.assertIsNone(canales.REPOSITORIO.match("a/.\n"))


class TopeDeCanalesEnMain(unittest.TestCase):
    def catalogo(self):
        return particion.texto_json(todo_el_modelo())

    def test_cinco_mil_canales_en_el_peor_caso_caben(self):
        entrada = {"id": "a" * 20, "estado": "bloqueado", "verificado": False, "adultos": False,
                   "paquetes": ["a" * 39 + "/" + "b" * 99 + str(i) for i in range(3)]}
        por_canal = len(publicar._json(entrada)) + 1
        self.assertGreater(publicar.TOPE_CANALES_MAIN // por_canal, 5000)

    def test_si_se_pasa_no_frena_el_catalogo(self):
        archivos = base()
        archivos["canales/rance_es/canal.json"] = canal_json("rance_es", paquetes=["rance-es/parches"])
        tope = publicar.TOPE_CANALES_MAIN
        publicar.TOPE_CANALES_MAIN = 100
        try:
            # Con el catálogo de main distinto del que sale (otro título): el catálogo se escribe igual.
            modelo = todo_el_modelo()
            otro = json.loads(json.dumps(modelo).replace('"titulo": "', '"titulo": "X', 1))
            self.assertNotEqual(modelo, otro)
            avisos = []
            cambios = publicar.regenerados(archivos, particion.texto_json(otro), None, avisos)
            self.assertEqual([permisos.RUTA_CATALOGO], list(cambios))
            self.assertIn("no se actualiza", avisos[0])
            # Con el catálogo ya al día y los canales sin caber: nada (no sube la versión en cada publicación).
            self.assertIsNone(publicar.regenerados(archivos, cambios[permisos.RUTA_CATALOGO], None, []))
        finally:
            publicar.TOPE_CANALES_MAIN = tope


class IdAnterioresEnMain(unittest.TestCase):
    """Los @ de antes de cada canal en `catalogo/canales.json`, para que la app avise como `permisos.py` (D8)."""

    def catalogo(self):
        return particion.texto_json(todo_el_modelo())

    def canales(self, archivos):
        return {c["id"]: c for c in json.loads(publicar.regenerados(archivos, self.catalogo(), None)[publicar.RUTA_CANALES_MAIN])["canales"]}

    def test_salen_sus_ids_y_el_resto_queda_igual(self):
        archivos = base()
        archivos["canales/rance_es/canal.json"] = canal_json("rance_es", idAnteriores=[
            {"id": "rance_viejo", "hasta": "2026-10-01"}, {"id": "rance_viejo", "hasta": "2026-10-02"},
            {"id": "rance_es", "hasta": "2026-10-03"}, {"id": "No Vale", "hasta": "2026-10-04"}, "suelto", {"hasta": "x"},
            {"id": "rance_2025", "hasta": "2026-11-01", "desde": "2025-01-01"}])
        canales_main = self.canales(archivos)
        self.assertEqual(["rance_viejo", "rance_2025"], canales_main["rance_es"]["idAnteriores"])
        # Sin @ anteriores, la entrada es la de siempre (mismas claves).
        self.assertEqual({"id", "estado", "verificado", "paquetes", "adultos"}, set(canales_main["viejo"]))
        # Y la app sigue leyendo un canales.json viejo sin el campo: es solo un campo más.
        self.assertNotIn("idAnteriores", canales_main["ornizen"])

    def test_muchos_ids_anteriores_caben(self):
        archivos = base()
        anteriores = [{"id": f"a{i:019d}", "hasta": "2026-01-01"} for i in range(1000)]
        archivos["canales/rance_es/canal.json"] = canal_json("rance_es", idAnteriores=anteriores)
        self.assertEqual(1000, len(self.canales(archivos)["rance_es"]["idAnteriores"]))

    def test_un_anterior_como_el_esqueleto_de_otro_canal_sale_igual(self):
        # Es de quien es: el robot no decide aquí quién se parece a quién; solo lo copia para la app.
        archivos = base()
        archivos["canales/rance_es/canal.json"] = canal_json("rance_es", idAnteriores=[{"id": "vlejo", "hasta": "2026-10-01"}])
        self.assertEqual(["vlejo"], self.canales(archivos)["rance_es"]["idAnteriores"])
        self.assertEqual(canales.esqueleto("viejo"), canales.esqueleto("vlejo"))

    def test_si_con_ellos_no_cabe_se_escribe_sin_ellos(self):
        archivos = base()
        archivos["canales/rance_es/canal.json"] = canal_json("rance_es", idAnteriores=[
            {"id": f"a{i:019d}", "hasta": "2026-01-01"} for i in range(200)])
        sin = len(publicar._json({"esquema": 1, "versionCatalogo": publicar.lector_app.VERSION_MAXIMA,
                                  "canales": publicar.canales_para_main(archivos, con_anteriores=False)}))
        tope = publicar.TOPE_CANALES_MAIN
        publicar.TOPE_CANALES_MAIN = sin + 10
        try:
            avisos = []
            cambios = publicar.regenerados(archivos, self.catalogo(), None, avisos)
            entradas = json.loads(cambios[publicar.RUTA_CANALES_MAIN])["canales"]
            self.assertFalse(any("idAnteriores" in c for c in entradas))
            self.assertIn("sin ellos", avisos[0])
            self.assertLessEqual(len(cambios[publicar.RUTA_CANALES_MAIN]), publicar.TOPE_CANALES_MAIN)
        finally:
            publicar.TOPE_CANALES_MAIN = tope

    def test_un_canal_json_roto_no_rompe_nada(self):
        self.assertEqual([], publicar._ids_anteriores({"canales/x/canal.json": b"{"}, "x"))
        self.assertEqual([], publicar._ids_anteriores({}, "x"))
        self.assertEqual([], publicar._ids_anteriores({"canales/x/canal.json": b'{"idAnteriores": 5}'}, "x"))


class Confundibles(unittest.TestCase):
    def test_ya_r(self):
        for nombre in ("OЯNIZ", "oяniz", "Oяnizen"):
            with self.subTest(nombre=nombre):
                self.assertTrue(canales.esqueleto(nombre).startswith(canales.esqueleto("orniz")))
                self.assertTrue(canales.nombre_reservado(nombre))


if __name__ == "__main__":
    unittest.main()
